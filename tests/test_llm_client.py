"""Tests for llm.ollama_client.describe_llm()."""

import os
from unittest.mock import patch

from llm.ollama_client import describe_llm


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


def test_describe_unknown_provider_falls_back_to_raw_label():
    with patch.dict(os.environ, {"LLM_PROVIDER": "vllm"}, clear=True):
        info = describe_llm()
    assert info["provider"] == "vllm"
    assert info["model"] == ""
    # Unknown providers fall through to their raw name as label.
    assert info["provider_label"] == "vllm"
