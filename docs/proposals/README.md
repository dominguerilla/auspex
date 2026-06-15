# Design Proposals

Numbered, RFC-style notes for **future work that hasn't been committed to yet**.
Each one captures a problem, a sketch of a design, the tradeoffs, and a
recommended incremental path — enough that future Carlos can pick it up, decide
whether it's worth doing, and start without re-deriving the whole discussion.

These are *proposals*, not decisions. A proposal that gets built should have its
`Status` updated (and ideally a short "what actually happened" note appended).

## Convention

- Filename: `NNNN-short-slug.md` (zero-padded, monotonically increasing).
- Each doc starts with a header block: `Status`, `Created`, `Owner`, `Related`.
- `Status` is one of: `Proposed` · `Accepted` · `In progress` · `Implemented` · `Rejected` · `Superseded`.

## Index

| # | Title | Status |
|---|-------|--------|
| [0001](0001-source-router.md) | Source router: pluggable, classified research sources | Proposed |
| [0002](0002-hosting-auspex.md) | Hosting Auspex: online MCP server, daily-report to customer-grade | Proposed |
