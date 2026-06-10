---
name: setup
description: Set up the auspex development environment from scratch on a new machine.
last_verified: 2026-06-10
sources: [requirements.txt, .env.example, pyproject.toml]
---

# Setup

## When to use

Starting on a new machine, after a fresh clone, or after the Python version or dependencies change.

## Steps

1. **Create and activate a virtual environment:**
   ```sh
   python -m venv .venv
   source .venv/bin/activate        # Windows: .venv\Scripts\activate
   ```

2. **Install dependencies:**
   ```sh
   pip install -r requirements.txt
   ```

3. **Configure environment:**
   ```sh
   cp .env.example .env
   # Edit .env — set LLM_PROVIDER and the relevant provider vars
   ```

4. **If using Ollama (local, default):** start the Ollama server and pull the model:
   ```sh
   ollama serve                  # in a separate terminal if not running as a service
   ollama pull qwen2.5:3b
   ```

5. **If using HuggingFace:** ensure `HF_TOKEN` is set in `.env`.

6. **Verify:**
   ```sh
   pytest                        # all tests should pass (no LLM or network needed)
   ruff check .                  # should be clean
   python main.py "Test question"
   ```

## Verify

- `pytest` exits 0 with all tests passing.
- `ruff check .` exits 0 with no output.
- `python main.py "..."` runs to completion and writes a file to `output/`.
