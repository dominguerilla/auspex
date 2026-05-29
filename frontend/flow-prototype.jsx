/* flow-prototype.jsx — The Auspex, single-viewport flow.
 *
 * State machine:
 *   idle → composing → working → complete
 *               ↑__________________|  (reset)
 *
 * Sub-states (not phases — they layer over the active phase):
 *   - inspecting: a sigil detail card is open (during working/complete)
 *   - reading:    the report overlay is open (during complete)
 *
 * The Circle is always mounted; phase-keyed CSS vars scale and fade it.
 */

// Pre-firing flavor text for each spirit's detail card.
// Only `body` is used — footnotes/meta come from live node_complete payloads.
const FLOW_CONTENT = {
  defaultQuestion: "",
  spirits: {
    magister: {
      body:
        "The question is broken into four search-queries. The Magister sets the frame of " +
        "the ritual and binds the Familiar to its path.",
    },
    familiar: {
      body:
        "The Familiar rides out across the noosphere. Testimonies are returned; " +
        "unreachable sources are discarded.",
    },
    scribe: {
      body:
        "The directional attribution of the four archangels appears consolidated in Heinrich " +
        "Cornelius Agrippa's De Occulta Philosophia (Book III, ch. 24, 1531). Earlier, partial " +
        "schemata appear in the Hebrew Sefer Raziel HaMalakh manuscript tradition, though the " +
        "specific Raphael / East pairing is not yet fixed there.",
    },
    censor: {
      body:
        "Citations are challenged. The Magister is consulted; the working is " +
        "rectified and re-submitted to the Censor's judgement.",
    },
    rectifier: {
      body:
        "The Rectifier reweaves the rejected passages, drawing on the Familiar's reserve of " +
        "sources. The amended testimony is returned to the Scribe for a second inscription.",
    },
    logos: {
      body:
        "The Logos speaks the Word. The final testimony is closed, sealed, and committed to the " +
        "scroll. The Circle may now be closed.",
    },
  },
};

/* Sigil station positions, as percent of the circle bounding box.
 * Mirrors CircleOfSpirits' positions: -π/2 + i·(2π/6).
 */
const STATION_POSITIONS = [
  { x: 50,    y: 12.5 },   // I  Magister  (top)
  { x: 82.48, y: 31.25 },  // II Familiar  (upper-right)
  { x: 82.48, y: 68.75 },  // III Scribe   (lower-right)
  { x: 50,    y: 87.5 },   // IV Censor    (bottom)
  { x: 17.52, y: 68.75 },  // V Rectifier (lower-left)
  { x: 17.52, y: 31.25 },  // VI Logos    (upper-left)
];

const ROMAN = ["I", "II", "III", "IV", "V", "VI"];

/* Default node→spirit index mapping, used until GET /config resolves.
 * Values must match SPIRIT_ORDER in sigils.jsx.
 * The live mapping is maintained in nodeToSpiritRef inside FlowPrototype
 * and updated from the config endpoint so backend renames propagate automatically.
 */
const DEFAULT_NODE_ORDER = [
  "orchestrator", "searcher", "reader", "critic", "refiner", "writer",
];

/* If the URL path is /r/{job_id}, return job_id. Otherwise null. */
function jobIdFromPath() {
  const m = window.location.pathname.match(/^\/r\/([a-f0-9]+)$/);
  return m ? m[1] : null;
}

/* Render the body / footnotes / meta for one spirit's detail card.
 *
 * - `idx` is the spirit index (0..5).
 * - `data` is the most recent node_complete payload for this spirit, or null
 *   if the spirit hasn't fired yet. When null, falls back to the fixed-flavor
 *   text in FLOW_CONTENT.spirits so the pre-firing card isn't blank.
 * - `fallback` is FLOW_CONTENT.spirits[key] — used for the pre-firing body.
 */
function renderSpiritCardContent(idx, data, fallback) {
  if (!data) {
    return { body: fallback.body, footnotes: null, meta: [] };
  }
  const elapsed = fmtMs((data.elapsed_s || 0) * 1000);

  switch (idx) {
    case 0: { // Magister — orchestrator
      const queries = data.queries || [];
      return {
        body: `The question is broken into ${queries.length} queries.`,
        footnotes: queries.length
          ? queries.map((q, i) => `Q.${String(i + 1).padStart(2, "0")} — ${q}`).join("\n")
          : null,
        meta: [
          ["queries", String(queries.length)],
          ["elapsed", elapsed],
        ],
      };
    }
    case 1: { // Familiar — searcher
      const urls = data.urls || [];
      const shown = urls.slice(0, 6);
      const extra = urls.length - shown.length;
      const text =
        shown.map((u) => `↳ ${u}`).join("\n") +
        (extra > 0 ? `\n· + ${extra} further sources` : "");
      return {
        body: `The Familiar collected ${data.results_count || 0} testimonies.`,
        footnotes: shown.length ? text : null,
        meta: [
          ["results", String(data.results_count || 0)],
          ["elapsed", elapsed],
        ],
      };
    }
    case 2: { // Scribe — reader
      const sources = data.sources || [];
      const shown = sources.slice(0, 6);
      const extra = sources.length - shown.length;
      const text =
        shown
          .map((s) => `↳ ${s.url}${s.summary_first_line ? "\n  " + s.summary_first_line : ""}`)
          .join("\n") + (extra > 0 ? `\n· + ${extra} more` : "");
      return {
        body: `${data.sources_count || 0} sources were absorbed into the working.`,
        footnotes: shown.length ? text : null,
        meta: [
          ["sources", String(data.sources_count || 0)],
          ["kb", String(data.total_raw_kb || 0)],
          ["elapsed", elapsed],
        ],
      };
    }
    case 3: { // Censor — critic
      const verdict = data.passed ? "PASSED" : "FAILED";
      const missing = data.missing_topics || [];
      const feedback = data.feedback || "";
      const iter = data.iteration || 1;
      const iterRoman = ROMAN[iter - 1] || String(iter);
      const footnotes =
        missing.length || feedback ? (
          <>
            {missing.map((t, i) => (
              <div key={i} style={{ fontWeight: 600 }}>↳ {t}</div>
            ))}
            {feedback && (
              <div style={{ opacity: 0.6, marginTop: "0.5em", whiteSpace: "pre-wrap" }}>
                {feedback}
              </div>
            )}
          </>
        ) : null;
      return {
        body: `The Censor returned ${verdict.toLowerCase()} on iteration ${iterRoman}.`,
        footnotes,
        meta: [
          ["verdict", verdict],
          ["iteration", iterRoman],
          ["gaps", String(missing.length)],
          ["elapsed", elapsed],
        ],
      };
    }
    case 4: { // Rectifier — refiner
      const queries = data.queries || [];
      return {
        body: `The Rectifier reissued ${queries.length} queries to fill the gaps.`,
        footnotes: queries.length ? queries.map((q) => `↳ ${q}`).join("\n") : null,
        meta: [
          ["new queries", String(queries.length)],
          ["elapsed", elapsed],
        ],
      };
    }
    case 5: { // Logos — writer
      const words = data.word_count || 0;
      const cites = data.citation_count || 0;
      return {
        body: `The Word was spoken — ${words.toLocaleString()} words, ${cites} citations.`,
        footnotes: `++TESTIMONIUM++ Sealed at ${elapsed}.`,
        meta: [
          ["words", words.toLocaleString()],
          ["citations", String(cites)],
          ["elapsed", elapsed],
        ],
      };
    }
    default:
      return { body: fallback.body, footnotes: null, meta: [] };
  }
}

const PHASE_DEFAULTS = /*EDITMODE-BEGIN*/{
  "stepDurationMs": 2200,
  "showCircleBehindWelcome": true,
  "centerGlowStyle": "warm"
}/*EDITMODE-END*/;

function useTimer(active) {
  const [ms, setMs] = React.useState(0);
  React.useEffect(() => {
    if (!active) return;
    const start = Date.now() - ms;
    const id = setInterval(() => setMs(Date.now() - start), 80);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);
  return ms;
}

function fmtMs(ms) {
  const s = ms / 1000;
  const mins = Math.floor(s / 60);
  const secs = Math.floor(s % 60);
  const cs = Math.floor((s * 100) % 100);
  return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}.${String(cs).padStart(2, "0")}`;
}

function useCircleSize() {
  const [size, setSize] = React.useState(() => calcSize());
  function calcSize() {
    if (typeof window === "undefined") return 480;
    const w = window.innerWidth;
    const h = window.innerHeight;
    // Leave room for header (~80) and footer (~80) and surrounding text.
    const s = Math.min(w * 0.5, h * 0.62, 560);
    return Math.max(260, Math.round(s));
  }
  React.useEffect(() => {
    const onResize = () => setSize(calcSize());
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  return size;
}

/* ── top status strip ─────────────────────────────────────────────────── */
function TopStrip({ phase, elapsedMs, challenges, config }) {
  let dotClass = "dot-idle";
  let label = "Circle Sealed · Awaiting";
  if (phase === "composing") {
    dotClass = "dot-idle";
    label = "Circle Sealed · Composing";
  } else if (phase === "working") {
    dotClass = "dot-working";
    label = `Circle Open · Working · ${fmtMs(elapsedMs)}`;
  } else if (phase === "complete") {
    dotClass = "dot-done";
    label = `Circle Open · Word Spoken · ${fmtMs(elapsedMs)}`;
  }
  const modelStr = config ? `${config.model} · ${config.provider_label}` : "…";
  const ceilingStr = config ? ROMAN[config.max_iterations_ceiling - 1] : "V";
  return (
    <div className="flow-topstrip">
      <div>↳ Source · github</div>
      <div>
        <span className={dotClass}>{phase === "working" ? "●" : phase === "complete" ? "◉" : "○"}</span>
        <span>{label}</span>
      </div>
      <div>
        {modelStr} &nbsp; · &nbsp; ⊙ {ROMAN[challenges - 1]} of {ceilingStr} challenges
      </div>
    </div>
  );
}

function Footer() {
  return (
    <div className="flow-footer">
      Spirits are bound to the Circle, not to truth. The Logos may speak inventions;
      cited URLs may not exist. Verify every source before this testimony enters the world.
    </div>
  );
}

/* ── welcome phase ────────────────────────────────────────────────────── */
function WelcomePhase({ active, onOpenForm }) {
  return (
    <div className={`flow-phase flow-welcome${active ? " is-active" : ""}`}>
      <div className="flow-welcome-inner">
        <div className="flow-welcome-ornament"> </div>
        <h1 className="flow-welcome-title">The Auspex</h1>
        <div className="flow-welcome-sub">
          Six spirits, one report.
        </div>
        <div className="flow-welcome-hero-blurb">
          A LangGraph agentic ceremony that transforms a question into a cited markdown report.
        </div>
        <button className="flow-welcome-cta" onClick={onOpenForm}>
          Pose the Question &nbsp;⊙
        </button>
      </div>
    </div>
  );
}

/* ── compose form (visible only while phase=composing) ────────────────── */
function ComposeForm({ phase, question, setQuestion, challenges, setChallenges, maxChallenges, onCancel, onSubmit }) {
  const taRef = React.useRef(null);
  React.useEffect(() => {
    if (phase === "composing" && taRef.current) {
      setTimeout(() => taRef.current && taRef.current.focus(), 200);
    }
  }, [phase]);

  const onTrackClick = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const ratio = (e.clientX - rect.left) / rect.width;
    const v = Math.max(1, Math.min(maxChallenges, Math.round(1 + ratio * (maxChallenges - 1))));
    setChallenges(v);
  };

  const fillPct = ((challenges - 1) / (maxChallenges - 1)) * 100;

  return (
    <div className="flow-compose" role="dialog" aria-label="Pose your question">
      <div className="flow-compose-label">
        <span className="mark">⊙</span>
        Pose your question to the Tribunal
      </div>
      <textarea
        ref={taRef}
        className="flow-compose-textarea"
        placeholder="e.g. What are the tradeoffs of Rust vs Go for backend services?"
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        rows={3}
      />
      <div className="flow-compose-row">
        <div className="flow-slider">
          <div className="flow-slider-label">Maximum challenges from the Censor</div>
          <span>I</span>
          <div className="flow-slider-track" onClick={onTrackClick}>
            <div className="flow-slider-fill" style={{ width: `${fillPct}%` }} />
            <div className="flow-slider-knob" style={{ left: `${fillPct}%` }} />
          </div>
          <span>{ROMAN[maxChallenges - 1]}</span>
          <div className="flow-slider-readout">{ROMAN[challenges - 1]}</div>
        </div>
        <div className="flow-compose-actions">
          <button className="flow-compose-cancel" onClick={onCancel}>Cancel</button>
          <button
            className="flow-compose-submit"
            onClick={onSubmit}
            disabled={!question.trim()}
          >
            Open the Circle &nbsp;⊙
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── working phase ────────────────────────────────────────────────────── */
function WorkingPhase({ active, question, progressIdx, completed }) {
  const spirit = SPIRIT_ORDER[progressIdx] || SPIRIT_ORDER[0];
  const spiritName = SIGILS[spirit] ? SIGILS[spirit].name : "";
  return (
    <div className={`flow-phase flow-working${active ? " is-active" : ""}`}>
      <div className="flow-working-inner">
        <div className="flow-working-header">
          <div className="flow-working-prompt-label">The Question Posed</div>
          <div className="flow-working-prompt">
            {question || FLOW_CONTENT.defaultQuestion}
          </div>
        </div>
        <div className="flow-working-circle-slot" />
        <div>
          <div className="flow-working-footer">
            <div className="flow-working-stage-name">
              <span className="roman">Stage {ROMAN[progressIdx] || "I"} of VI</span>
              {spiritName} — {SIGILS[spirit] && SIGILS[spirit].verb}
            </div>
            <div className="flow-working-stagebar">
              {SPIRIT_ORDER.map((_, i) => {
                let cls = "";
                if (completed.includes(i)) cls = "done";
                else if (i === progressIdx) cls = "active";
                return <div key={i} className={cls} />;
              })}
            </div>
            <div className="flow-working-timer">In motion</div>
          </div>
          <div className="flow-working-hint">
            ↳ Tap a sigil on the circle to read its testimony
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── complete phase ───────────────────────────────────────────────────── */
function CompletePhase({ active, onOpenReport }) {
  return (
    <div className={`flow-phase flow-complete${active ? " is-active" : ""}`}>
      <div className="flow-complete-top">
        <div className="flow-complete-top-eyebrow">· The Word is Spoken ·</div>
      </div>
      <div className="flow-complete-inner">
        <div className="flow-complete-eyebrow">All six spirits have sealed their testimony</div>
        <button className="flow-complete-cta" onClick={onOpenReport}>
          Open the Scroll &nbsp;⊙
        </button>
      </div>
    </div>
  );
}

/* ── circle host — always on, sigil hit zones rendered over the SVG ──── */
function CircleHost({ phase, progressIdx, completed, onSigilClick, onCenterClick }) {
  const size = useCircleSize();
  // Clamp activeIdx — progressIdx briefly hits 6 between last spirit and
  // phase=complete; positions[6] is undefined and crashes CircleOfSpirits.
  const safeProgress = progressIdx >= 0 && progressIdx <= 5 ? progressIdx : -1;
  const activeIdx = phase === "working" ? safeProgress : -1;
  const completedNow =
    phase === "complete" ? [0, 1, 2, 3, 4, 5] : completed;
  const interactive = phase === "working" || phase === "complete";

  return (
    <div className="flow-circle-host" style={{ width: size, height: size }}>
      <CircleOfSpirits
        active={activeIdx}
        completed={completedNow}
        size={size}
        variant="plate"
      />

      {/* Glow that appears at center when complete */}
      <div className="flow-center-glow">
        <div className="flow-center-glow-ring r3" />
        <div className="flow-center-glow-ring" />
        <div className="flow-center-glow-ring r2" />
      </div>

      {/* Sigil hit zones — only clickable when interactive */}
      {interactive &&
        STATION_POSITIONS.map((pos, i) => (
          <button
            key={i}
            className="station-hit"
            aria-label={`Open ${SIGILS[SPIRIT_ORDER[i]].name} testimony`}
            style={{ left: `${pos.x}%`, top: `${pos.y}%` }}
            onClick={(e) => {
              e.stopPropagation();
              onSigilClick(i);
            }}
          />
        ))}

      {/* Center hit — only enabled when complete */}
      <button
        className="center-hit"
        aria-label="Open the scroll"
        onClick={(e) => { e.stopPropagation(); onCenterClick(); }}
      />
    </div>
  );
}

/* ── spirit detail card (overlay during working/complete) ─────────────── */
function SpiritCard({ idx, progressIdx, completed, spiritData, onClose }) {
  if (idx == null) return null;
  const key = SPIRIT_ORDER[idx];
  const s = SIGILS[key];
  const fallback = FLOW_CONTENT.spirits[key];
  const data = spiritData ? spiritData[idx] : null;
  const content = renderSpiritCardContent(idx, data, fallback);
  const isActive = idx === progressIdx;
  const isDone = completed.includes(idx);
  const stateLabel = isActive ? "Speaking" : isDone ? "Sealed" : "Awaiting";
  const stateCls = isActive ? "active" : isDone ? "done" : "pending";

  return (
    <div className="flow-spirit-card" role="dialog" aria-label={`${s.name} testimony`}>
      <button className="flow-spirit-card-close" onClick={onClose}>✕ Close</button>
      <div className="flow-spirit-card-head">
        <div className="flow-spirit-card-sigil" style={{ color: stateCls === "active" ? "var(--accent)" : "var(--ink)" }}>
          {React.createElement(s.Comp, { size: 56 })}
        </div>
        <div>
          <div className="flow-spirit-card-name">
            {ROMAN[idx]} · {s.name}
          </div>
          <div className="flow-spirit-card-verb">{s.verb}</div>
        </div>
        <div className={`flow-spirit-card-state ${stateCls}`}>{stateLabel}</div>
      </div>
      <div className="flow-spirit-card-body">{content.body}</div>
      {content.footnotes && (
        <div className="flow-spirit-card-footnotes">{content.footnotes}</div>
      )}
      {content.meta.length > 0 && (
        <div className="flow-spirit-card-meta">
          {content.meta.map(([label, val]) => (
            <div key={label}>
              {label}
              <strong>{val}</strong>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── report overlay (full testimony, opens from the circle's heart) ───── */
function ReportOverlay({ open, onClose, reportText, elapsedMs, onCopyLink, copyState }) {
  const wordCount = React.useMemo(() => {
    if (!reportText) return 0;
    return reportText.trim().split(/\s+/).length;
  }, [reportText]);

  const html = React.useMemo(() => {
    if (!reportText) return "";
    if (typeof marked === "undefined") {
      // marked.js not loaded — fall back to escaped <pre>
      const esc = reportText.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
      return `<pre style="white-space:pre-wrap;font-family:inherit">${esc}</pre>`;
    }
    return marked.parse(reportText);
  }, [reportText]);

  return (
    <>
      <div className="flow-report-scrim" onClick={onClose} />
      <div className="flow-report" role="dialog" aria-label="Testimony">
        <div className="flow-report-head">
          <div>
            <div className="flow-report-eyebrow">
              Testimony · sealed at {fmtMs(elapsedMs)} · {wordCount.toLocaleString()} words
            </div>
            <h2 className="flow-report-title">The Tribunal's Testimony</h2>
          </div>
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <button className="flow-report-close" onClick={onCopyLink}>
              {copyState === "copied" ? "✓ Link copied" : "⎘ Copy share link"}
            </button>
            <button className="flow-report-close" onClick={onClose}>✕ Close the Scroll</button>
          </div>
        </div>
        <div className="flow-report-body">
          <div
            className="flow-report-prose"
            dangerouslySetInnerHTML={{ __html: html }}
          />
          <aside className="flow-report-rail">
            <h3>About this report</h3>
            <p style={{ opacity: 0.7, fontSize: "0.85em", lineHeight: 1.5 }}>
              Sources are cited inline. This report and its share URL are
              ephemeral — they live until the next redeployment of the demo.
            </p>
          </aside>
        </div>
      </div>
    </>
  );
}

/* ── main app ─────────────────────────────────────────────────────────── */
function FlowPrototype() {
  const tweaks = (typeof useTweaks === "function")
    ? useTweaks(PHASE_DEFAULTS)
    : [PHASE_DEFAULTS, () => {}];
  const t = tweaks[0];
  const setTweak = tweaks[1];

  const [phase, setPhase] = React.useState("idle");        // idle | composing | working | complete
  const [question, setQuestion] = React.useState(FLOW_CONTENT.defaultQuestion);
  const [challenges, setChallenges] = React.useState(2);
  const [progressIdx, setProgressIdx] = React.useState(-1);
  const [completed, setCompleted] = React.useState([]);
  const [spiritOpen, setSpiritOpen] = React.useState(null);
  const [reportOpen, setReportOpen] = React.useState(false);
  const [elapsedMs, setElapsedMs] = React.useState(0);
  const [jobId, setJobId] = React.useState(null);
  const [reportText, setReportText] = React.useState(null);
  const [errorText, setErrorText] = React.useState(null);
  const [spiritData, setSpiritData] = React.useState({});

  const [config, setConfig] = React.useState(null);

  const esRef = React.useRef(null);
  const lastEventIdRef = React.useRef(-1);
  // Node-name → spirit-index mapping. Seeded from DEFAULT_NODE_ORDER, then
  // updated once GET /config resolves so backend renames propagate automatically.
  const nodeToSpiritRef = React.useRef(
    Object.fromEntries(DEFAULT_NODE_ORDER.map((name, i) => [name, i]))
  );
  // Epoch-ms anchor for the live timer. The timer interval reads this on
  // every tick, so refreshing it from a server snapshot (on cold load via
  // /r/{id} or on visibilitychange) corrects the display without having to
  // restart the interval.
  const startedAtRef = React.useRef(null);
  const [copyState, setCopyState] = React.useState("idle");

  const copyShareLink = React.useCallback(async () => {
    const id = jobId || sessionStorage.getItem("jobId");
    if (!id) return;
    const url = `${window.location.origin}/r/${id}`;
    try {
      await navigator.clipboard.writeText(url);
      setCopyState("copied");
      setTimeout(() => setCopyState("idle"), 2000);
    } catch {
      // Clipboard API can fail on insecure contexts; prompt as fallback.
      window.prompt("Copy this link:", url);
    }
  }, [jobId]);

  const closeStream = React.useCallback(() => {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
  }, []);

  const handleEvent = React.useCallback((evt) => {
    lastEventIdRef.current = Math.max(lastEventIdRef.current, Number(evt.id));
    if (evt.event === "node_complete") {
      const idx = nodeToSpiritRef.current[evt.data.node];
      if (idx !== undefined) {
        setProgressIdx(idx);
        setCompleted((prev) => (prev.includes(idx) ? prev : [...prev, idx]));
        setSpiritData((prev) => ({ ...prev, [idx]: evt.data }));
      }
    } else if (evt.event === "complete") {
      setReportText(evt.data.report || "");
      setPhase("complete");
      closeStream();
    } else if (evt.event === "error_event") {
      setErrorText(evt.data.message || "Unknown error");
      closeStream();
    }
  }, [closeStream]);

  const connectStream = React.useCallback((id) => {
    closeStream();
    const url = `/research/${id}/stream?last_event_id=${lastEventIdRef.current}`;
    const es = new EventSource(url);
    esRef.current = es;
    ["node_complete", "complete", "error_event"].forEach((name) => {
      es.addEventListener(name, (e) => {
        handleEvent({ id: e.lastEventId, event: name, data: JSON.parse(e.data) });
      });
    });
    es.onerror = () => {
      // EventSource auto-reconnects; we only clean up on explicit close.
    };
  }, [closeStream, handleEvent]);

  /* Hydrate from snapshot — used on first mount and on visibilitychange. */
  const hydrate = React.useCallback(async (id) => {
    let snap;
    try {
      const r = await fetch(`/research/${id}`);
      if (r.status === 404) {
        sessionStorage.removeItem("jobId");
        return false;
      }
      snap = await r.json();
    } catch {
      return false;
    }
    setJobId(id);
    setQuestion(snap.question || "");
    // Restore the slider/header to this job's actual max_iterations value.
    if (snap.max_iterations != null) setChallenges(snap.max_iterations);
    // Replay events to rebuild progressIdx / completed / spiritData / lastEventId.
    // Later events overwrite earlier ones for the same spirit (latest-wins on loops).
    let maxId = -1;
    const seen = new Set();
    let latestIdx = -1;
    const rebuiltData = {};
    for (const evt of snap.events || []) {
      maxId = Math.max(maxId, evt.id);
      if (evt.event === "node_complete") {
        const idx = nodeToSpiritRef.current[evt.data.node];
        if (idx !== undefined) {
          seen.add(idx);
          latestIdx = idx;
          rebuiltData[idx] = evt.data;
        }
      }
    }
    lastEventIdRef.current = maxId;
    if (seen.size) {
      setCompleted(Array.from(seen).sort((a, b) => a - b));
      setProgressIdx(latestIdx);
      setSpiritData(rebuiltData);
    }
    if (snap.status === "done") {
      setReportText(snap.report || "");
      // Seed the elapsed display from the job's recorded duration so the
      // "sealed at …" timestamp is correct even after a page reload or tab switch.
      if (snap.duration_ms != null) setElapsedMs(snap.duration_ms);
      setPhase("complete");
    } else if (snap.status === "error") {
      setErrorText(snap.error || "Unknown error");
      setPhase("idle");
    } else if (snap.status === "running") {
      // Anchor the live timer on the server's started_at so it stays accurate
      // even after the tab was backgrounded (where setInterval gets throttled).
      // The timer interval reads startedAtRef each tick, so updating it here
      // self-corrects on the next tick without restarting the interval.
      if (snap.started_at_ms != null) {
        startedAtRef.current = snap.started_at_ms;
        setElapsedMs(Date.now() - snap.started_at_ms);
      }
      setPhase("working");
      connectStream(id);
    }
    return true;
  }, [connectStream]);

  /* Fetch server config once on mount. */
  React.useEffect(() => {
    fetch("/config")
      .then((r) => r.json())
      .then((cfg) => setConfig(cfg))
      .catch(() => {}); // silently fall back to defaults on failure
  }, []);

  /* Keep nodeToSpiritRef in sync with config so event routing uses server names. */
  React.useEffect(() => {
    if (!config) return;
    nodeToSpiritRef.current = Object.fromEntries(
      config.node_order.map((name, i) => [name, i])
    );
  }, [config]);

  /* Seed challenges default from config (only when no job is active). */
  React.useEffect(() => {
    if (config && phase === "idle") {
      setChallenges(config.max_iterations_default);
    }
  }, [config]); // intentionally omits phase — only fires once when config loads

  /* On mount: prefer /r/{id} URL, then sessionStorage. Also listen for tab refocus. */
  React.useEffect(() => {
    const fromUrl = jobIdFromPath();
    const fromSession = sessionStorage.getItem("jobId");
    const id = fromUrl || fromSession;
    if (id) hydrate(id);

    const onVis = () => {
      if (document.visibilityState !== "visible") return;
      const current = jobIdFromPath() || sessionStorage.getItem("jobId");
      if (current) hydrate(current);
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      document.removeEventListener("visibilitychange", onVis);
      closeStream();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Live timer during the working phase. Anchored on startedAtRef so a
  // re-hydrate from the server (cold load or visibilitychange) can correct
  // the display by writing the ref — no interval restart needed.
  React.useEffect(() => {
    if (phase !== "working") return;
    if (startedAtRef.current == null) startedAtRef.current = Date.now() - elapsedMs;
    const id = setInterval(() => setElapsedMs(Date.now() - startedAtRef.current), 80);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase]);

  const openForm = () => setPhase("composing");
  const cancelForm = () => setPhase("idle");

  const submit = async () => {
    setElapsedMs(0);
    setProgressIdx(-1);
    setCompleted([]);
    setReportText(null);
    setErrorText(null);
    setSpiritData({});
    lastEventIdRef.current = -1;
    startedAtRef.current = Date.now();
    setPhase("working");
    try {
      const r = await fetch("/research", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, max_iterations: challenges }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const { job_id } = await r.json();
      sessionStorage.setItem("jobId", job_id);
      setJobId(job_id);
      // Reflect the job in the URL so a refresh / share captures the same job.
      window.history.replaceState(null, "", `/r/${job_id}`);
      connectStream(job_id);
    } catch (e) {
      setErrorText(`Failed to start: ${e.message}`);
      setPhase("idle");
    }
  };

  const reset = () => {
    closeStream();
    sessionStorage.removeItem("jobId");
    window.history.replaceState(null, "", "/");
    setJobId(null);
    setReportText(null);
    setErrorText(null);
    setSpiritData({});
    setPhase("idle");
    setProgressIdx(-1);
    setCompleted([]);
    setSpiritOpen(null);
    setReportOpen(false);
    setElapsedMs(0);
    lastEventIdRef.current = -1;
    startedAtRef.current = null;
  };

  // ESC closes overlays
  React.useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") {
        if (reportOpen) setReportOpen(false);
        else if (spiritOpen != null) setSpiritOpen(null);
        else if (phase === "composing") cancelForm();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [reportOpen, spiritOpen, phase]);

  // Jump-to helpers for the tweaks panel
  const jumpTo = (next) => {
    setSpiritOpen(null);
    setReportOpen(false);
    if (next === "idle") {
      reset();
    } else if (next === "composing") {
      setPhase("composing");
    } else if (next === "working") {
      setElapsedMs(12000);
      setProgressIdx(2);
      setCompleted([0, 1]);
      setPhase("working");
    } else if (next === "complete") {
      setElapsedMs(62400);
      setProgressIdx(-1);
      setCompleted([0, 1, 2, 3, 4, 5]);
      setPhase("complete");
    }
  };

  const rootCls = `flow-root${spiritOpen != null ? " has-spirit" : ""}${reportOpen ? " has-report" : ""}`;

  return (
    <div className={rootCls} data-phase={phase}>
      {errorText && (
        <div
          role="alert"
          style={{
            position: "fixed",
            top: 12,
            left: "50%",
            transform: "translateX(-50%)",
            background: "rgba(120, 20, 20, 0.95)",
            color: "#fff",
            padding: "0.6rem 1rem",
            borderRadius: 4,
            fontSize: "0.85em",
            zIndex: 1000,
            maxWidth: "90vw",
          }}
        >
          ⚠ {errorText}
          <button
            onClick={() => setErrorText(null)}
            style={{
              marginLeft: "1rem",
              background: "transparent",
              border: "1px solid rgba(255,255,255,0.4)",
              color: "#fff",
              cursor: "pointer",
              padding: "0.1rem 0.4rem",
            }}
          >
            ✕
          </button>
        </div>
      )}
      <TopStrip phase={phase} elapsedMs={elapsedMs} challenges={challenges} config={config} />

      <div className="flow-stage">
        {/* The Circle — always mounted, scales/fades per phase */}
        <CircleHost
          phase={phase}
          progressIdx={progressIdx}
          completed={completed}
          onSigilClick={(i) => setSpiritOpen(i)}
          onCenterClick={() => setReportOpen(true)}
        />

        {/* Three phase layers, only one is-active at a time */}
        <WelcomePhase
          active={phase === "idle" || phase === "composing"}
          onOpenForm={openForm}
        />
        <WorkingPhase
          active={phase === "working"}
          question={question}
          progressIdx={progressIdx < 0 ? 0 : Math.min(progressIdx, 5)}
          completed={completed}
        />
        <CompletePhase
          active={phase === "complete"}
          onOpenReport={() => setReportOpen(true)}
        />

        {/* Compose form (shown over welcome when phase=composing) */}
        <ComposeForm
          phase={phase}
          question={question}
          setQuestion={setQuestion}
          challenges={challenges}
          setChallenges={setChallenges}
          maxChallenges={config ? config.max_iterations_ceiling : 5}
          onCancel={cancelForm}
          onSubmit={submit}
        />

        {/* Spirit detail card + scrim */}
        <div
          className="flow-spirit-card-scrim"
          onClick={() => setSpiritOpen(null)}
        />
        <SpiritCard
          idx={spiritOpen}
          progressIdx={progressIdx}
          completed={completed}
          spiritData={spiritData}
          onClose={() => setSpiritOpen(null)}
        />

        {/* Report overlay */}
        <ReportOverlay
          open={reportOpen}
          onClose={() => setReportOpen(false)}
          reportText={reportText}
          elapsedMs={elapsedMs}
          onCopyLink={copyShareLink}
          copyState={copyState}
        />

        {/* Reset / replay */}
        <button className="flow-reset" onClick={reset}>
          ↺ Reset
        </button>
      </div>

      <Footer />

      {/* Tweaks */}
      {typeof TweaksPanel === "function" && (
        <TweaksPanel>
          <TweakSection label="Phase">
            <TweakSelect
              label="Jump to"
              value={phase}
              onChange={jumpTo}
              options={[
                { value: "idle",      label: "1 · Welcome" },
                { value: "composing", label: "2 · Compose form" },
                { value: "working",   label: "3 · Working (mid-flow)" },
                { value: "complete",  label: "4 · Complete" },
              ]}
            />
          </TweakSection>
          <TweakSection label="Animation">
            <TweakSlider
              label="Step duration"
              min={500}
              max={5000}
              step={100}
              unit="ms"
              value={t.stepDurationMs}
              onChange={(v) => setTweak("stepDurationMs", v)}
            />
          </TweakSection>
          <TweakSection label="Debug">
            <TweakButton label="↺ Reset flow" onClick={reset} />
            <TweakButton label="Open report" onClick={() => setReportOpen(true)} secondary />
          </TweakSection>
        </TweaksPanel>
      )}
    </div>
  );
}

window.FlowPrototype = FlowPrototype;
