"""Single source of truth for the structural contract between LLM prompts
and the Python parsers that read their output.

Each constant pairs a literal/regex used by parsers with a hint string injected
into the corresponding prompt template — change either alone and the desync is
silent (citations report 0, every critique defaults to FAILED, etc.).
"""

import re

CITATION_FORMAT_HINT = "[Source](url)"
CITATION_LINK_RE = re.compile(r"\[Source\]\((https?://[^)\s]+)\)")

CRITIC_PASS = "PASSED"
CRITIC_FAIL = "FAILED"
CRITIC_MISSING_PREFIX = "MISSING:"
