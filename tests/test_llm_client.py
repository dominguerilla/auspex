"""Tests for llm.ollama_client.describe_llm() and the Anthropic provider."""

import os
from unittest.mock import patch

import pytest

from llm.ollama_client import _anthropic_accepts_temperature, describe_llm, get_llm


def test_describe_defaults_to_ollama_qwen():
    with patch.dict(os.environ, {}, clear=True):
        info = describe_llm()
    assert info == {
        "provider": "ollama",
        "model": "qwen2.5:3b",
        "provider_label": "Ollama",
    }


def test_describe_respects_ollama_model_override():
    with patch.dict(os.environ, {"LLM_PROVIDER": "ollama", "OLLAMA_MODEL": "llama3:8b"}, clear=True):
        info = describe_llm()
    assert info["provider"] == "ollama"
    assert info["model"] == "llama3:8b"
    assert info["provider_label"] == "Ollama"


def test_describe_huggingface_with_defaults():
    with patch.dict(os.environ, {"LLM_PROVIDER": "huggingface"}, clear=True):
        info = describe_llm()
    assert info == {
        "provider": "huggingface",
        "model": "meta-llama/Llama-3.1-8B-Instruct",
        "provider_label": "HF Inference",
    }


def test_describe_respects_hf_model_override():
    with patch.dict(
        os.environ, {"LLM_PROVIDER": "huggingface", "HF_MODEL": "mistralai/Mistral-7B"}, clear=True
    ):
        info = describe_llm()
    assert info["model"] == "mistralai/Mistral-7B"
    assert info["provider_label"] == "HF Inference"


def test_describe_uppercase_provider_normalized():
    with patch.dict(os.environ, {"LLM_PROVIDER": "OLLAMA"}, clear=True):
        info = describe_llm()
    assert info["provider"] == "ollama"
    assert info["provider_label"] == "Ollama"


def test_describe_nous_with_defaults():
    with patch.dict(os.environ, {"LLM_PROVIDER": "nous"}, clear=True):
        info = describe_llm()
    assert info == {
        "provider": "nous",
        "model": "hermes-3-llama-3.1-70b",
        "provider_label": "Nous Portal",
    }


def test_describe_respects_nous_model_override():
    with patch.dict(
        os.environ, {"LLM_PROVIDER": "nous", "NOUS_MODEL": "hermes-3-llama-3.1-405b"}, clear=True
    ):
        info = describe_llm()
    assert info["model"] == "hermes-3-llama-3.1-405b"
    assert info["provider_label"] == "Nous Portal"


def test_describe_openai_compatible_reads_openai_model():
    with patch.dict(
        os.environ,
        {"LLM_PROVIDER": "openai_compatible", "OPENAI_MODEL": "meta-llama/Llama-3.3-70B-Instruct-Turbo"},
        clear=True,
    ):
        info = describe_llm()
    assert info == {
        "provider": "openai_compatible",
        "model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "provider_label": "OpenAI-compatible",
    }


def test_describe_openai_compatible_has_no_default_model():
    # Unlike named providers, the generic endpoint has no sensible default model.
    with patch.dict(os.environ, {"LLM_PROVIDER": "openai_compatible"}, clear=True):
        info = describe_llm()
    assert info["model"] == ""
    assert info["provider_label"] == "OpenAI-compatible"


def test_describe_unknown_provider_falls_back_to_raw_label():
    with patch.dict(os.environ, {"LLM_PROVIDER": "vllm"}, clear=True):
        info = describe_llm()
    assert info["provider"] == "vllm"
    assert info["model"] == ""
    # Unknown providers fall through to their raw name as label.
    assert info["provider_label"] == "vllm"


# --- Anthropic provider: describe_llm() reporting ---


def test_describe_anthropic_with_defaults():
    with patch.dict(os.environ, {"LLM_PROVIDER": "anthropic"}, clear=True):
        info = describe_llm()
    assert info == {
        "provider": "anthropic",
        "model": "claude-haiku-4-5",
        "provider_label": "Anthropic",
    }


def test_describe_respects_anthropic_model_override():
    with patch.dict(
        os.environ, {"LLM_PROVIDER": "anthropic", "ANTHROPIC_MODEL": "claude-sonnet-4-6"}, clear=True
    ):
        info = describe_llm()
    assert info["model"] == "claude-sonnet-4-6"
    assert info["provider_label"] == "Anthropic"


# --- Anthropic provider: temperature gating (pure) ---


def test_anthropic_accepts_temperature_for_haiku_and_sonnet():
    assert _anthropic_accepts_temperature("claude-haiku-4-5")
    assert _anthropic_accepts_temperature("claude-sonnet-4-6")


def test_anthropic_rejects_temperature_for_opus_and_fable():
    assert not _anthropic_accepts_temperature("claude-opus-4-8")
    assert not _anthropic_accepts_temperature("claude-opus-4-7")
    assert not _anthropic_accepts_temperature("claude-fable-5")


# --- Anthropic provider: get_llm() construction (ChatAnthropic mocked) ---


def test_get_llm_anthropic_builds_client_with_temperature():
    pytest.importorskip("langchain_anthropic")
    with (
        patch("langchain_anthropic.ChatAnthropic") as mock_chat,
        patch.dict(
            os.environ,
            {"LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "sk-ant-test"},
            clear=True,
        ),
    ):
        get_llm(temperature=0.3)
    # Haiku 4.5 (the default) accepts temperature, so it is forwarded.
    mock_chat.assert_called_once_with(
        model="claude-haiku-4-5", api_key="sk-ant-test", temperature=0.3
    )


def test_get_llm_anthropic_omits_temperature_for_no_sampling_model():
    pytest.importorskip("langchain_anthropic")
    env = {
        "LLM_PROVIDER": "anthropic",
        "ANTHROPIC_API_KEY": "sk-ant-test",
        "ANTHROPIC_MODEL": "claude-opus-4-8",
    }
    with (
        patch("langchain_anthropic.ChatAnthropic") as mock_chat,
        patch.dict(os.environ, env, clear=True),
    ):
        get_llm(temperature=0.3)
    # Opus 4.8 rejects temperature, so it must not be passed.
    mock_chat.assert_called_once_with(model="claude-opus-4-8", api_key="sk-ant-test")


def test_get_llm_anthropic_requires_api_key():
    with patch.dict(os.environ, {"LLM_PROVIDER": "anthropic"}, clear=True):
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            get_llm()
