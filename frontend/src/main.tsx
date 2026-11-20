import { lazy, Suspense, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowUp,
  BookOpen,
  ChevronRight,
  FileText,
  FlaskConical,
  Library,
  Moon,
  Plus,
  Search,
  Settings,
  ShieldCheck,
  Sun,
  X,
  ExternalLink,
  PanelLeftClose,
  Download,
} from "lucide-react";
import "./style.css";
import {
  AISettings,
  OrganisationHistory,
  send,
  type AIConfig,
} from "./AISettings";
const Pdf = lazy(() => import("./Pdf"));
type Document = {
  id: number;
  title: string;
  filename: string;
  pages: number;
  passages: number;
  available: boolean;
  processing_state?: string;
  attachments?: { filename: string; available: boolean }[];
};
type Source = {
  source_id: number;
  document_id: number;
  title: string;
  page: number;
  excerpt: string;
  citation: string;
  bibliography?: {
    authors?: string;
    year?: string | number;
    journal?: string;
    doi?: string;
    text_origin?: string;
  };
};
type Detail = Document & {
  page: number;
  excerpt: string | null;
  authors: string | null;
  abstract: string | null;
  metadata_provenance: string;
  bibliography?: {
    year?: string;
    journal?: string;
    doi?: string;
    categories?: string[];
    text_origin?: string;
    extraction_warning?: string;
  };
};
type Stats = {
  on_disk: number;
  indexed: number;
  unindexed: number;
  passages: number;
  missing: number;
  duplicate_copies?: number;
  database_available: boolean;
  folder_available: boolean;
};
type Turn = {
  question: string;
  sources: Source[];
  answer?: string;
  notice?: string;
};
async function api<T>(url: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, { signal });
  if (!response.ok)
    throw new Error(
      `Local API returned ${response.status}. Check that the backend is running and the index is compatible.`,
    );
  return response.json();
}
function Readiness({ advanced = false }: { advanced?: boolean }) {
  const [status, setStatus] = useState<{
    states: Record<string, number>;
    semantic_available: boolean;
    metadata_preparing?: number;
    metadata_attention?: number;
    failures: unknown[];
    scan_error?: string;
  }>();
  useEffect(() => {
    let alive = true;
    const refresh = () =>
      api<typeof status>("/api/library/readiness")
        .then((s) => {
          if (alive) setStatus(s);
        })
        .catch(() => {});
    void refresh();
    const timer = setInterval(refresh, 10000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);
  if (!status) return <p className="muted">Connecting to Smart Library…</p>;
  const active =
    (status.states.pending || 0) +
    (status.states.running || 0) +
    (status.metadata_preparing || 0);
  return (
    <div className="muted" role="status">
      {status.scan_error
        ? "Library folder temporarily unavailable"
        : active
          ? `Smart Library · preparing ${active} documents in the background`
          : "Smart Library · ready for questions"}
      {!!status.failures?.length && (
        <span>
          {" "}
          · {status.failures.length} documents need attention; other sources
          remain searchable
        </span>
      )}
      {advanced && (
        <pre style={{ whiteSpace: "pre-wrap" }}>
          {JSON.stringify(status, null, 2)}
        </pre>
      )}
    </div>
  );
}
function App() {
  const [ai, setAI] = useState<AIConfig>({
    enabled: false,
    consent: false,
    provider: "Gemini",
    model: "",
    credentials: {},
    cost: "Unknown",
  });
  useEffect(() => {
    api<AIConfig>("/api/ai/settings")
      .then(setAI)
      .catch(() => {});
    api<Turn[]>("/api/history")
      .then(setTurns)
      .catch(() => {});
  }, []);

  const [left, setLeft] = useState(true);
  const [right, setRight] = useState(true);
  const [theme, setTheme] = useState(
    localStorage.getItem("lab-theme") || "light",
  );
  const [view, setView] = useState("Research");
  const [stats, setStats] = useState<Stats>();
  const [docs, setDocs] = useState<Document[]>([]);
  const [filter, setFilter] = useState("");
  const [question, setQuestion] = useState("");
  const [limit, setLimit] = useState(6);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<{
    id: number;
    page: number;
    excerpt?: string;
  }>();
  const [detail, setDetail] = useState<Detail>();
  const [detailError, setDetailError] = useState("");
  const [pdf, setPdf] = useState(false);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("lab-theme", theme);
  }, [theme]);
  useEffect(() => {
    const abort = new AbortController();
    Promise.all([
      api<Stats>("/api/library/stats", abort.signal),
      api<Document[]>("/api/documents", abort.signal),
    ])
      .then(([s, d]) => {
        setStats(s);
        setDocs(d);
      })
      .catch((e) => {
        if (!abort.signal.aborted) setError(e.message);
      });
    return () => abort.abort();
  }, []);
  useEffect(() => {
    const timer = setInterval(() => {
      Promise.all([
        api<Stats>("/api/library/stats"),
        api<Document[]>("/api/documents"),
      ])
        .then(([s, d]) => {
          setStats(s);
          setDocs(d);
        })
        .catch(() => {});
    }, 10000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    if (!selected) return;
    const abort = new AbortController();
    setDetail(undefined);
    setDetailError("");
    setPdf(false);
    api<Detail>(
      `/api/documents/${selected.id}?page=${selected.page}`,
      abort.signal,
    )
      .then(setDetail)
      .catch((e) => {
        if (!abort.signal.aborted) setDetailError(e.message);
      });
    return () => abort.abort();
  }, [selected]);
  function open(id: number, page = 1, excerpt?: string) {
    setSelected({ id, page, excerpt });
    setRight(true);
  }
  async function importFiles(files: FileList | null) {
    if (!files) return;
    setError("");
    for (const file of Array.from(files)) {
      try {
        const response = await fetch(
          "/api/library/import?name=" + encodeURIComponent(file.name),
          {
            method: "POST",
            headers: { "Content-Type": "application/pdf" },
            body: file,
          },
        );
        const data = await response.json();
        if (!response.ok) throw Error(data.detail);
      } catch (e) {
        setError((e as Error).message);
        break;
      }
    }
  }
  async function search(value = question) {
    if (!value.trim() || busy) return;
    setBusy(true);
    setError("");
    setView("Research");
    try {
      const result = await send<Turn>("/api/ask", { question: value, limit });
      setTurns((t) => [...t, { ...result, question: value }]);
      setQuestion("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function exportEvidence() {
    const rows = [
      [
        "Question",
        "Citation",
        "Paper",
        "Authors",
        "Year",
        "Journal",
        "DOI",
        "Page",
        "Exact excerpt",
        "Extraction",
        "Assessment",
        "PDF link",
      ],
      ...turns.flatMap((t) =>
        t.sources.map((s) => [
          t.question,
          s.citation,
          s.title,
          s.bibliography?.authors || "Unavailable",
          String(s.bibliography?.year || "Unavailable"),
          s.bibliography?.journal || "Unavailable",
          s.bibliography?.doi || "Unavailable",
          String(s.page),
          s.excerpt,
          s.bibliography?.text_origin || "pdf_text",
          "Retrieved; entailment not assessed",
          `${location.origin}/api/documents/${s.document_id}/pdf#page=${s.page}`,
        ]),
      ),
    ];
    const blob = new Blob(
      [
        "\ufeff" +
          rows
            .map((r) =>
              r
                .map(
                  (c) =>
                    `"${(/^[=+@\-]/.test(c) ? "'" : "") + c.replaceAll('"', '""')}"`,
                )
                .join(","),
            )
            .join("\r\n"),
      ],
      { type: "text/csv;charset=utf-8" },
    );
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "evidence.csv";
    a.click();
    URL.revokeObjectURL(url);
  }
  const filtered = docs.filter((d) =>
    `${d.title} ${d.filename}`.toLowerCase().includes(filter.toLowerCase()),
  );
  return (
    <div
      className={`app ${left ? "" : "rail-small"} ${right ? "" : "reference-hidden"}`}
    >
      <aside className="rail">
        <div className="brand">
          <span className="brand-icon">
            <FlaskConical size={21} />
          </span>
          {left && (
            <div>
              Lab Research<span>YOUR SCIENTIFIC WORKSPACE</span>
            </div>
          )}
        </div>
        <button
          className="new"
          title="New research"
          onClick={() => {
            setTurns([]);
            setView("Research");
            setQuestion("");
          }}
        >
          <Plus size={18} />
          {left && "New research"}
        </button>
        <div className="nav-label">{left ? "WORKSPACE" : "···"}</div>
        <nav>
          {[
            { label: "Research", icon: BookOpen },
            { label: "Library", icon: Library },
            { label: "Evidence", icon: FileText },
          ].map(({ label, icon: Icon }) => (
            <button
              aria-label={label}
              title={label}
              className={view === label ? "active" : ""}
              onClick={() => setView(label)}
              key={label}
            >
              <Icon size={18} />
              {left && label}
              {left && label === "Library" && (
                <small>{stats?.indexed ?? "—"}</small>
              )}
            </button>
          ))}
        </nav>
        {left && (
          <div className="rail-note">
            <span className="tiny-label">THIS SESSION</span>
            {turns.length ? (
              turns.map((t, i) => (
                <button key={i} onClick={() => setView("Research")}>
                  {t.question}
                </button>
              ))
            ) : (
              <p>Your next question starts here.</p>
            )}
            <p>Research history is saved locally.</p>
          </div>
        )}
        <div className="rail-bottom">
          {left && (
            <div className="index-card">
              <span>
                <i />{" "}
                {stats?.database_available && stats?.folder_available
                  ? "Local library connected"
                  : stats
                    ? "Library configuration needed"
                    : "Connecting to library..."}
              </span>
              <strong>{stats?.indexed ?? "—"} indexed records</strong>
              <small>
                {stats?.on_disk ?? "—"} on disk · {stats?.unindexed ?? "—"}{" "}
                unindexed
              </small>
              <div className="progress">
                <span
                  style={{
                    width: stats?.on_disk
                      ? `${(100 * (stats.on_disk - stats.unindexed)) / stats.on_disk}%`
                      : "0%",
                  }}
                />
              </div>
              <small>Original PDFs unchanged</small>
            </div>
          )}
          <button title="Settings" onClick={() => setView("Settings")}>
            <Settings size={18} />
            {left && "Settings"}
          </button>
          <button
            title="Collapse navigation"
            aria-label="Toggle navigation"
            onClick={() => setLeft(!left)}
          >
            <PanelLeftClose size={18} />
            {left && "Collapse sidebar"}
          </button>
        </div>
      </aside>
      <main>
        <Readiness />
        <header>
          <div className="breadcrumb">
            Workspace <span>/</span> <strong>{view}</strong>
          </div>
          <div className="header-actions">
            <span className="local">
              <i />{" "}
              {ai.enabled ? `Cloud AI · ${ai.provider}` : "Local retrieval"}
            </span>
            <button
              aria-label="Toggle theme"
              title="Toggle light/dark theme"
              onClick={() => setTheme(theme === "light" ? "dark" : "light")}
            >
              {theme === "light" ? <Moon size={17} /> : <Sun size={17} />}
            </button>
            <button
              aria-label="Toggle references"
              title="Toggle references"
              onClick={() => setRight(!right)}
            >
              <BookOpen size={18} />
            </button>
          </div>
        </header>
        {error && (
          <div className="error" role="alert">
            {error}
            <button aria-label="Dismiss error" onClick={() => setError("")}>
              <X size={15} />
            </button>
          </div>
        )}
        <div className="main-scroll">
          {view === "Research" && (
            <div className="research">
              {turns.length === 0 ? (
                <>
                  <div className="eyebrow">
                    <span /> BUILT FOR CURIOUS MINDS
                  </div>
                  <h1>
                    Good research starts
                    <br />
                    with a better question.
                  </h1>
                  <p className="intro">
                    Explore your papers. Connect the evidence.
                    <br />
                    Keep every insight grounded in its source.
                  </p>
                  <div className="starter-grid">
                    {[
                      "How does annealing affect TiO2 thin films?",
                      "Find evidence on oxygen vacancies",
                      "Compare electric field effects",
                    ].map((q, i) => (
                      <button
                        key={q}
                        onClick={() => {
                          setQuestion(q);
                        }}
                      >
                        <span className="starter-number">0{i + 1}</span>
                        <span>{q}</span>
                        <ChevronRight size={16} />
                      </button>
                    ))}
                  </div>
                  <div className="library-overview">
                    <span className="overview-icon">
                      <Library size={21} />
                    </span>
                    <div>
                      <strong>Your literature, connected.</strong>
                      <p>
                        {stats
                          ? `${stats.indexed} indexed records · ${stats.passages.toLocaleString()} searchable passages`
                          : "Connecting to your local library…"}
                      </p>
                    </div>
                    <button onClick={() => setView("Library")}>
                      Explore library <ChevronRight size={14} />
                    </button>
                  </div>
                </>
              ) : (
                <div className="turns">
                  {turns.map((turn, i) => (
                    <article className="turn" key={i}>
                      <div className="eyebrow">RESEARCH QUESTION {i + 1}</div>
                      <h2>{turn.question}</h2>
                      {turn.answer && (
                        <div className="answer">
                          <p className="muted">
                            AI interpretation · {turn.notice}
                          </p>
                          {turn.answer
                            .split(/(\[S\d+\])/g)
                            .map((part, index) => {
                              const source = turn.sources.find(
                                (s) => `[${s.citation}]` === part,
                              );
                              return source ? (
                                <button
                                  key={index}
                                  className="citation"
                                  onClick={() =>
                                    open(
                                      source.document_id,
                                      source.page,
                                      source.excerpt,
                                    )
                                  }
                                >
                                  {part}
                                </button>
                              ) : (
                                <span key={index}>{part}</span>
                              );
                            })}
                        </div>
                      )}
                      <div className="result-heading">
                        <FlaskConical size={19} />
                        <strong>Evidence from your library</strong>
                        <span>{turn.sources.length} passages</span>
                      </div>
                      <p className="muted">
                        Keyword retrieval · exact indexed excerpts. These
                        passages have not been assessed for support of a
                        scientific claim.
                      </p>
                      {!turn.sources.length && (
                        <div className="empty">
                          No matching passages. Try a material name or a shorter
                          phrase.
                        </div>
                      )}
                      {turn.sources.map((s) => (
                        <div className="source-card" key={s.source_id}>
                          <button
                            className="citation"
                            onClick={() =>
                              open(s.document_id, s.page, s.excerpt)
                            }
                          >
                            {s.citation} <span>p. {s.page}</span>
                          </button>
                          <button
                            className="source-title"
                            onClick={() =>
                              open(s.document_id, s.page, s.excerpt)
                            }
                          >
                            {s.title}
                          </button>
                          <p>{s.excerpt}</p>
                          <button
                            className="text-button"
                            onClick={() =>
                              open(s.document_id, s.page, s.excerpt)
                            }
                          >
                            Inspect passage & PDF <ChevronRight size={14} />
                          </button>
                        </div>
                      ))}
                    </article>
                  ))}
                </div>
              )}
            </div>
          )}
          {view === "Library" && (
            <section className="page">
              <div className="eyebrow">YOUR LOCAL COLLECTION</div>
              <h1>Literature library</h1>
              <div
                className="drop-zone"
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  void importFiles(e.dataTransfer.files);
                }}
              >
                <strong>Drop PDFs here</strong>
                <span>
                  {" "}
                  or add files to your configured library folder. Everything
                  else happens automatically.
                </span>
                <label className="primary">
                  Add PDFs
                  <input
                    aria-label="Import PDFs"
                    type="file"
                    accept="application/pdf,.pdf"
                    multiple
                    onChange={(e) => {
                      void importFiles(e.target.files);
                      e.target.value = "";
                    }}
                  />
                </label>
              </div>
              <p className="intro">
                Add PDFs to your library. Identification, organisation and
                search preparation happen automatically.
              </p>
              <div className="stat-grid">
                {[
                  ["On disk", stats?.on_disk],
                  ["Searchable papers", stats?.indexed],
                  ["Awaiting readable text", stats?.unindexed],
                  ["Duplicate copies", stats?.duplicate_copies],
                ].map(([l, n]) => (
                  <div key={l}>
                    <strong>{n ?? "—"}</strong>
                    <span>{l}</span>
                  </div>
                ))}
              </div>
              <p className="muted">
                Smart Library detects exact copies and prepares new PDFs
                automatically.
              </p>
              <label className="library-search">
                <Search size={17} />
                <input
                  aria-label="Search library"
                  placeholder="Search indexed titles or filenames…"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                />
              </label>
              <div className="list-label">
                {filtered.length} PAPERS <span>Title / extracted pages</span>
              </div>
              {filtered.map((d) => (
                <button
                  className="doc-row"
                  key={d.id}
                  onClick={() => open(d.id)}
                >
                  <span className="doc-icon">
                    <FileText size={19} />
                  </span>
                  <div>
                    <strong>{d.title}</strong>
                    <small>
                      {d.filename}{" "}
                      {d.attachments &&
                      d.attachments.filter((a) => a.available).length > 1
                        ? ` · ${d.attachments.filter((a) => a.available).length} attachments`
                        : ""}
                    </small>
                  </div>
                  <span>{d.pages} pp.</span>
                  <span className={d.available ? "tag" : "tag warning"}>
                    {!d.available
                      ? "PDF missing"
                      : d.passages
                        ? "Search ready"
                        : d.processing_state === "needs_attention"
                          ? "Needs attention"
                          : "Preparing"}
                  </span>
                  <ChevronRight size={15} />
                </button>
              ))}
              {!filtered.length && (
                <p className="empty">
                  No indexed documents found. Check the configured database or
                  try another title.
                </p>
              )}
            </section>
          )}
          {view === "Evidence" && (
            <section className="page">
              <div className="eyebrow">TRACEABLE RESEARCH</div>
              <h1>Evidence notebook</h1>
              <p className="intro">
                Exact excerpts from this session, ready for human review.
              </p>
              <button
                className="primary"
                disabled={!turns.some((t) => t.sources.length)}
                onClick={exportEvidence}
              >
                <Download size={16} /> Export evidence CSV
              </button>
              <p className="muted">
                Retrieval is not claim verification. Support categories,
                conditions and experimental comparisons are pending.
              </p>
              {turns.flatMap((t, i) =>
                t.sources.map((s) => (
                  <div className="source-card" key={`${i}-${s.source_id}`}>
                    <button
                      className="source-title"
                      onClick={() => open(s.document_id, s.page, s.excerpt)}
                    >
                      {s.title} · p. {s.page}
                    </button>
                    <p>{s.excerpt}</p>
                    <span className="tag">Entailment not assessed</span>
                  </div>
                )),
              )}
              {!turns.length && (
                <div className="empty">
                  Run a research query to collect evidence here.
                </div>
              )}
            </section>
          )}
          {view === "Settings" && (
            <section className="page">
              <div className="eyebrow">WORKSPACE PREFERENCES</div>
              <h1>Local by default.</h1>
              <Readiness advanced />
              <AISettings config={ai} onChange={setAI} />
              <OrganisationHistory />
              <div className="settings-card">
                <Library />
                <div>
                  <h3>Existing index · read-only</h3>
                  <p>
                    Configure LAB_DATABASE and LAB_PDF_FOLDER before starting
                    the backend. Search uses SQLite FTS5 and suppresses similar
                    passages. Existing embeddings are preserved in the original
                    index. Smart Library prepares hybrid search automatically in
                    a separate local database.
                  </p>
                </div>
              </div>
              <button
                className="primary"
                onClick={() => setTheme(theme === "light" ? "dark" : "light")}
              >
                Switch to {theme === "light" ? "dark" : "light"} theme
              </button>
            </section>
          )}
        </div>
        {view === "Research" && (
          <footer>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void search();
              }}
            >
              <textarea
                aria-label="Research question"
                placeholder="Ask a question about your research…"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void search();
                  }
                }}
              />
              <div className="composer-bottom">
                <span>
                  <button
                    type="button"
                    aria-label="Toggle AI"
                    onClick={async () => {
                      try {
                        setAI(
                          await send<AIConfig>(
                            "/api/ai/settings",
                            { ...ai, enabled: !ai.enabled },
                            "PUT",
                          ),
                        );
                      } catch (e) {
                        setError((e as Error).message);
                        setView("Settings");
                      }
                    }}
                  >
                    <ShieldCheck size={14} />{" "}
                    {ai.enabled ? `AI On · ${ai.provider}` : "Retrieval Only"}
                  </button>{" "}
                  <span className="divider">|</span> Automatic search
                </span>
                <button
                  type="button"
                  title="Choose provider and model"
                  onClick={() => setView("Settings")}
                >
                  {ai.model || "Choose AI model"}
                </button>
                <label>
                  Sources{" "}
                  <select
                    aria-label="Source count"
                    value={limit}
                    onChange={(e) => setLimit(Number(e.target.value))}
                  >
                    {[3, 6, 8, 12, 20, 30].map((n) => (
                      <option key={n}>{n}</option>
                    ))}
                  </select>
                </label>
                <button
                  className="send"
                  aria-label="Search papers"
                  disabled={busy || !question.trim()}
                >
                  {busy ? <span className="spinner" /> : <ArrowUp size={18} />}
                </button>
              </div>
            </form>
            <p>
              Evidence first. Always verify context, methods and conclusions in
              the original paper.
            </p>
          </footer>
        )}
      </main>
      {right && (
        <aside className="references">
          <div className="reference-header">
            <span>
              <BookOpen size={17} /> Reference desk
            </span>
            <button
              aria-label="Close references"
              onClick={() => setRight(false)}
            >
              <X size={17} />
            </button>
          </div>
          {selected ? (
            <div className="reference-scroll">
              {detailError && (
                <p role="alert" className="error">
                  {detailError}
                </p>
              )}
              {!detail && !detailError && (
                <p role="status">Loading reference…</p>
              )}
              {detail && (
                <>
                  <div className="eyebrow">SOURCE · PAGE {selected.page}</div>
                  <h2>{detail.title}</h2>
                  <p className="muted">
                    {detail.authors || "Authors unavailable"} · {detail.pages}{" "}
                    pages
                  </p>
                  <div className="provenance">{detail.metadata_provenance}</div>
                  <p className="muted">
                    {detail.bibliography?.journal || "Journal unavailable"} ·{" "}
                    {detail.bibliography?.year || "Year unavailable"}
                  </p>
                  <p className="muted">
                    DOI: {detail.bibliography?.doi || "Unavailable"}
                  </p>
                  <p className="muted">
                    {detail.bibliography?.categories?.join(" · ")}
                  </p>
                  <h4>Abstract</h4>
                  <p className="muted">
                    {detail.abstract ||
                      "Unavailable. No validated abstract has been extracted."}
                  </p>
                  {detail.bibliography?.text_origin === "ocr" && (
                    <p className="error">
                      OCR-extracted text: verify numbers, units and equations
                      against the original page.
                    </p>
                  )}
                  <h4>
                    Supporting passage <span>p. {selected.page}</span>
                  </h4>
                  <blockquote>
                    {selected.excerpt ||
                      detail.excerpt ||
                      "No indexed passage for this page."}
                  </blockquote>
                  <p className="muted small">
                    Exact indexed text. Extraction may contain layout or OCR
                    errors. Scientific support has not been assessed.
                  </p>
                  <div className="pdf-actions">
                    <button
                      className="primary"
                      disabled={!detail.available}
                      onClick={() => setPdf(!pdf)}
                    >
                      <FileText size={15} />
                      {pdf ? "Hide PDF" : "Read original PDF"}
                    </button>
                    {detail.available && (
                      <a
                        aria-label="Open PDF in new tab"
                        href={`/api/documents/${detail.id}/pdf#page=${selected.page}`}
                        target="_blank"
                        rel="noreferrer"
                      >
                        <ExternalLink size={17} />
                      </a>
                    )}
                  </div>
                  {!detail.available && (
                    <p className="error">
                      Original PDF unavailable in configured library.
                    </p>
                  )}
                  {pdf && (
                    <Suspense
                      fallback={<p role="status">Loading PDF viewer…</p>}
                    >
                      <Pdf
                        id={detail.id}
                        initialPage={selected.page}
                        pages={detail.pages}
                      />
                    </Suspense>
                  )}
                </>
              )}
            </div>
          ) : (
            <div className="reference-empty">
              <div className="paper-illustration">
                <FileText size={34} />
                <span>
                  <Search size={19} />
                </span>
              </div>
              <h3>Follow the evidence.</h3>
              <p>
                Select a paper or citation to inspect its metadata, exact
                passage and original PDF.
              </p>
              <div className="reference-steps">
                <span>
                  01 <strong>Explore a source</strong>
                </span>
                <span>
                  02 <strong>Read the passage</strong>
                </span>
                <span>
                  03 <strong>Check the original</strong>
                </span>
              </div>
              <div className="privacy">
                <ShieldCheck size={17} />
                <span>
                  Your papers stay on this device.
                  <br />
                  {ai.enabled
                    ? `Selected excerpts go to ${ai.provider}.`
                    : "Cloud AI is disabled."}
                </span>
              </div>
            </div>
          )}
        </aside>
      )}
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
