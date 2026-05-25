"""
Streamlit frontend for the research agent — "The Scrying Plate" theme.

Run locally:
    streamlit run streamlit_app.py

Deploy on Hugging Face Spaces:
    1. Create a new Space with SDK = "Streamlit"
    2. Push this repo
    3. In the Space settings, add these secrets:
         LLM_PROVIDER = huggingface
         HF_TOKEN     = <your HF access token>
         HF_MODEL     = meta-llama/Llama-3.1-8B-Instruct   (or any instruct model)

Design notes
------------
The page is rendered as an illuminated manuscript on parchment: deep brown
ink on cream vellum with oxblood accents. The six spirits arrange around a
central sigillum; each speaks in turn, stamping a marginalia entry into the
log. Streamlit's default chrome is hidden; native widgets are restyled by
CSS to fit the page.

This file is one big script — the layout is fully declarative, all state
flows top-to-bottom on every re-run (Streamlit's model).
"""

import os
import re
from datetime import datetime
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from graph.graph_builder import build_graph

load_dotenv()


# ─────────────────────────────────────────────────────────────────────────────
# 1. Page config + custom CSS injection
#
# All visual styling lives in styles.css next to this file. Font <link> tags
# stay inline below (HTML, not CSS). Editing styles.css is a real CSS-file
# experience: editor highlighting, Prettier/stylelint, clean diffs.
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="The Goetic Tribunal",
    page_icon="⊙",
    layout="wide",
    initial_sidebar_state="collapsed",
)


FONT_LINKS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@400;500;600;700&family=EB+Garamond:ital,wght@0,400;0,500;0,600;1,400;1,500&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
"""


@st.cache_data
def _load_css() -> str:
    """Read styles.css from disk and wrap it in a <style> tag for st.markdown.

    Cached so the file is read once per server boot (not on every rerun).
    If you edit styles.css while the dev server is running, hit "Rerun" in
    the Streamlit toolbar or restart `streamlit run` to pick up the change.
    """
    css = (Path(__file__).parent / "styles.css").read_text(encoding="utf-8")
    # The leading "\n\n" + trailing "\n" matter — Streamlit's markdown parser
    # only treats <style>...</style> as a raw-HTML block when the opening tag
    # is on its own line with a blank line above it. Without these newlines
    # the CSS renders as paragraph text on the page.
    return f"\n\n<style>\n{css}\n</style>\n"


st.markdown(FONT_LINKS + _load_css(), unsafe_allow_html=True)


def _html(s: str) -> str:
    """Flatten an HTML block so Streamlit's markdown parser doesn't trip on
    indentation. Markdown treats lines with 4+ leading spaces as code blocks,
    and a blank line inside an HTML block closes it — meaning the next
    indented `<div>` gets rendered as literal code (which is what caused the
    hero blurb to appear inside a black ``` box). This helper strips leading
    whitespace from every line and removes blanks, which is safe because we
    only emit HTML here (no <pre>/whitespace-sensitive content)."""
    return "\n".join(ln.lstrip() for ln in s.splitlines() if ln.strip())


# ─────────────────────────────────────────────────────────────────────────────
# 2. Spirit metadata + sigil SVGs
# ─────────────────────────────────────────────────────────────────────────────

SPIRITS = [
    {"node": "orchestrator", "key": "magister",  "name": "The Magister",  "verb": "opens the Circle"},
    {"node": "searcher",     "key": "familiar",  "name": "The Familiar",  "verb": "ranges abroad"},
    {"node": "reader",       "key": "scribe",    "name": "The Scribe",    "verb": "inscribes the findings"},
    {"node": "critic",       "key": "censor",    "name": "The Censor",    "verb": "challenges the evidence"},
    {"node": "refiner",      "key": "rectifier", "name": "The Rectifier", "verb": "amends the working"},
    {"node": "writer",       "key": "logos",     "name": "The Logos",     "verb": "speaks the Word"},
]
NODE_TO_IDX = {s["node"]: i for i, s in enumerate(SPIRITS)}
ROMAN = ["I", "II", "III", "IV", "V", "VI"]


# Each sigil is a self-contained SVG. Originals — geometric figures rooted in
# a planetary/alchemical vocabulary but not reproductions of any historical
# sigil. All share viewBox 0 0 64 64, currentColor stroke, 1.6 stroke-width.
def _sigil(key: str, size: int = 56) -> str:
    inner = {
        "magister": """
            <circle cx="32" cy="32" r="26"/>
            <circle cx="32" cy="32" r="18"/>
            <path d="M32 6 L32 58 M6 32 L58 32"/>
            <circle cx="32" cy="32" r="3" fill="currentColor" stroke="none"/>
        """,
        "familiar": """
            <circle cx="32" cy="32" r="26"/>
            <path d="M32 32 L32 8 M32 32 L52.78 44 M32 32 L11.22 44"/>
            <circle cx="32" cy="8" r="2.5" fill="currentColor" stroke="none"/>
            <circle cx="52.78" cy="44" r="2.5" fill="currentColor" stroke="none"/>
            <circle cx="11.22" cy="44" r="2.5" fill="currentColor" stroke="none"/>
            <circle cx="32" cy="32" r="4"/>
        """,
        "scribe": """
            <circle cx="32" cy="32" r="26"/>
            <path d="M18 22 L46 22 M18 30 L46 30 M18 38 L46 38 M18 46 L40 46"/>
            <path d="M44 14 L52 22 L30 44 L22 44 L22 36 Z"/>
        """,
        "censor": """
            <circle cx="32" cy="32" r="26"/>
            <path d="M32 10 L54 48 L10 48 Z"/>
            <path d="M18 36 Q32 24 46 36 Q32 48 18 36 Z"/>
            <circle cx="32" cy="36" r="4"/>
            <circle cx="32" cy="36" r="1.5" fill="currentColor" stroke="none"/>
        """,
        "rectifier": """
            <circle cx="32" cy="32" r="26"/>
            <path d="M12 12 L52 52 M52 12 L12 52"/>
            <circle cx="32" cy="32" r="8"/>
            <path d="M32 24 L32 40 M24 32 L40 32"/>
        """,
        "logos": """
            <circle cx="32" cy="32" r="26"/>
            <path d="M14 32 L50 32"/>
            <path d="M20 22 Q32 14 44 22"/>
            <path d="M18 16 Q32 4 46 16"/>
            <path d="M22 42 L42 42 M24 48 L40 48 M27 54 L37 54"/>
        """,
    }[key]
    return (
        f'<svg viewBox="0 0 64 64" width="{size}" height="{size}" '
        f'style="display:inline-block">'
        f'<g fill="none" stroke="currentColor" stroke-width="1.6" '
        f'stroke-linecap="round" stroke-linejoin="round">{inner}</g></svg>'
    )


def render_circle(active_idx: int | None, completed: set[int], size: int = 480) -> str:
    """The central Sigillum Tribunalis. SVG with the 6 spirits arranged
    hexagonally; active glows oxblood with a slow-rotating dashed ring,
    completed are inked, pending are faded.
    """
    import math
    cx, cy, R, inner = 200, 200, 150, 92
    positions = []
    for i in range(6):
        a = -math.pi / 2 + (i * math.pi * 2) / 6
        positions.append((cx + R * math.cos(a), cy + R * math.sin(a)))

    parts = [
        f'<svg viewBox="0 0 400 400" width="{size}" height="{size}" '
        f'style="display:block;color:var(--ink)">',
        '<defs><radialGradient id="cos-glow" cx="50%" cy="50%" r="50%">'
        '<stop offset="0%" stop-color="var(--accent)" stop-opacity="0.45"/>'
        '<stop offset="60%" stop-color="var(--accent)" stop-opacity="0.08"/>'
        '<stop offset="100%" stop-color="var(--accent)" stop-opacity="0"/>'
        '</radialGradient></defs>',
    ]

    # active halo
    if active_idx is not None and 0 <= active_idx < 6:
        ax, ay = positions[active_idx]
        parts.append(f'<circle cx="{ax}" cy="{ay}" r="46" fill="url(#cos-glow)"/>')

    # rings
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="{R}" fill="none" stroke="currentColor" stroke-width="1.4" opacity="0.55"/>')
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="{R-14}" fill="none" stroke="currentColor" stroke-width="1" opacity="0.3" stroke-dasharray="2 4"/>')
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="{inner}" fill="none" stroke="currentColor" stroke-width="1.4" opacity="0.45"/>')
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="{inner-10}" fill="none" stroke="currentColor" stroke-width="1" opacity="0.25"/>')

    # hexagram
    def _poly(indices):
        pts = " ".join(f"{positions[i][0]:.2f},{positions[i][1]:.2f}" for i in indices)
        return f'<polygon points="{pts}" fill="none" stroke="currentColor" stroke-width="1.4" opacity="0.25"/>'
    parts.append(_poly([0, 2, 4]))
    parts.append(_poly([1, 3, 5]))

    # tick marks
    for i in range(60):
        a = (i * math.pi * 2) / 60
        r1 = R + 4
        r2 = R + (10 if i % 5 == 0 else 6)
        x1, y1 = cx + r1 * math.cos(a), cy + r1 * math.sin(a)
        x2, y2 = cx + r2 * math.cos(a), cy + r2 * math.sin(a)
        op = 0.55 if i % 5 == 0 else 0.25
        parts.append(f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" stroke="currentColor" stroke-width="0.8" opacity="{op}"/>')

    # center glyph
    parts.append(f'<g opacity="0.4"><circle cx="{cx}" cy="{cy}" r="14" fill="none" stroke="currentColor" stroke-width="1.2"/>'
                 f'<circle cx="{cx}" cy="{cy}" r="3" fill="currentColor"/>'
                 f'<line x1="{cx-22}" y1="{cy}" x2="{cx+22}" y2="{cy}" stroke="currentColor" stroke-width="1"/>'
                 f'<line x1="{cx}" y1="{cy-22}" x2="{cx}" y2="{cy+22}" stroke="currentColor" stroke-width="1"/></g>')

    # spirits
    for i, (x, y) in enumerate(positions):
        is_active = i == active_idx
        is_done = i in completed
        is_pending = not is_active and not is_done
        color = "var(--accent)" if is_active else "var(--ink)" if is_done else "var(--ink-fade)"
        station_r = 32 if is_active else 28
        opacity = 0.6 if is_pending else 1
        parts.append(f'<g transform="translate({x:.2f} {y:.2f})" style="color:{color}">')
        parts.append(f'<circle cx="0" cy="0" r="{station_r}" fill="var(--page)" stroke="currentColor" '
                     f'stroke-width="{1.6 if is_active else 1}" opacity="{opacity}"/>')
        if is_active:
            parts.append(f'<circle cx="0" cy="0" r="{station_r+6}" fill="none" stroke="currentColor" '
                         f'stroke-width="0.8" stroke-dasharray="3 3" opacity="0.6">'
                         f'<animateTransform attributeName="transform" type="rotate" '
                         f'from="0" to="360" dur="12s" repeatCount="indefinite"/></circle>')
        # sigil — translate so 64x64 viewBox renders centered
        parts.append(f'<g transform="translate(-22 -22)" style="opacity:{opacity}">')
        # inline sigil paths (size 44 inside its own 64 box; we shift then scale)
        sigil_inner = _sigil(SPIRITS[i]["key"], 44)
        # Strip outer <svg> wrapper and embed group at correct scale
        m = re.search(r'<g[^>]*>(.*)</g>', sigil_inner, re.S)
        if m:
            parts.append(f'<g transform="scale({44/64:.4f})" fill="none" stroke="currentColor" '
                         f'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
                         f'{m.group(1)}</g>')
        parts.append('</g>')
        # numeral
        parts.append(f'<text x="0" y="{station_r+16}" text-anchor="middle" '
                     f'font-family="Cinzel, serif" font-size="10" fill="currentColor" '
                     f'opacity="0.7" letter-spacing="2">{ROMAN[i]}</text>')
        parts.append('</g>')

    parts.append('</svg>')
    return "".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# 3. HTML renderers for each region
# ─────────────────────────────────────────────────────────────────────────────

def render_topstrip(status: str = "sealed", elapsed: str | None = None, model: str = "") -> str:
    """status ∈ {"sealed", "working", "closed"}"""
    if status == "working":
        right_state = f'<span class="gt-status-on">●</span><span>&nbsp; Circle Open · Working · {elapsed or "00:00"}</span>'
    elif status == "closed":
        right_state = f'<span class="gt-status-done">✓</span><span>&nbsp; Circle Closed · Testimony Inscribed · {elapsed or ""}</span>'
    else:
        right_state = '<span class="gt-status-off">○</span><span>&nbsp; Circle Sealed · Awaiting</span>'

    return _html(f"""
    <div class="gt-topstrip">
        <div><a href="https://github.com/dominguerilla/research-agent" target="_blank">↳ Source · github</a></div>
        <div style="display:flex;align-items:center;gap:12px">{right_state}</div>
        <div style="text-align:right">{model}</div>
    </div>
    """)


def render_hero(blurb: bool = True) -> str:
    extra = (
        '<div class="gt-hero-blurb">A LangGraph pipeline staged as a ceremonial working — '
        'Magister, Familiar, Scribe, Censor, Rectifier, Logos — that turns a '
        'question into a cited markdown report.</div>'
    ) if blurb else ""
    return _html(f"""
    <div class="gt-hero">
        <div class="gt-hero-ornament">· ⊙ ·</div>
        <h1>The Goetic Tribunal</h1>
        <div class="gt-hero-sub">A bounded research working — six spirits, one report.</div>
        {extra}
    </div>
    """)


def render_epigraph(question: str, iter_of: tuple[int, int] | None = None) -> str:
    q = (question or "").strip()
    if not q:
        return ""
    first = q[0].upper()
    rest = q[1:]
    meta = ""
    if iter_of:
        meta = f' · Iteration {ROMAN[iter_of[0]-1]} of {ROMAN[iter_of[1]-1]}'
    stamp = datetime.now().strftime("%H·%M·%S UTC")
    return _html(f"""
    <div class="gt-epigraph">
        <div class="gt-dropcap">{first}</div>
        <div>
            <div class="gt-question-text">{rest}</div>
            <div class="gt-question-meta">Posed · {stamp} · §0001{meta}</div>
        </div>
    </div>
    """)


def render_circle_section(active_idx: int | None, completed: set[int]) -> str:
    """Circle plus the left/right roster columns."""
    def roster_item(i: int) -> str:
        s = SPIRITS[i]
        label = f'⊙ {ROMAN[i]} · {s["name"].replace("The ", "").upper()}'
        if i == active_idx:
            return f'<span class="gt-active">{label} · speaking</span>'
        if i in completed:
            return f'<span class="gt-done">{label} · sealed</span>'
        return f'{label} · awaiting'

    left = "<br>".join(roster_item(i) for i in (0, 1, 2))
    right = "<br>".join(roster_item(i) for i in (3, 4, 5))

    return _html(f"""
    <div class="gt-circle-section">
        <div class="gt-circle-side left">{left}</div>
        <div class="gt-circle-svg">{render_circle(active_idx, completed)}</div>
        <div class="gt-circle-side">{right}</div>
    </div>
    """)


def render_entry(
    idx: int,
    state: str,             # "active" | "done" | "pending"
    body_html: str,
    gloss_html: str = "",
    footnotes_html: str = "",
) -> str:
    s = SPIRITS[idx]
    badge = ""
    if state == "active":
        badge = '<span class="gt-badge gt-badge-active">SPEAKING</span>'
    elif state == "done":
        badge = '<span class="gt-badge gt-badge-sealed">· SEALED</span>'

    sigil = _sigil(s["key"], 56)
    sigil_sm = _sigil(s["key"], 24)
    fn = f'<div class="gt-entry-footnotes">{footnotes_html}</div>' if footnotes_html else ""

    # Phone-only: tucked behind a <details> in place of the right gloss column.
    # CSS (styles.css @media block) hides this on desktop and shows it under
    # the body on narrow viewports. Skip for pending entries (nothing to show).
    trace = ""
    if gloss_html and state != "pending":
        trace = (
            f'<details class="gt-entry-trace">'
            f'<summary>trace</summary>'
            f'<div>{gloss_html}</div>'
            f'</details>'
        )

    return _html(f"""
    <div class="gt-entry {state}">
        <div class="gt-entry-sigil">
            {sigil}
            <div class="gt-entry-numeral">{ROMAN[idx]}</div>
        </div>
        <div>
            <div class="gt-entry-name">
                <span class="gt-entry-sigil-inline">{sigil_sm}<span class="gt-entry-numeral">{ROMAN[idx]}</span></span>
                <span>{s["name"]}</span> {badge}
            </div>
            <div class="gt-entry-verb">{s["verb"]}</div>
            <div class="gt-entry-body">{body_html}</div>
            {fn}
            {trace}
        </div>
        <div class="gt-entry-gloss">{gloss_html}</div>
    </div>
    """)


def render_log_title(active_idx: int | None, total_done: int) -> str:
    progress = f"{ROMAN[min(active_idx, 5)] if active_idx is not None else ROMAN[total_done-1] if total_done else 'I'} / VI · {'IN MOTION' if active_idx is not None else 'SEALED'}"
    return _html(f"""
    <div class="gt-log-title">
        <h2>The Working</h2>
        <div class="gt-log-progress">{progress}</div>
    </div>
    """)


def render_caveat() -> str:
    return _html("""
    <div class="gt-caveat">
        Spirits are bound to the Circle, not to truth. The Logos may speak
        inventions; cited URLs may not exist. Verify every source before this
        testimony enters the world.
    </div>
    """)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Stage describers — turn a graph update into entry body + gloss
# ─────────────────────────────────────────────────────────────────────────────

def describe_partial(node_name: str, partial: dict, elapsed: str = "") -> tuple[str, str, str]:
    """Return (body_html, gloss_html, footnotes_html) for a completed stage."""
    if node_name == "orchestrator":
        queries = partial.get("search_queries", []) or []
        body = (f"The frame of the working is set. {len(queries)} search-quer{'y' if len(queries)==1 else 'ies'} "
                f"forged from the question and committed to the Familiar.")
        gloss = f"{elapsed}<br>{len(queries)} queries forged<br>frame set"
        fn = "<br>".join(
            f'<span class="gt-ix">Q.{i+1:02d}</span>{q}'
            for i, q in enumerate(queries[:8])
        ) or ""
        return body, gloss, fn

    if node_name == "searcher":
        sources = partial.get("sources", []) or partial.get("search_results", []) or []
        body = f"The Familiar rides out across the noosphere. {len(sources)} testimon{'y is' if len(sources)==1 else 'ies are'} gathered."
        gloss = f"{elapsed}<br>{len(sources)} sources<br>admitted"
        urls = []
        for s in sources[:6]:
            if isinstance(s, dict):
                urls.append(s.get("url") or s.get("link") or s.get("title", ""))
            else:
                urls.append(str(s))
        fn = "<br>".join(f"↳ {u}" for u in urls if u)
        if len(sources) > 6:
            fn += f'<br><span class="gt-ix">+ {len(sources)-6} further sources</span>'
        return body, gloss, fn

    if node_name == "reader":
        sources = partial.get("sources", []) or []
        body = ("The Scribe reads and inscribes. Cited claims are extracted from each admitted "
                "testimony and woven into a draft.")
        gloss = f"{elapsed}<br>{len(sources)} sources read<br>draft scribed"
        return body, gloss, ""

    if node_name == "critic":
        critique = partial.get("critique") or {}
        if isinstance(critique, dict):
            sufficient = critique.get("sufficient", critique.get("is_sufficient"))
            reason = critique.get("reason", critique.get("notes", ""))
        else:
            sufficient = None
            reason = str(critique)
        verdict = "The testimony is held sufficient." if sufficient else "Weaknesses are found; the working must be amended."
        body = f"The Censor weighs the draft against the question. {verdict}"
        gloss = f"{elapsed}<br>{'sufficient' if sufficient else 'insufficient'}<br>verdict rendered"
        fn = f'<span class="gt-ix">NOTE</span>{reason}' if reason else ""
        return body, gloss, fn

    if node_name == "refiner":
        queries = partial.get("search_queries", []) or []
        body = (f"The Rectifier reforges the inquiry. {len(queries)} amended quer{'y is' if len(queries)==1 else 'ies are'} "
                "issued; the Familiar is sent forth again.")
        gloss = f"{elapsed}<br>{len(queries)} amended<br>loop-back"
        fn = "<br>".join(
            f'<span class="gt-ix">Q.{i+1:02d}</span>{q}'
            for i, q in enumerate(queries[:6])
        )
        return body, gloss, fn

    if node_name == "writer":
        report = partial.get("final_report") or ""
        chars = len(report)
        body = f"The Word is spoken. {chars:,} characters set down; the testimony is sealed."
        gloss = f"{elapsed}<br>{chars:,} chars<br>sealed"
        return body, gloss, ""

    return "Stage completed.", elapsed, ""


# ─────────────────────────────────────────────────────────────────────────────
# 5. Source extraction for the Testimony's right rail
# ─────────────────────────────────────────────────────────────────────────────

def extract_sources(state_sources, final_report: str) -> list[dict]:
    """Best-effort extraction of sources for the two-column scholar layout."""
    out: list[dict] = []
    if state_sources:
        for s in state_sources:
            if isinstance(s, dict):
                out.append({
                    "title": s.get("title") or s.get("name") or "",
                    "url": s.get("url") or s.get("link") or "",
                })
            else:
                out.append({"title": "", "url": str(s)})
    if not out and final_report:
        # Fallback: pull markdown links and bare URLs from the report
        seen = set()
        for m in re.finditer(r'\[([^\]]+)\]\((https?://[^\)\s]+)\)', final_report):
            url = m.group(2)
            if url in seen: continue
            seen.add(url)
            out.append({"title": m.group(1), "url": url})
        for m in re.finditer(r'(?<![\(\[])\b(https?://[^\s\)\]]+)', final_report):
            url = m.group(1).rstrip('.,;:')
            if url in seen: continue
            seen.add(url)
            out.append({"title": "", "url": url})
    return out


def render_sources_rail(sources: list[dict]) -> str:
    if not sources:
        return ""
    items = []
    for i, s in enumerate(sources, 1):
        title = s.get("title", "")
        url = s.get("url", "")
        url_html = (
            f'<a class="gt-source-url" href="{url}" target="_blank">{url}</a>'
            if url and title else ''
        )
        items.append(
            f'<div class="gt-source">'
            f'<span class="gt-source-num">§ {i:02d}</span>'
            f'{title or url}'
            f'{url_html}'
            f'</div>'
        )
    return _html(f"""
    <div class="gt-sources-rail">
        <div class="gt-sources-label">Sources · {len(sources)}</div>
        {''.join(items)}
    </div>
    """)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Graph wiring
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_resource
def get_graph():
    return build_graph()


def run_research(question: str, max_iterations: int):
    graph = get_graph()
    initial_state = {
        "research_question": question,
        "max_iterations": max_iterations,
        "iteration": 0,
        "search_queries": [],
        "search_results": [],
        "sources": [],
        "critique": None,
        "final_report": None,
        "messages": [],
    }
    for update in graph.stream(initial_state, stream_mode="updates"):
        for node_name, partial in update.items():
            yield node_name, partial


# ─────────────────────────────────────────────────────────────────────────────
# 7. Compose the page
# ─────────────────────────────────────────────────────────────────────────────

provider = os.getenv("LLM_PROVIDER", "ollama").lower()
if provider == "huggingface":
    model = os.getenv("HF_MODEL", "meta-llama/Llama-3.1-8B-Instruct")
else:
    model = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
model_label = f"{provider} / {model}"

# Session state: hold the question/iterations between reruns so the form
# survives the button click without flicker.
st.session_state.setdefault("question", "")
st.session_state.setdefault("max_iterations", 2)
st.session_state.setdefault("submitted", False)
st.session_state.setdefault("final_report", None)
st.session_state.setdefault("final_sources", [])
st.session_state.setdefault("elapsed", "")


# === Render top strip + hero (always shown) ==================================
running_now = st.session_state.submitted and st.session_state.final_report is None
finished = st.session_state.submitted and st.session_state.final_report is not None
status = "working" if running_now else "closed" if finished else "sealed"

st.markdown(render_topstrip(status, st.session_state.elapsed, model_label), unsafe_allow_html=True)
st.markdown(render_hero(blurb=not st.session_state.submitted), unsafe_allow_html=True)


# === IDLE: render the invocation form ========================================
if not st.session_state.submitted:
    # All-dormant circle
    st.markdown(render_circle_section(active_idx=None, completed=set()), unsafe_allow_html=True)
    st.markdown('<div class="gt-circle-caption">The Circle Awaits</div>', unsafe_allow_html=True)

    st.markdown('<div class="gt-form-wrap">', unsafe_allow_html=True)

    max_iterations = st.slider(
        "Maximum challenges from the Censor",
        min_value=1,
        max_value=5,
        value=st.session_state.max_iterations,
        help="How many times the Censor may reject the testimony and send the Familiar back for more sources.",
        key="max_iter_widget",
    )
    st.session_state.max_iterations = max_iterations

    st.markdown(
        '<div class="gt-pose-label"><span class="gt-mark">⊙</span>Pose your question to the Tribunal</div>',
        unsafe_allow_html=True,
    )
    question = st.text_area(
        "Question",  # hidden via CSS
        value=st.session_state.question,
        placeholder="e.g. What are the tradeoffs of Rust vs Go for backend services?",
        height=140,
        key="question_widget",
        label_visibility="collapsed",
    )

    st.markdown(
        '<div class="gt-submit-hint">↳ The working will take 30—90 seconds. Verify every cited source.</div>',
        unsafe_allow_html=True,
    )

    if st.button("Open the Circle  ⊙", type="primary", disabled=not question.strip()):
        st.session_state.question = question.strip()
        st.session_state.submitted = True
        st.session_state.final_report = None
        st.session_state.final_sources = []
        st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)
    st.markdown(render_caveat(), unsafe_allow_html=True)
    st.stop()


# === RUNNING: stream the working =============================================
question_text = st.session_state.question

st.markdown(
    render_epigraph(question_text, iter_of=(1, st.session_state.max_iterations)),
    unsafe_allow_html=True,
)

# Placeholders for the live circle + log. We rebuild both on every yield.
circle_slot = st.empty()
log_slot = st.empty()

# Initial dormant render
circle_slot.markdown(render_circle_section(active_idx=None, completed=set()), unsafe_allow_html=True)

# Streaming loop — only runs the first time we land in this branch with no
# final_report. Once finished, we cache the report in session_state and the
# next rerun skips to the complete branch.
if running_now:
    started = datetime.now()
    spirit_log: list[tuple[int, str, str, str]] = []   # (idx, body, gloss, footnotes)
    completed_set: set[int] = set()
    final_report: str | None = None
    final_state_sources = []

    try:
        for node_name, partial in run_research(question_text, st.session_state.max_iterations):
            idx = NODE_TO_IDX.get(node_name)
            if idx is None:
                continue

            elapsed_s = (datetime.now() - started).total_seconds()
            elapsed_str = f"{int(elapsed_s // 60):02d}:{elapsed_s % 60:05.2f}"

            body, gloss, fn = describe_partial(node_name, partial, elapsed_str)

            # The just-yielded spirit is the most-recently-completed one.
            spirit_log.append((idx, body, gloss, fn))
            completed_set.add(idx)

            # Capture sources/report for the final state.
            if partial.get("sources"):
                final_state_sources = partial["sources"]
            if node_name == "writer" and partial.get("final_report"):
                final_report = partial["final_report"]

            # Re-render circle: active = just-completed (so the user sees
            # which spirit's voice they're reading); ring keeps rotating.
            circle_slot.markdown(
                render_circle_section(active_idx=idx, completed=completed_set - {idx}),
                unsafe_allow_html=True,
            )

            # Rebuild log with all entries seen so far. The most recent one
            # gets "active" styling so its block stands out while streaming;
            # earlier ones are "done".
            entries_html = [render_log_title(active_idx=idx, total_done=len(spirit_log))]
            for n, (i, b, g, f) in enumerate(spirit_log):
                state = "active" if n == len(spirit_log) - 1 and final_report is None else "done"
                entries_html.append(render_entry(i, state, b, g, f))
            # Pending placeholders for unseen spirits — show the full set.
            unseen = [i for i in range(6) if i not in completed_set]
            for i in unseen:
                entries_html.append(render_entry(
                    i, "pending",
                    "<span style='font-style:italic'>Awaits its turn.</span>",
                    "— — —",
                    "",
                ))
            log_slot.markdown(
                f'<div class="gt-log-wrap">{"".join(entries_html)}</div>',
                unsafe_allow_html=True,
            )

        # ── Working complete ──
        total = (datetime.now() - started).total_seconds()
        st.session_state.elapsed = f"{int(total // 60):02d}:{total % 60:05.2f}"
        st.session_state.final_report = final_report or "_The Circle closed, but the Logos was silent._"
        st.session_state.final_sources = extract_sources(final_state_sources, final_report or "")
        st.rerun()

    except Exception as e:
        st.markdown(
            _html(f"""
            <div class="gt-error">
                <div class="gt-error-tag">⚠ The Working Was Broken</div>
                <div class="gt-error-body">{str(e)}</div>
            </div>
            """),
            unsafe_allow_html=True,
        )
        if st.button("Seal the Circle"):
            st.session_state.submitted = False
            st.session_state.final_report = None
            st.rerun()
        st.markdown(render_caveat(), unsafe_allow_html=True)
        st.stop()


# === COMPLETE: render the Testimony ==========================================
if finished:
    # Render the closed circle + all-sealed log first
    circle_slot.markdown(
        render_circle_section(active_idx=None, completed={0,1,2,3,4,5}),
        unsafe_allow_html=True,
    )

    # Two-column Testimony
    sources = st.session_state.final_sources or []
    report_md = st.session_state.final_report or ""

    # Convert markdown -> HTML via Streamlit's markdown — but we need it inside
    # our two-column grid. Use a small trick: emit the grid + a placeholder div
    # for the body, then immediately render st.markdown() inside a column.
    st.markdown('<div class="gt-testimony-wrap">', unsafe_allow_html=True)
    st.markdown(
        _html("""
        <div class="gt-testimony-title">
            <h2>Testimony</h2>
            <div class="gt-log-progress">Sealed · {}</div>
        </div>
        """).format(st.session_state.elapsed),
        unsafe_allow_html=True,
    )

    col_body, col_sources = st.columns([3, 1], gap="large")
    with col_body:
        st.markdown(
            f'<div class="gt-testimony-body">\n\n{report_md}\n\n</div>',
            unsafe_allow_html=True,
        )
    with col_sources:
        st.markdown(render_sources_rail(sources), unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

    # Download + reset row
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = re.sub(r'[^a-z0-9]+', '_', question_text[:40].lower()).strip('_')
    col_dl, col_again = st.columns([1, 1])
    with col_dl:
        st.download_button(
            "Take the testimony (.md)",
            data=report_md,
            file_name=f"{timestamp}_{slug or 'testimony'}.md",
            mime="text/markdown",
        )
    with col_again:
        if st.button("Seal the Circle · Begin Anew"):
            st.session_state.submitted = False
            st.session_state.question = ""
            st.session_state.final_report = None
            st.session_state.final_sources = []
            st.session_state.elapsed = ""
            st.rerun()

st.markdown(render_caveat(), unsafe_allow_html=True)
