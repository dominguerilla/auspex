---
last_verified: 2026-06-10
sources: [tools/web_search.py, tools/web_scraper.py, llm/ollama_client.py, app.py, Dockerfile]
owner: Carlos
status: draft
---

# Troubleshooting

## DuckDuckGo rate-limiting (HTTP 202 / 429)

**Symptom:** `search_results` is empty (`[]`) for one or more queries; the run completes but the report is thin or factually sparse.

**Cause:** DuckDuckGo's `ddgs` library returns an empty list rather than raising when rate-limited. This is intentional — `tools/web_search.py` degrades gracefully.

**Fixes:**
- Reduce `--max-iterations` to cut the number of search rounds.
- Add a short delay between runs if re-running quickly.
- When running evals: use `--concurrency 1` (`python -m evals.run --concurrency 1`) to serialize search calls.
- The rate limit resets within seconds to minutes — retry the run.

---

## Scraper blocked by paywalled sites (HTTP 403 / 429)

**Symptom:** `sources` contains entries with empty or one-line summaries; the report cites URLs but has no real content from them. Logged as warnings in the reader agent.

**Cause:** Academic and news sites (ScienceDirect, ResearchGate, PsycNet, SSRN, etc.) return 403 or 429 to `requests`. `tools/web_scraper.py` returns `""` on these errors rather than raising. The reader agent skips or minimally summarises these sources.

**Fix (short-term):** Rephrase the research question to target less paywalled domains, or accept the quality degradation.

**Fix (longer-term):** See [docs/proposals/0001-source-router.md](../proposals/0001-source-router.md) — adding OpenAlex / Wikipedia as provider alternatives.

---

## Ollama not running

**Symptom:** `RuntimeError` or `ConnectionRefusedError` when the CLI or server starts; the error message mentions `localhost:11434`.

**Cause:** `LLM_PROVIDER=ollama` is set (the default) but the Ollama server is not running.

**Fix:**
```sh
ollama serve          # start the server
ollama pull qwen2.5:3b  # if the model hasn't been downloaded yet
```

Also check that `OLLAMA_BASE_URL` in `.env` matches where Ollama is actually listening.

---

## `HF_TOKEN` not set

**Symptom:** `RuntimeError: LLM_PROVIDER=huggingface but HF_TOKEN is not set.`

**Cause:** `.env` has `LLM_PROVIDER=huggingface` but `HF_TOKEN` is missing or empty. Source: `llm/ollama_client.py:96-101`.

**Fix:** Create a HuggingFace access token at https://huggingface.co/settings/tokens and add it to `.env`:
```
HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxx
```

---

## Unknown LLM provider

**Symptom:** `ValueError: Unknown LLM_PROVIDER='xyz'. Expected 'ollama' or 'huggingface'.`

**Cause:** `LLM_PROVIDER` in `.env` is set to an unsupported value. Source: `llm/ollama_client.py:112-114`.

**Fix:** Set `LLM_PROVIDER` to exactly `ollama` or `huggingface` (lowercase).

---

## Jobs not persisting across HF Spaces redeploys

**Symptom:** Shareable `/r/{job_id}` URLs return 404 after a redeploy.

**Cause:** `jobs.db` (SQLite) lives on the container's ephemeral filesystem. It is wiped on every redeploy. Source: `app.py:16-17`, `README.md:138-139`.

**There is no fix** — this is a known limitation of the free HF Spaces tier. The UI surfaces this in the "About this report" rail.

---

## Windows: garbled Unicode in the terminal

**Symptom:** Arrows, em-dashes, or emoji in LLM output appear as `?` or mojibake on Windows.

**Cause:** Windows console defaults to a non-UTF-8 code page.

**Fix:** `main.py` and `app.py` both call `configure_utf8_console()` from `console_utf8.py` at startup, which sets the console to UTF-8. If you see this in a test or script that doesn't call that function, add `import sys; sys.stdout.reconfigure(encoding='utf-8')` at the top.

---

## Critic always fails / all critiques default to FAILED

**Symptom:** The graph always exhausts `max_iterations` before writing; the final report is produced by the writer after the cap, not after a genuine pass.

**Cause:** The critic prompt literal or the `CRITIC_PASS` / `CRITIC_FAIL` constants in `llm/contract.py` are out of sync. If the prompt tells the LLM to respond "PASS" but the parser looks for "PASSED", every critique parses as failed. Source: `llm/contract.py`.

**Fix:** Check that `prompts/critic.txt` uses exactly the strings defined in `llm/contract.py:CRITIC_PASS` and `CRITIC_FAIL`. Change both together.

---

## Ruff CI failures

**Symptom:** CI fails on the ruff step with import-order, unused-import, or whitespace errors.

**Fix:**
```sh
ruff check --fix .   # auto-fix safe rules (import sort, unused imports, whitespace)
ruff check .         # verify clean
```

Commit the fixes before pushing.
