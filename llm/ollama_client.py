"""
CONCEPT: Centralized LLM Construction
======================================
Factory pattern: get_llm() reads config from the environment and returns a
LangChain chat model. Every agent imports THIS function instead of constructing
its own LLM, so swapping providers is a config change — not a code change.

Providers are declared once in the PROVIDERS registry. get_llm() constructs the
client and describe_llm() reports it; both read the registry, so they cannot
drift. There are four construction paths:

  LLM_PROVIDER=ollama            (default — local development)
    Reads OLLAMA_BASE_URL, OLLAMA_MODEL. Returns ChatOllama (native API).

  LLM_PROVIDER=huggingface       (cloud deployment, e.g. HF Spaces)
    Reads HF_TOKEN, HF_MODEL. Returns ChatHuggingFace wrapping a
    HuggingFaceEndpoint that calls the HF Inference API.

  LLM_PROVIDER=anthropic         (cloud deployment — Claude)
    Reads ANTHROPIC_API_KEY, ANTHROPIC_MODEL. Returns ChatAnthropic (native
    Anthropic API). temperature is forwarded only for models that accept it
    (Haiku 4.5, Sonnet 4.6); newer models (Opus 4.8, Fable 5) reject it.

  OpenAI-compatible              (everything else — returns ChatOpenAI)
    Any registry entry with a "key_env" is reached through one shared path:
      - named presets carry their own base_url + key env var + default model,
        so e.g. LLM_PROVIDER=nous + NOUS_API_KEY just works; and
      - LLM_PROVIDER=openai_compatible reads OPENAI_BASE_URL / OPENAI_API_KEY /
        OPENAI_MODEL, for any endpoint without a preset (Together, Fireworks,
        OpenRouter, vLLM, ...).
    Adding a named OpenAI-compatible portal is a registry entry, not a branch.

All providers return objects implementing LangChain's BaseChatModel interface,
so agents call llm.invoke(messages) without caring which backend is live.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# Single source of truth for provider metadata. get_llm() (construction) and
# describe_llm() (the /config display) both read this, and evals/adapter.py
# imports describe_llm() — so the model name a run reports can't drift from the
# model it actually used.
#   model_env      : env var that overrides the model
#   default_model  : used when model_env is unset ("" = no sensible default)
# OpenAI-compatible providers additionally carry:
#   key_env        : env var holding the API key (its presence marks the
#                    provider as OpenAI-compatible — i.e. built via ChatOpenAI)
#   base_url       : fixed endpoint for a named preset, or None to read
#                    OPENAI_BASE_URL at call time (the generic provider)
#   help           : appended to the error raised when required env is missing
PROVIDERS: dict[str, dict] = {
    "ollama": {
        "label": "Ollama",
        "model_env": "OLLAMA_MODEL",
        "default_model": "qwen2.5:3b",
    },
    "huggingface": {
        "label": "HF Inference",
        "model_env": "HF_MODEL",
        "default_model": "meta-llama/Llama-3.1-8B-Instruct",
    },
    "anthropic": {
        # Native Claude provider. No "key_env" here on purpose: that marker
        # routes a provider through the shared OpenAI-compatible path, but
        # Anthropic has its own branch in get_llm() (ChatAnthropic), so it must
        # not carry it. Model IDs: https://docs.claude.com/en/docs/about-claude/models
        "label": "Anthropic",
        "model_env": "ANTHROPIC_MODEL",
        "default_model": "claude-haiku-4-5",
    },
    "nous": {
        # Model IDs are listed at https://portal.nousresearch.com/api-docs
        "label": "Nous Portal",
        "model_env": "NOUS_MODEL",
        "default_model": "hermes-3-llama-3.1-70b",
        "key_env": "NOUS_API_KEY",
        "base_url": "https://inference-api.nousresearch.com/v1",
        "help": "Generate a key at https://portal.nousresearch.com and "
        "export it as NOUS_API_KEY.",
    },
    "openai_compatible": {
        # No preset: the endpoint dictates the URL and valid model IDs, so
        # OPENAI_BASE_URL and OPENAI_MODEL are required alongside the key.
        "label": "OpenAI-compatible",
        "model_env": "OPENAI_MODEL",
        "default_model": "",
        "key_env": "OPENAI_API_KEY",
        "base_url": None,
        "help": "Point OPENAI_BASE_URL at the endpoint's /v1 URL and set "
        "OPENAI_API_KEY and OPENAI_MODEL.",
    },
}


def _resolved_model(provider: str) -> str:
    """Model the given provider would use, honoring its model_env override."""
    spec = PROVIDERS[provider]
    return os.getenv(spec["model_env"], spec["default_model"])


# Anthropic models that reject sampling params (temperature/top_p/top_k) — they
# return HTTP 400 if temperature is sent. Current as of the Claude 4.x family
# (2026-06); Haiku 4.5 and Sonnet 4.6 still accept it. The default is to forward
# temperature, so a new model is treated as accepting it until proven otherwise.
_ANTHROPIC_NO_SAMPLING = (
    "claude-opus-4-7",
    "claude-opus-4-8",
    "claude-fable-5",
    "claude-mythos-5",
)


def _anthropic_accepts_temperature(model: str) -> bool:
    """Whether the given Anthropic model accepts a temperature parameter."""
    return not model.startswith(_ANTHROPIC_NO_SAMPLING)


def describe_llm() -> dict:
    """Return the provider/model the next get_llm() call would construct.

    Used by the FastAPI /config endpoint so the UI shows the same model name
    the agents will actually run against, without duplicating the defaults.
    """
    provider = os.getenv("LLM_PROVIDER", "ollama").lower()
    spec = PROVIDERS.get(provider)
    return {
        "provider": provider,
        "model": _resolved_model(provider) if spec else "",
        "provider_label": spec["label"] if spec else provider,
    }


def _build_openai_compatible(provider: str, temperature: float):
    """Construct a ChatOpenAI for any OpenAI-compatible provider.

    Handles both named presets (fixed base_url + dedicated key env var) and the
    generic ``openai_compatible`` provider (base_url + model read from env).
    """
    spec = PROVIDERS[provider]
    base_url = spec["base_url"] or os.getenv("OPENAI_BASE_URL")
    api_key = os.getenv(spec["key_env"])
    model = _resolved_model(provider)

    # A named preset supplies base_url/model itself, so only the key can be
    # missing; the generic provider needs all three from the environment.
    # Validate before importing so a misconfig fails fast with a clear message
    # rather than first dragging in the (heavy) openai client.
    required = {spec["key_env"]: api_key}
    if spec["base_url"] is None:
        required["OPENAI_BASE_URL"] = base_url
        required["OPENAI_MODEL"] = model
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError(
            f"LLM_PROVIDER={provider} requires {', '.join(missing)} to be set. "
            + spec["help"]
        )

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        base_url=base_url,
        api_key=api_key,
        model=model,
        temperature=temperature,
    )


def get_llm(temperature: float = 0.3):
    """
    Return a LangChain chat model configured from the environment.

    Parameters
    ----------
    temperature : float
        Controls randomness. 0.0 = deterministic, 1.0 = creative.

    Environment variables read
    --------------------------
    LLM_PROVIDER     : see PROVIDERS keys  (default: "ollama")
    OLLAMA_BASE_URL  : str  (default: http://localhost:11434)
    OLLAMA_MODEL     : str  (default: qwen2.5:3b)
    HF_TOKEN         : str  (required when LLM_PROVIDER=huggingface)
    HF_MODEL         : str  (default: meta-llama/Llama-3.1-8B-Instruct)
    NOUS_API_KEY     : str  (required when LLM_PROVIDER=nous)
    NOUS_MODEL       : str  (default: hermes-3-llama-3.1-70b)
    ANTHROPIC_API_KEY: str  (required when LLM_PROVIDER=anthropic)
    ANTHROPIC_MODEL  : str  (default: claude-haiku-4-5)
    OPENAI_BASE_URL  : str  (required when LLM_PROVIDER=openai_compatible)
    OPENAI_API_KEY   : str  (required when LLM_PROVIDER=openai_compatible)
    OPENAI_MODEL     : str  (required when LLM_PROVIDER=openai_compatible)

    Returns
    -------
    BaseChatModel
        A LangChain chat model. Callers use llm.invoke(messages).
    """
    provider = os.getenv("LLM_PROVIDER", "ollama").lower()

    if provider == "ollama":
        from langchain_ollama import ChatOllama

        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        # ChatOllama uses the native Ollama API, not the OpenAI-compatible /v1 path.
        # Strip /v1 so OLLAMA_BASE_URL can be set to either form.
        base_url = base_url.rstrip("/").removesuffix("/v1")
        return ChatOllama(
            base_url=base_url,
            model=_resolved_model("ollama"),
            temperature=temperature,
        )

    if provider == "huggingface":
        from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint

        token = os.getenv("HF_TOKEN")
        if not token:
            raise RuntimeError(
                "LLM_PROVIDER=huggingface but HF_TOKEN is not set. "
                "Create a token at https://huggingface.co/settings/tokens "
                "and export it as HF_TOKEN."
            )

        endpoint = HuggingFaceEndpoint(
            repo_id=_resolved_model("huggingface"),
            task="text-generation",
            huggingfacehub_api_token=token,
            temperature=temperature,
            max_new_tokens=1024,
        )
        return ChatHuggingFace(llm=endpoint)

    if provider == "anthropic":
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set. "
                "Generate a key at https://console.anthropic.com and export it "
                "as ANTHROPIC_API_KEY."
            )

        model = _resolved_model("anthropic")
        # Newer Claude models (Opus 4.8, Fable 5) reject temperature; Haiku 4.5
        # and Sonnet 4.6 accept it. Only forward it when the model takes it, so
        # the shared get_llm(temperature=...) contract degrades gracefully.
        kwargs = {"model": model, "api_key": api_key}
        if _anthropic_accepts_temperature(model):
            kwargs["temperature"] = temperature

        # Import after validation so a misconfig fails fast without dragging in
        # the (heavy) Anthropic client — same pattern as _build_openai_compatible.
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(**kwargs)

    # Every OpenAI-compatible provider (named preset or generic) shares one
    # construction path, marked in the registry by a "key_env" entry.
    spec = PROVIDERS.get(provider)
    if spec and "key_env" in spec:
        return _build_openai_compatible(provider, temperature)

    raise ValueError(
        f"Unknown LLM_PROVIDER={provider!r}. Expected one of: "
        f"{', '.join(sorted(PROVIDERS))}."
    )
