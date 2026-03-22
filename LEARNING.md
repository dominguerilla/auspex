# Learning Guide: LangGraph + Agentic Patterns

This file maps vocabulary to the actual code so you can explain every piece in an interview.

---

## Core Vocabulary

### StateGraph
`StateGraph` is LangGraph's main class. It holds the graph structure (nodes + edges) but is NOT yet runnable. You register nodes, add edges, then call `.compile()` to get a `CompiledGraph` (a runnable Pregel object).

**In the code:** `graph/graph_builder.py` — `graph = StateGraph(ResearchState)`

### Node
A node is a Python function with the signature:
```python
def my_node(state: ResearchState) -> dict:
    ...
    return {"some_field": new_value}
```
LangGraph calls each node with the full current state. The node returns a **partial update dict** — only the fields it changes. LangGraph merges this into the state.

**In the code:** Every function in `agents/` is a node. They're registered with `graph.add_node("name", function)`.

### Edge
A directed connection between nodes. `graph.add_edge("a", "b")` means: after node `a` completes, always go to node `b`.

**In the code:** `graph/graph_builder.py` — the edges you wire in Phase 2.

### Conditional Edge
An edge whose target depends on a **routing function**. The routing function receives state and returns a string key that maps to the next node name.

```python
graph.add_conditional_edges(
    "critic",                      # source node
    should_revise_or_write,        # routing function → returns "searcher" or "writer"
    {"searcher": "searcher", "writer": "writer"}  # string → node name mapping
)
```

**In the code:** `graph/edges.py` + `graph/graph_builder.py` — this is what makes the graph a loop instead of a pipeline.

### Reducer
When a node returns an update, LangGraph merges it into state. The merge strategy per field is called a **reducer**.

- **Default reducer** (last write wins): `search_results`, `sources`, `critique`, etc.
- **`add_messages` reducer**: `messages` — appends new messages instead of replacing the list.

```python
messages: Annotated[List[BaseMessage], add_messages]
#                                       ^^^^^^^^^^^^
#                                       This is the reducer
```

**In the code:** `graph/state.py` line with `Annotated`.

### TypedDict
LangGraph requires TypedDict for the top-level state schema. It's just Python type hints — no runtime validation. Think of it as documentation that also enables IDE autocomplete.

**In the code:** `graph/state.py` — `ResearchState`, `SearchResult`, `ScrapedSource`, `CritiqueResult`.

---

## Data Flow: Trace a Research Run

```
main.py
  │ initial_state = {"research_question": "...", "iteration": 0, ...}
  │ graph.invoke(initial_state)
  ▼
orchestrator
  │ reads:  state["research_question"]
  │ writes: state["search_queries"] = ["query 1", "query 2", ...]
  ▼
searcher
  │ reads:  state["search_queries"]
  │ writes: state["search_results"] = [SearchResult(...), ...]
  ▼
reader
  │ reads:  state["search_results"], state["research_question"]
  │ writes: state["sources"] = [ScrapedSource(...), ...]
  ▼
critic
  │ reads:  state["sources"], state["research_question"]
  │ writes: state["critique"] = CritiqueResult(passed=False, ...)
  │         state["iteration"] = 1
  ▼
should_revise_or_write(state)  ← routing function
  │ if critique.passed == False AND iteration < max_iterations:
  │     → "searcher"  (loop back)
  │ else:
  │     → "writer"
  ▼
writer
  │ reads:  state["sources"], state["research_question"], state["critique"]
  │ writes: state["final_report"] = "# Report..."
  ▼
END → main.py reads state["final_report"], writes file
```

---

## Why These Patterns?

### Why a graph instead of a simple Python for-loop?
- **Observability**: LangSmith can trace every node execution with inputs/outputs
- **Interruptibility**: LangGraph supports human-in-the-loop — you can pause at any node and inject human feedback
- **Scalability**: nodes can be parallelised (LangGraph supports parallel branches)
- **Restartability**: checkpointing lets you resume from any node after a crash

### Why separate prompts/*.txt files?
Prompts are artifacts, not code. Separating them means:
- You can iterate on prompts without touching Python
- Designers or PMs can edit prompts
- Prompts can be versioned, A/B tested, or loaded from a database

### Why TypedDict for state vs Pydantic BaseModel?
LangGraph uses TypedDict because it needs to JSON-serialise state for checkpointing and streaming. Pydantic models add validation overhead and serialisation complexity. TypedDict is zero-overhead at runtime.

---

## Interview Questions You Should Be Able to Answer

1. **What is a StateGraph and how does it differ from a simple function chain?**
2. **What is a reducer? Why does `messages` use `add_messages` while `sources` uses the default?**
3. **What is a conditional edge? Where is it used in this project and why?**
4. **How does the critic loop terminate? What prevents infinite loops?**
5. **Why does `get_llm()` exist as a factory function rather than each agent constructing its own?**
6. **What would you change to add a new agent (e.g. a fact-checker) to this graph?**
7. **How would you add human-in-the-loop review before the writer runs?**
