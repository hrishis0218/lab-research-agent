# Codex repository instructions — Lab Research Agent

This file applies to the entire repository. Read `docs/V1_PRODUCT_SPEC.md` before making substantial changes.

## Mission
Ship a cohesive, maintainable React + TypeScript frontend backed by FastAPI for local-first scientific PDF research on Windows 8 GB RAM. This is a **v1 rebuild**, not another cosmetic Streamlit patch. Keep the existing Phase 2.4 Streamlit application available as a fallback.

## Workflow
1. Begin by inspecting current source, tests, Git status/branch and `docs/V1_PRODUCT_SPEC.md`.
2. Use a dedicated feature branch off the latest v1 development branch. Never force-push, overwrite history or merge to `main` unapproved.
3. Maintain an executable milestone plan in `docs/V1_IMPLEMENTATION_PLAN.md` with status, acceptance criteria, blockers and test results. Update it as work progresses; do not stop after planning.
4. Implement an entire coherent milestone with integration, tests, visual QA and documentation. Avoid repetitive one-file-only edits and asking the user to manually copy commands.
5. Run Python unit/integration tests, TypeScript typechecks/build, and browser tests where available. If tools, network, PDF collection or GUI access are missing, note the limitation and continue with deterministic test fixtures.
6. Summarise changes, screenshots (when available), automated test results, and remaining issues concisely after milestones. Prefer a reviewable PR.

## Protect the lab's data
- The user has explicitly authorised automatic, reversible PDF **renaming and organisation** within the configured library, without per-file confirmation. Follow `docs/AUTONOMOUS_LIBRARY_MILESTONE.md`: no overwriting/deleting originals, no unchecked collisions, journal every move and preserve citations.
- Existing PDF/embedding index is under `data/`; never clear/rebuild/overwrite it without a verified backup and explicit approval for data migration.
- Keep PDFs, database files, local embedding caches, and API keys out of Git. GitHub repository visibility is public. Scan staged changes before commits.
- Do not send unpublished/confidential research text to any external API without permission. Provider/model selection must visibly show cloud processing.
- Never invent scientific citations/DOIs/authors/pages or assume the reported 416 PDFs are identical to the 262 currently indexed paths.
- Credentials must use Windows Credential Manager/keyring (or another secure OS store), not source files or plaintext configs.

## Engineering expectations
- React + Vite + TypeScript frontend with independently collapsible left navigation and right reference pane; readable centre chat and PDF.js viewer.
- FastAPI backend; preserve compatible local SQLite/FTS5 and current CPU embeddings while migrating behind service interfaces.
- Use TypeScript, Python type hints and Pydantic models. Modular files, clear errors, Windows-compatible scripts, small memory footprint.
- Evaluate actual scientific retrieval quality using hand-labelled questions and citations; a successful API response is not sufficient.
- An LLM checking its own citations is not independent verification. Ground every evidence label in page-level excerpts.
- Support configurable retrieval limits, de-duplicated sources, per-provider API/model selection and persistence, saved conversations and document metadata preview.

## Delegated development objective
Deliver the complete v1 workspace described in `docs/V1_PRODUCT_SPEC.md` through **cohesive, testable milestones**. Start by creating `docs/V1_IMPLEMENTATION_PLAN.md`, then implement M0 and M1 (React/Vite/TypeScript shell + FastAPI API + real PDF pane); after validating those, proceed with M2–M5 as time/resources/access permit without requiring a new user prompt for each ordinary change. Run and visually inspect the browser UI; keep old Streamlit and the existing database untouched. Do not report the overall v1 complete until the acceptance criteria pass. At major checkpoints, report functionality, tests, problems and approvals needed.

Prioritise `docs/AUTONOMOUS_LIBRARY_MILESTONE.md` as the next development milestone. Automatic safe PDF renaming/organisation is now authorised without per-file approval. Ask before destructive Git operations, irreversible deletion, destructive data migration or enabling paid/cloud processing. For ordinary coding, metadata lookup, background processing and reversible filename organisation, proceed independently.
