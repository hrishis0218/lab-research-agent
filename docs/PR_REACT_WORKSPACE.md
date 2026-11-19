# Draft PR: React scientific workspace with read-only FastAPI integration

Base: `feature/ui-index-credentials`
Head: `codex/react-workspace`

The v1 branch previously had no frontend and only a health endpoint. This milestone adds a locally served React/TypeScript research workspace connected to the existing passage index, with keyword evidence retrieval, searchable indexed library, exact excerpt/page citations and an in-pane PDF.js viewer. It reports disk/index/stale-path populations separately and exports evidence CSV without presenting retrieved text as verified scientific conclusions.

The legacy Streamlit source and live SQLite schema/embeddings remain untouched. PDF serving resolves document IDs within the configured library root. No cloud calls, key collection, migrations or source-file changes are introduced. Providers, persistent chat, indexing jobs, hybrid search and document identity/rename workflows remain later milestones.

Validation: 20 Python tests, strict TypeScript/Vite build and 3 Chromium workflows (1366/1920 desktop, mobile failure handling) pass. Screenshots were visually inspected, including actual synthetic PDF painting; Windows worker MIME handling has regression coverage. npm audit reports zero vulnerabilities. The live DB hash is unchanged and quick_check passes. Fixtures/screenshots contain synthetic content only. See docs/V1_IMPLEMENTATION_PLAN.md and docs/REACT_DEVELOPMENT.md.
