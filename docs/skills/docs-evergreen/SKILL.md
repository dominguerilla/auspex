---
name: docs-evergreen
description: Check all permanent docs for drift — stale last_verified dates, broken internal links, or sources that changed since the doc was last checked.
last_verified: 2026-06-10
sources: [docs/, AGENTS.md]
---

# Docs Evergreen

## When to use

After any non-trivial code change (new agent, changed state fields, new env var, removed file), before a release, or when docs feel out of date.

## Steps

1. **Find all permanent docs with front-matter:**
   ```sh
   grep -rl "last_verified:" docs/ AGENTS.md LEARNING.md
   ```

2. **For each doc, check if its `sources:` files changed since `last_verified`:**
   ```sh
   # Example: check if architecture.md sources changed since 2026-06-10
   git log --since="2026-06-10" --oneline -- \
     graph/graph_builder.py graph/state.py graph/edges.py \
     agents/ llm/ollama_client.py llm/contract.py tools/ app.py prompts/
   ```
   Any output means the doc may be stale.

3. **Check for broken internal links** (links to paths that no longer exist):
   ```sh
   # Extract all markdown links from docs
   grep -rh '\[.*\](\.\./\|\./' docs/ AGENTS.md | grep -oP '\(([^)]+)\)' | tr -d '()'
   ```
   Manually verify each path still exists.

4. **Update stale docs:**
   - Update the prose to match the current code.
   - Update `last_verified:` to today's date.
   - Update `sources:` if the relevant files changed.

5. **Update `docs/DISCOVERY.md`** if the repo structure changed significantly (it is a transient/scratchpad doc, not permanent, but it should not mislead).

## Verify

- No `git log` output for any doc's sources (nothing changed since `last_verified`), or all changes are accounted for in the updated docs.
- All internal links resolve to existing files.
- All permanent docs have `last_verified` dates within the last release cycle.
