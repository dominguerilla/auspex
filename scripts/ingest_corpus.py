"""Ingest the Auspex repo into the pgvector corpus store (RAG Phase 1, §1.1).

Idempotent: safe to re-run. Chunks are keyed on a content hash and inserted
with ``ON CONFLICT DO NOTHING``, so re-running with an unchanged corpus is a
no-op and re-running after edits inserts only the new/changed chunks.

The corpus is read *at a pinned commit SHA* via ``git`` (not the working tree),
so the corpus is frozen for the duration of both phases regardless of local
edits. The SHA is recorded on every row (``commit_sha``).

Pipeline:
    1. Enumerate tracked files at the pinned SHA (``git ls-tree``), apply
       include/exclude rules.
    2. Chunk each file, language-aware:
         - markdown/docs  → split on headings, fixed-size fallback
         - python         → split on top-level def/class (ast), fixed fallback
         - everything else→ fixed-size chunks
    3. Embed each chunk with the frozen model (llm/embeddings.py).
    4. Upsert into ``corpus_chunks``.

Usage (run from repo root)::

    # Validate chunking only — no Ollama, no Postgres needed (works on Windows):
    python -m scripts.ingest_corpus --dry-run

    # Full ingest (needs Ollama with nomic-embed-text pulled + Postgres/pgvector).
    # Note: per CLAUDE.md, psycopg can't connect in-process on native Windows —
    # run the non-dry path under WSL2/Linux or CI.
    export DATABASE_URL=postgresql://auspex:auspex@localhost:5432/auspex
    python -m scripts.ingest_corpus
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import os
import subprocess
import sys
from dataclasses import dataclass

# --- Chunk sizing --------------------------------------------------------
# The plan targets ~500-800 tokens/chunk with ~10-15% overlap on fixed paths.
# We approximate tokens as chars/4 (good enough for sizing; no tokenizer dep).
_CHARS_PER_TOKEN = 4
_TARGET_TOKENS = 650
_TARGET_CHARS = _TARGET_TOKENS * _CHARS_PER_TOKEN         # ~2600
_MAX_CHARS = 800 * _CHARS_PER_TOKEN                       # ~3200, the split ceiling
_OVERLAP_CHARS = int(_TARGET_CHARS * 0.12)               # ~12% overlap

# --- Include / exclude ---------------------------------------------------
# extension -> language label stored on the chunk
_EXT_LANGUAGE = {
    ".py": "python",
    ".md": "markdown",
    ".tf": "terraform",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".ts": "typescript",
    ".tsx": "typescript",
}
_EXCLUDE_NAMES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock"}
_EXCLUDE_SUFFIXES = (".min.js", ".min.css", ".map")
_EXCLUDE_DIR_PARTS = ("/dist/", "/build/", "/node_modules/", "/.venv/")

_DEFAULT_DATABASE_URL = "postgresql://auspex:auspex@localhost:5432/auspex"


@dataclass
class Chunk:
    """One unit of corpus text with provenance, pre-embedding."""

    file_path: str
    chunk_index: int
    start_line: int
    end_line: int
    content: str
    language: str
    symbol_name: str | None

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Git: read the corpus at a frozen commit
# ---------------------------------------------------------------------------

def _git(*args: str) -> str:
    """Run a git command from the repo root and return stdout (text)."""
    result = subprocess.run(
        ["git", *args],
        cwd=_repo_root(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return result.stdout


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resolve_commit(commit: str) -> str:
    """Expand a ref (e.g. 'HEAD', 'develop') to a full SHA."""
    return _git("rev-parse", commit).strip()


def _list_files(commit: str) -> list[str]:
    """Tracked file paths at ``commit`` that pass the include/exclude rules."""
    raw = _git("ls-tree", "-r", "--name-only", commit)
    paths = [p for p in raw.splitlines() if p.strip()]
    return [p for p in paths if _included(p)]


def _read_file(commit: str, path: str) -> str | None:
    """Text of ``path`` at ``commit``; None if it isn't valid UTF-8 (binary)."""
    result = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=_repo_root(),
        capture_output=True,
        check=True,
    )
    try:
        return result.stdout.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _included(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    posix = "/" + path
    if name in _EXCLUDE_NAMES:
        return False
    if path.endswith(_EXCLUDE_SUFFIXES):
        return False
    if any(part in posix for part in _EXCLUDE_DIR_PARTS):
        return False
    return _language_for(path) is not None


def _language_for(path: str) -> str | None:
    name = path.rsplit("/", 1)[-1]
    if name.startswith("Dockerfile"):
        return "dockerfile"
    _, dot, ext = name.rpartition(".")
    if dot:
        return _EXT_LANGUAGE.get("." + ext.lower())
    return None


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

# A "unit" is a semantic region of a file, as absolute character offsets into
# the file text, plus an optional symbol name: (start_char, end_char, symbol).
# Language chunkers produce an ordered list of units; the packer turns units
# into target-sized chunks. Breaking always happens *at* unit boundaries.
Unit = tuple[int, int, "str | None"]


def _line_at(text: str, offset: int) -> int:
    """1-based line number of a character offset."""
    return text.count("\n", 0, offset) + 1


def _line_offsets(lines: list[str]) -> list[int]:
    """Char offset at the start of each line (index i = start of line i+1)."""
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    return offsets


def _is_heading(line: str) -> bool:
    """True for an ATX markdown heading: 1-6 '#' then a space (e.g. '## Foo')."""
    stripped = line.lstrip()
    hashes = len(stripped) - len(stripped.lstrip("#"))
    return 1 <= hashes <= 6 and stripped[hashes:hashes + 1] == " "


def _make_chunk(
    full: str, file_path: str, language: str,
    start: int, end: int, symbol_name: str | None,
) -> Chunk:
    """Build one Chunk from an absolute char range of the file text."""
    return Chunk(
        file_path=file_path,
        chunk_index=0,  # renumbered per file in chunk_file()
        start_line=_line_at(full, start),
        end_line=_line_at(full, max(start, end - 1)),
        content=full[start:end],
        language=language,
        symbol_name=symbol_name,
    )


def _fixed_split(
    full: str, file_path: str, language: str,
    start: int, end: int, symbol_name: str | None,
) -> list[Chunk]:
    """Split one oversized char range into overlapping fixed-size chunks."""
    chunks: list[Chunk] = []
    pos = start
    while pos < end:
        stop = min(pos + _MAX_CHARS, end)
        if full[pos:stop].strip():
            chunks.append(_make_chunk(full, file_path, language, pos, stop, symbol_name))
        if stop == end:
            break
        pos = stop - _OVERLAP_CHARS  # step back for overlap
    return chunks


def _pack_units(full: str, file_path: str, language: str, units: list[Unit]) -> list[Chunk]:
    """Greedily pack units into ~target-sized chunks, breaking at unit edges.

    A unit larger than the ceiling is fixed-split on its own. Otherwise units
    accumulate until adding the next one would exceed the target size. A chunk
    keeps its symbol name only when it is exactly one symbol; packed chunks that
    span multiple units carry symbol_name=None (their line range still locates
    them, which is what Phase 2's node↔chunk mapping uses).
    """
    chunks: list[Chunk] = []
    g_start: int | None = None
    g_end = 0
    g_units = 0
    g_symbol: str | None = None

    def flush() -> None:
        nonlocal g_start, g_end, g_units, g_symbol
        if g_start is not None and full[g_start:g_end].strip():
            symbol = g_symbol if g_units == 1 else None
            chunks.append(_make_chunk(full, file_path, language, g_start, g_end, symbol))
        g_start, g_end, g_units, g_symbol = None, 0, 0, None

    for start, end, symbol in units:
        if not full[start:end].strip():
            continue
        if end - start > _MAX_CHARS:
            flush()
            chunks.extend(_fixed_split(full, file_path, language, start, end, symbol))
            continue
        if g_start is not None and end - g_start > _TARGET_CHARS:
            flush()
        if g_start is None:
            g_start = start
        g_end, g_symbol = end, symbol
        g_units += 1
    flush()
    return chunks


def _markdown_units(text: str) -> list[Unit]:
    """Section boundaries at ATX headings; each section is one unit."""
    lines = text.splitlines(keepends=True)
    boundaries = [0]
    offset = 0
    for i, line in enumerate(lines):
        if i > 0 and _is_heading(line):
            boundaries.append(offset)
        offset += len(line)
    boundaries.append(len(text))
    return [(s, e, None) for s, e in zip(boundaries, boundaries[1:]) if e > s]


def _python_units(text: str) -> list[Unit] | None:
    """One unit per top-level statement; def/class units carry the symbol name.

    Returns None if the file doesn't parse (caller falls back to fixed chunks).
    Leading non-statement text (e.g. a license comment before any code) is not
    an ast node and is folded into the first unit's range.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    if not tree.body:
        return None

    lines = text.splitlines(keepends=True)
    starts = _line_offsets(lines)
    symbol_types = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

    units: list[Unit] = []
    prev_end = 0  # char offset; absorbs gaps/comments into the following unit
    for node in tree.body:
        end_line = getattr(node, "end_lineno", node.lineno)
        end = starts[end_line]
        name = node.name if isinstance(node, symbol_types) else None
        units.append((prev_end, end, name))
        prev_end = end
    if prev_end < len(text):  # trailing text after the last statement
        units.append((prev_end, len(text), None))
    return units


def chunk_file(path: str, text: str, language: str) -> list[Chunk]:
    """Chunk a single file with the language-appropriate unit strategy."""
    if language == "markdown":
        units = _markdown_units(text)
    elif language == "python":
        units = _python_units(text)
        if units is None:  # unparseable — treat whole file as one unit
            units = [(0, len(text), None)]
    else:
        units = [(0, len(text), None)]

    chunks = _pack_units(text, path, language, units)
    for i, chunk in enumerate(chunks):  # renumber per file
        chunk.chunk_index = i
    return chunks


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _format_vector(vec: list[float]) -> str:
    """pgvector text literal, e.g. '[0.1,0.2,...]', for a ``%s::vector`` bind."""
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


def _insert_chunks(conn, corpus_name: str, commit_sha: str, rows: list[tuple[Chunk, list[float]]]) -> int:
    """Insert (chunk, embedding) rows, skipping content-hash duplicates.

    Returns the number of rows actually inserted (dupes are skipped silently).
    """
    inserted = 0
    with conn.cursor() as cur:
        for chunk, embedding in rows:
            cur.execute(
                """
                INSERT INTO corpus_chunks
                    (corpus_name, commit_sha, file_path, chunk_index,
                     start_line, end_line, content, content_hash,
                     language, symbol_name, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
                ON CONFLICT (corpus_name, content_hash) DO NOTHING
                """,
                (
                    corpus_name, commit_sha, chunk.file_path, chunk.chunk_index,
                    chunk.start_line, chunk.end_line, chunk.content,
                    chunk.content_hash, chunk.language, chunk.symbol_name,
                    _format_vector(embedding),
                ),
            )
            inserted += cur.rowcount
    conn.commit()
    return inserted


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def gather_chunks(commit_sha: str) -> list[Chunk]:
    """Read + chunk every included file at ``commit_sha``."""
    all_chunks: list[Chunk] = []
    for path in _list_files(commit_sha):
        language = _language_for(path)
        text = _read_file(commit_sha, path)
        if text is None:  # binary / undecodable
            continue
        all_chunks.extend(chunk_file(path, text, language))
    return all_chunks


def _print_summary(chunks: list[Chunk], commit_sha: str) -> None:
    from collections import Counter

    by_lang = Counter(c.language for c in chunks)
    files = sorted({c.file_path for c in chunks})
    print(f"commit         : {commit_sha}")
    print(f"files          : {len(files)}")
    print(f"chunks         : {len(chunks)}")
    for lang, count in sorted(by_lang.items(), key=lambda kv: -kv[1]):
        print(f"  {lang:<12}: {count}")
    if not (100 <= len(chunks) <= 300):
        print(
            f"\n[warn] {len(chunks)} chunks is outside the expected 100-300 band "
            "(plan §1.1). Revisit include rules or chunk sizing before ingesting."
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", default="HEAD", help="ref/SHA to freeze (default: HEAD)")
    parser.add_argument("--corpus-name", default="auspex-develop")
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL", _DEFAULT_DATABASE_URL),
        help="Postgres URL (default: $DATABASE_URL or local docker-compose)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Chunk and report counts only — no embedding, no DB. Works without "
        "Ollama or Postgres (use this to validate chunking on Windows).",
    )
    args = parser.parse_args(argv)

    commit_sha = _resolve_commit(args.commit)
    print(f"[ingest] freezing corpus at {commit_sha}")
    chunks = gather_chunks(commit_sha)
    _print_summary(chunks, commit_sha)

    if args.dry_run:
        print("\n[dry-run] no embeddings computed, nothing written.")
        return 0

    from llm.embeddings import EMBEDDING_DIM, describe_embedder, get_embedder

    print(f"[ingest] embedding {len(chunks)} chunks with {describe_embedder()}")
    embedder = get_embedder()
    vectors = embedder.embed_documents([c.content for c in chunks])
    if vectors and len(vectors[0]) != EMBEDDING_DIM:
        raise SystemExit(
            f"Embedding dim {len(vectors[0])} != expected {EMBEDDING_DIM}. "
            f"Wrong model? corpus_chunks.embedding is vector({EMBEDDING_DIM})."
        )

    import psycopg2

    conn = psycopg2.connect(args.database_url)
    try:
        inserted = _insert_chunks(
            conn, args.corpus_name, commit_sha, list(zip(chunks, vectors))
        )
    finally:
        conn.close()

    skipped = len(chunks) - inserted
    print(f"[ingest] inserted {inserted} new chunks, skipped {skipped} existing "
          f"(corpus_name={args.corpus_name!r})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
