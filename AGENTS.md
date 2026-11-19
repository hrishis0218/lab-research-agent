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
- Treat the real PDFs at `C:\Users\petar\Desktop\all pdf papers` as **read-only** unless the user explicitly approves a particular rename/move/delete operation.
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

## First delegated task
Create `docs/V1_IMPLEMENTATION_PLAN.md`; implement **M0 + M1** in `docs/V1_PRODUCT_SPEC.md`: safely scaffold React/Vite/TypeScript and FastAPI endpoints, connect them to a working browser UI with a library/sidebar, conversation region and contextual PDF pane; use fixtures if local PDFs unavailable. Include working launch/test scripts. Keep the existing Streamlit version and database untouched. Continue through testing and UI inspection before requesting milestone review.

Ask before destructive Git operations, PDF renames, data migration or enabling paid/cloud processing. For routine coding and test fixes, proceed independently.
