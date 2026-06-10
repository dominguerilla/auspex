---
name: add-agent
description: Add a new agent node to the LangGraph pipeline — from prompt file through state fields, graph wiring, and tests.
last_verified: 2026-06-10
sources: [agents/, graph/graph_builder.py, graph/state.py, graph/edges.py, prompts/, tests/]
---

# Add Agent

## When to use

Adding a new processing step to the pipeline (e.g., a fact-checker, a source ranker, a human-review pause).

## Steps

1. **Add any new state fields** to `graph/state.py`:
   - Decide the reducer: last-write-wins (default) or append (`Annotated[List[...], add_messages]`).
   - Add the field to `ResearchState` with a type annotation and optional docstring.
   - Update `base_state` in `tests/conftest.py` to include the new field (with a zero/empty default).

2. **Write the prompt file** at `prompts/<name>.txt`:
   - Use `{placeholder}` syntax matching the keys you'll pass to `.format(...)`.
   - If the prompt includes pass/fail markers or citation formats, reference constants from `llm/contract.py` — do not hardcode the literal strings.

3. **Write the agent function** at `agents/<name>.py`:
   ```python
   from pathlib import Path
   from langchain_core.messages import HumanMessage
   from graph.state import ResearchState
   from llm.ollama_client import get_llm

   _PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "<name>.txt"

   def run_<name>(state: ResearchState) -> dict:
       llm = get_llm(temperature=0.X)
       prompt = _PROMPT_PATH.read_text().format(
           field=state["field"], ...
       )
       response = llm.invoke([HumanMessage(content=prompt)])
       # parse response.content → structured output
       return {"output_field": parsed_value}
   ```

4. **Register the node** in `graph/graph_builder.py`:
   ```python
   from agents.<name> import run_<name>
   graph.add_node("<name>", run_<name>)
   ```

5. **Wire edges** in `graph/graph_builder.py`:
   - For a linear step: `graph.add_edge("predecessor", "<name>")` and `graph.add_edge("<name>", "successor")`.
   - For a conditional branch: add a routing function to `graph/edges.py` and use `graph.add_conditional_edges(...)`.
   - If the routing function's return values change, update the mapping dict passed to `add_conditional_edges`.

6. **Update `NODE_ORDER`** in `app.py:49` if the new node should appear in the frontend's spirit-to-node mapping.

7. **Write tests** in `tests/test_<name>.py`:
   - Patch `get_llm` to return `mock_llm` (from `tests/conftest.py`).
   - Set `mock_llm.invoke.return_value.content` to a representative LLM response.
   - Assert the returned dict has the correct keys and values.

## Verify

```sh
pytest tests/test_<name>.py -v     # new tests pass
pytest -x                          # full suite still passes
ruff check .                       # no lint errors
python main.py "Test question"     # end-to-end run completes
```

Check that `final_state["<output_field>"]` contains the expected value in a manual run.
