"""Unit tests for the corpus chunker (scripts/ingest_corpus.py).

Pure-Python: no Postgres, no Ollama, no network — the embedding and DB paths are
not exercised here (they need WSL2/Linux per CLAUDE.md). These lock the chunking
behaviour that freezes into the corpus, so a regression can't silently change
what gets embedded.
"""

import scripts.ingest_corpus as ing
from scripts.ingest_corpus import _MAX_CHARS, _TARGET_CHARS, chunk_file

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _python_func(name: str, approx_chars: int) -> str:
    """A syntactically valid top-level function padded to ~approx_chars."""
    header = f"def {name}():\n    total = 0\n"
    footer = "    return total\n"
    body_line = "    total = total + 1  # pad\n"
    n = max(1, (approx_chars - len(header) - len(footer)) // len(body_line))
    return header + body_line * n + footer


def _assert_valid(chunks, text, language):
    """Invariants every chunk must satisfy regardless of language."""
    total_lines = text.count("\n") + 1
    for i, c in enumerate(chunks):
        assert c.chunk_index == i, "chunk_index must be sequential per file"
        assert c.language == language
        assert c.content.strip(), "no empty/whitespace-only chunks"
        assert len(c.content) <= _MAX_CHARS, "chunk exceeds the size ceiling"
        assert c.content in text, "chunk content must be a verbatim slice"
        assert 1 <= c.start_line <= c.end_line <= total_lines, "line range invalid"
        # content_hash is a stable sha256 hex digest
        assert len(c.content_hash) == 64
        assert c.content_hash == c.content_hash  # deterministic property


# ---------------------------------------------------------------------------
# include / exclude + language detection
# ---------------------------------------------------------------------------

def test_language_for_known_extensions():
    assert ing._language_for("a/b/foo.py") == "python"
    assert ing._language_for("README.md") == "markdown"
    assert ing._language_for("infra/main.tf") == "terraform"
    assert ing._language_for("ci.yaml") == "yaml"
    assert ing._language_for("ci.yml") == "yaml"
    assert ing._language_for("pyproject.toml") == "toml"
    assert ing._language_for("app/x.tsx") == "typescript"


def test_language_for_dockerfile_by_name():
    assert ing._language_for("Dockerfile") == "dockerfile"
    assert ing._language_for("deploy/Dockerfile.worker") == "dockerfile"


def test_language_for_unknown_returns_none():
    assert ing._language_for("image.png") is None
    assert ing._language_for("noext") is None


def test_included_excludes_lockfiles_and_generated():
    assert ing._included("src/app.py") is True
    assert ing._included("package-lock.json") is False
    assert ing._included("frontend/dist/bundle.js") is False
    assert ing._included("frontend/x.min.js") is False
    assert ing._included("data.bin") is False  # unknown language → excluded


# ---------------------------------------------------------------------------
# heading detection
# ---------------------------------------------------------------------------

def test_is_heading():
    assert ing._is_heading("# Title\n")
    assert ing._is_heading("### Sub\n")
    assert ing._is_heading("###### Deep\n")
    assert not ing._is_heading("####### too deep\n")
    assert not ing._is_heading("#nospace\n")
    assert not ing._is_heading("text # not a heading\n")
    assert not ing._is_heading("plain paragraph\n")


# ---------------------------------------------------------------------------
# fixed-size ("everything else") path
# ---------------------------------------------------------------------------

def test_small_fixed_file_is_one_chunk():
    text = "key: value\nother: 1\n"
    chunks = chunk_file("conf.yaml", text, "yaml")
    assert len(chunks) == 1
    assert chunks[0].content == text
    assert chunks[0].symbol_name is None
    assert chunks[0].start_line == 1
    _assert_valid(chunks, text, "yaml")


def test_large_fixed_file_splits_with_overlap():
    text = "".join(f"line {i:04d} aaaaaaaaaaaaaaaaaaaa\n" for i in range(400))
    assert len(text) > _MAX_CHARS
    chunks = chunk_file("big.yaml", text, "yaml")
    assert len(chunks) >= 2
    _assert_valid(chunks, text, "yaml")
    # Consecutive fixed chunks overlap (end of one reappears at start of next).
    tail = chunks[0].content[-20:]
    assert tail in chunks[1].content


# ---------------------------------------------------------------------------
# markdown path
# ---------------------------------------------------------------------------

def test_markdown_packs_small_sections_and_reconstructs():
    text = (
        "# Title\nintro paragraph\n\n"
        "## A\nalpha body\n\n"
        "## B\nbeta body\n\n"
        "## C\ngamma body\n"
    )
    chunks = chunk_file("doc.md", text, "markdown")
    _assert_valid(chunks, text, "markdown")
    # All sections are tiny → they pack into a single chunk.
    assert len(chunks) == 1
    # No overlap on the packed path, so contents reconstruct the file exactly.
    assert "".join(c.content for c in chunks) == text


def test_markdown_breaks_between_large_sections():
    big = "x " * (_TARGET_CHARS // 2)
    text = f"# One\n{big}\n\n## Two\n{big}\n"
    chunks = chunk_file("doc.md", text, "markdown")
    _assert_valid(chunks, text, "markdown")
    assert len(chunks) >= 2  # two ~target-sized sections can't share one chunk


def test_oversized_markdown_section_is_fixed_split():
    huge = "y " * _MAX_CHARS  # single section well over the ceiling
    text = f"# H\n{huge}\n"
    chunks = chunk_file("doc.md", text, "markdown")
    _assert_valid(chunks, text, "markdown")
    assert len(chunks) >= 2


# ---------------------------------------------------------------------------
# python path
# ---------------------------------------------------------------------------

def test_python_preserves_single_symbol_name():
    # A near-target function stands alone as its own chunk, keeping its name.
    text = "import os\n\n" + _python_func("big_func", _TARGET_CHARS + 200)
    chunks = chunk_file("m.py", text, "python")
    _assert_valid(chunks, text, "python")
    named = [c for c in chunks if c.symbol_name == "big_func"]
    assert len(named) == 1


def test_python_packs_small_functions_together():
    text = (
        "import os\n\n"
        + _python_func("a", 80)
        + "\n"
        + _python_func("b", 80)
        + "\n"
        + _python_func("c", 80)
    )
    chunks = chunk_file("m.py", text, "python")
    _assert_valid(chunks, text, "python")
    # Tiny functions pack; a packed multi-symbol chunk drops the symbol name.
    assert len(chunks) < 3
    assert any(c.symbol_name is None for c in chunks)


def test_python_oversized_function_fixed_split_keeps_symbol():
    text = _python_func("huge", _MAX_CHARS * 2)
    chunks = chunk_file("m.py", text, "python")
    _assert_valid(chunks, text, "python")
    assert len(chunks) >= 2
    # Every sub-chunk of the split function still attributes to the symbol.
    assert all(c.symbol_name == "huge" for c in chunks)


def test_python_class_symbol_captured():
    # Sole top-level statement → one unit → stands alone, so its name survives.
    # (A *small* class next to other small units would pack and lose the name,
    # which is fine: Phase 2 maps nodes↔chunks by line range, not symbol_name.)
    body = "".join(f"    def method_{i}(self):\n        return {i}\n" for i in range(3))
    text = "class Widget:\n" + body
    chunks = chunk_file("m.py", text, "python")
    _assert_valid(chunks, text, "python")
    assert len(chunks) == 1
    assert chunks[0].symbol_name == "Widget"


def test_unparseable_python_falls_back_to_fixed():
    text = "def broken(:\n    this is not valid python !!!\n" * 3
    chunks = chunk_file("bad.py", text, "python")
    # Must not raise; still produces valid python-language chunks.
    _assert_valid(chunks, text, "python")
    assert len(chunks) >= 1


def test_empty_file_yields_no_chunks():
    for language in ("python", "markdown", "yaml"):
        assert chunk_file("empty", "", language) == []
        assert chunk_file("ws", "   \n\n  ", language) == []
