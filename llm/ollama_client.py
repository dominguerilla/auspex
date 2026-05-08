"""
CONCEPT: Centralized LLM Construction
======================================
Factory pattern: get_llm() reads config from the environment and returns a
LangChain chat model. Every agent imports THIS function instead of constructing
its own LLM, so swapping providers is a config change — not a code change.

Two providers are supported, selected by the LLM_PROVIDER env var:

  LLM_PROVIDER=ollama       (default — local development)
    Reads OLLAMA_BASE_URL, OLLAMA_MODEL. Returns ChatOllama.

  LLM_PROVIDER=huggingface  (cloud deployment, e.g. HF Spaces)
    Reads HF_TOKEN, HF_MODEL. Returns ChatHuggingFace wrapping a
    HuggingFaceEndpoint that calls the HF Inference API.

Both providers return objects implementing LangChain's BaseChatModel interface,
so agents call llm.invoke(messages) without caring which backend is live.
"""

import os

from dotenv import load_dotenv

load_dotenv()


def get_llm(temperature: float = 0.3):
    """
    Return a LangChain chat model configured from the environment.

    Parameters
    ----------
    temperature : float
        Controls randomness. 0.0 = deterministic, 1.0 = creative.

    Environment variables read
    --------------------------
    LLM_PROVIDER     : "ollama" | "huggingface"  (default: "ollama")
    OLLAMA_BASE_URL  : str  (default: http://localhost:11434)
    OLLAMA_MODEL     : str  (default: qwen2.5:3b)
    HF_TOKEN         : str  (required when LLM_PROVIDER=huggingface)
    HF_MODEL         : str  (default: meta-llama/Llama-3.1-8B-Instruct)

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
            model=os.getenv("OLLAMA_MODEL", "qwen2.5:3b"),
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
            repo_id=os.getenv("HF_MODEL", "meta-llama/Llama-3.1-8B-Instruct"),
            task="text-generation",
            huggingfacehub_api_token=token,
            temperature=temperature,
            max_new_tokens=1024,
        )
        return ChatHuggingFace(llm=endpoint)

    raise ValueError(
        f"Unknown LLM_PROVIDER={provider!r}. Expected 'ollama' or 'huggingface'."
    )
