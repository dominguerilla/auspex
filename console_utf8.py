"""Force stdout/stderr to UTF-8 so the agent is portable across platforms.

On Windows, stdout defaults to the legacy cp1252 ("charmap") codec. Any agent
that prints a non-cp1252 character (the searcher logs an arrow ``->`` rendered
as U+2192, and LLM-generated reports routinely contain em-dashes, smart quotes,
and arrows) raises ``UnicodeEncodeError`` on write and kills the whole run.

Reconfiguring the streams to UTF-8 at process startup fixes this at the source,
so no ``PYTHONUTF8=1`` env var is needed. Call :func:`configure_utf8_console`
once from each process entry point.
"""

from __future__ import annotations

import sys


def configure_utf8_console() -> None:
    """Reconfigure stdout/stderr to UTF-8 if the streams support it.

    Streams replaced with objects lacking ``reconfigure`` (e.g. some capture
    shims) are skipped silently.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
