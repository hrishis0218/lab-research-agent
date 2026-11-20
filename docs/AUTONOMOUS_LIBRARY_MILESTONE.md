# Next milestone: autonomous paper library and AI answers

## User requirements / authority (20 November 2026)

The user has explicitly authorised the application to **automatically rename and organise PDFs in the configured research library without seeking per-file confirmation**. This includes moving files into a sensible managed folder hierarchy within the selected library. This authorisation does **not** include deletion of originals, overwriting or replacing a file, destructive database resets, cloud uploads of confidential full-text documents, activating paid provider APIs without setup, or pushing private files to public GitHub.

Implement automatic file operations conservatively and reversibly. The normal user interaction is **Add PDFs -> Ask questions -> See supported answer and source PDF**. Expose advanced operations and logs only when needed; never require an "Index" button.

## Verified baseline

As documented in `docs/V1_IMPLEMENTATION_PLAN.md`, the React workspace currently exposes a **read-only** `backend/library.py` adapter that returns 262 indexed records, whereas a live file scan found 416 available PDFs, 239 unindexed files and 85 stale paths. These numbers overlap; 262 is not a subset of 416 because some indexed paths are stale. The metadata detail endpoint currently sets DOI/abstract to None; the chat offers local keyword snippets, not LLM answers. The first milestone must remove these limitations.

## Milestone A: automatic background intake and index reconciliation

1. Preserve existing `data/library.sqlite3` and 14,453 existing embeddings. Create a verified backup before any live database migration. Use migration tests and recovery procedures.
2. Implement a durable ingestion/jobs service (SQLite job records or robust work queue) with resumability and retries; run it with FastAPI as a controlled background worker. Avoid expensive scans on every HTTP request.
3. Provide a persistent, configured library root and automatic file discovery on app startup, low-frequency file watcher, and periodic reconciliation. Wait until copied PDFs stop changing before processing. Offer simple drag-and-drop import as an additional route. The user should not manually initiate indexing.
4. Perform a fast inventory/hash/metadata stage first, then do incremental passage extraction and embeddings asynchronously. Display `Preparing 17 papers` and `Library ready`, not raw SQLite counts. Search existing ready papers while new papers are processing.
5. Reconcile old indexed paths to discovered files using hashes **and evidence from document contents**, not filename alone. Preserve embedding rows for unchanged contents. Identify stale records without automatically deleting them.
6. For every PDF, maintain state `discovered -> identified -> organised -> text_ready -> search_ready` or `needs_attention / failed`. All discovered PDFs must appear in the library immediately, even if parsing or semantic processing fails. Failures must not block other files.
7. Make indexing idempotent with restart/resume and test for 416-on-disk vs 262-old-index scenario, including 85 stale records, path moves, duplicates and interruptions.
8. Database/job/filesystem writes must use compatible transactions and durable logs, not assume a filename update is harmless.

## Milestone B: automatic scientific bibliographic metadata, renaming and classification

1. Read PyMuPDF title candidates, DOI candidates, authors, abstract, page count, and document type. Use the existing `backend/documents/audit.py` and `crossref.py` as starting points; improve multiline titles and title validation.
2. Fetch Crossref by DOI; if DOI is absent, use controlled title/author lookup, then an additional credible scholarly metadata source (e.g. OpenAlex) where permitted. Books/theses/preprints need separate handling. Do not assign a DOI found in the bibliography to the paper.
3. Store field-level provenance, retrieval status, confidence and user-edited overrides. Missing metadata should be clearly labelled, not fabricated. Metadata extraction must be useful even if no cloud AI key is configured.
4. Assign stable publication identities, distinct file/attachment identities and SHA-256s. Recognise exact duplicates and multiple versions of one paper. Retrieval must avoid counting bibliographic duplicates as independent support.
5. Auto-rename validated attachments using `Year_FirstAuthor_ShortTitle.pdf` (sanitise Windows characters; hash/sequence suffix for collisions). Group physical files conservatively by `Articles/Year`, `Reviews`, `Books`, `Theses`, `Reports`, `Needs_Review`; use multiple **virtual scientific categories/tags** for materials, processes, techniques and applications. Do not create physical duplicate copies for different tags.
6. **No per-file approval is needed** for normal auto-renaming/organising within the managed library; this is the user's explicit choice. Preserve a machine-readable operation journal, pre/post file hashes, collision protection, link-aware index updates and one-click undo/restore. Never overwrite/delete originals. If identity is genuinely uncertain, use an unambiguous provisional filename or keep its old name in `Needs_Review` rather than inventing metadata.
7. On moves/renames, rebind citations/path references with permanent document IDs and avoid re-embedding unchanged content. Test Windows file locks, interrupted renames, filename collisions, duplicate titles, Unicode names and rollback.
8. Previously indexed sources must still open at the correct PDF page after organisation.

## Milestone C: cloud AI user controls and scientific answers

1. Add an obvious `AI On / Retrieval Only` toggle in the chat composer and a provider/model selector for Gemini and OpenAI initially. Expand to Claude/DeepSeek after verifying current APIs. No fictitious model IDs.
2. Persist keys in Windows Credential Manager via existing `backend/credentials.py` keyring adapter. No repeated entry; no plaintext storage, browser exposure or logs.
3. When AI is on, conduct hybrid search over ready documents; build a grounded context and answer the question with citation IDs linked to source keys/page/excerpt. Users should click a citation and see title, authors, year, DOI, journal, abstract, exact cited passage, page and full PDF in the right pane.
4. Display when the question is being answered from an incomplete library, distinguish retrieved quotations from generated interpretations, and do not claim independent scientific validation just because source IDs exist.
5. Cloud provider calls must use user-configured credentials and an explicit, persistent AI toggle. Do not auto-enable paid usage or send confidential unpublished text without consent; user consent can be configured as a one-time setting rather than requested for every question.
6. Retrieval Only must remain fully functional with no internet or external API key. Handle provider errors without losing the query.

## Delivery acceptance tests (run, don't merely promise)

- Import or watch a folder of synthetic+public PDFs, including a 416-versus-262 fixture: every discovered PDF appears immediately; missing ones process in background; previously indexed embeddings remain; no hidden failures.
- Auto-identify and rename a verified journal article without a per-file dialog. Verify filename, classification, new path, working cited PDF link and successful rollback.
- Refuse to overwrite existing files; handle collisions, truncated title, absent DOI, a DOI in references, book, thesis, invalid PDF and different versions of the same paper.
- Show journal, title, authors, DOI, abstract, techniques/topics and full PDF on the source pane; mark absent fields explicitly.
- Select Gemini/OpenAI in the React UI, save a dummy key with a mocked keyring, restart and confirm key persistence; run mocked AI answer with exact page citations. No network required for CI.
- Visually test end-to-end React workflow, run Python tests, TS build and browser tests. Report live local verification separately from fixture tests.
- Maintain `docs/V1_IMPLEMENTATION_PLAN.md`, keep Streamlit fallback intact, and deliver integrated milestones without requesting manual indexing commands.

## Engineering performance

On CPU/8 GB, metadata identification is comparatively lightweight; high-quality text extraction and especially creating embeddings across thousands of passages are slower. **Do not block metadata/renaming on embeddings**. Queue work by priority (recent papers first), batch embeddings, cache by file/content fingerprint, bound memory and concurrency. The UI should remain responsive even when background ingestion is active.

The database and filesystem must remain consistent across crashes/restarts. If automatic rename cannot be completed safely for one file, log it as `needs_attention` and continue processing other documents. Do not interpret user's auto-rename authorisation as permission for irreversible or unsafe operations.
