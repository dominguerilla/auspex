"""
CONCEPT: Centralized LLM Construction
======================================
This file is given complete. Read it carefully — understanding it unblocks every agent.

Pattern: Factory function
  get_llm() is a factory: it reads config from the environment and returns a
  fully-configured ChatOllama instance. Every agent imports THIS function instead
  of constructing its own LLM. This means:
    - One place to change the model, temperature, or base URL
    - Agents don't need to know anything about Ollama — they just call llm.invoke()
    - Swapping the model (qwen2.5:3b → qwen2.5:7b) requires only a .env change

LangChain's ChatOllama speaks the same interface as ChatOpenAI, ChatAnthropic, etc.
That interface is: llm.invoke(messages) → AIMessage. The messages argument is a list
of LangChain message objects (HumanMessage, SystemMessage, AIMessage).
"""

import os
from dotenv import load_dotenv
from langchain_ollama import ChatOllama

load_dotenv()


def get_llm(temperature: float = 0.3) -> ChatOllama:
    """
    Return a configured ChatOllama instance.

    Parameters
    ----------
    temperature : float
        Controls randomness. 0.0 = deterministic, 1.0 = creative.
        Agents that need structured output (orchestrator, critic) should use
        lower temperatures. The writer can use slightly higher values.

    Environment variables read
    --------------------------
    OLLAMA_BASE_URL : str  (default: http://localhost:11434)
    OLLAMA_MODEL    : str  (default: qwen2.5:3b)

    Returns
    -------
    ChatOllama
        Drop-in compatible with any LangChain chat model.
    """
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    model = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")

    return ChatOllama(
        base_url=base_url,
        model=model,
        temperature=temperature,
    )
