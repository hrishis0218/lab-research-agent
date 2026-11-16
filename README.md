# Lab Research Agent — Phase 2

Local-first scientific PDF research assistant: chunked indexing, hybrid keyword/semantic retrieval, source passages with page numbers, and optional OpenAI answers.

## Windows / Anaconda installation

Open **Anaconda Prompt**:

```bat
conda create -n labagent python=3.12 -y
conda activate labagent
cd /d C:\path\to\lab-research-agent
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Open the local address printed by Streamlit (usually http://localhost:8501). Enter the absolute path to a folder of 10–20 test PDFs and choose **Index / update folder**. Leave **Create local semantic embeddings** selected. The first run downloads the local BGE-small embedding model; it may take a while on an 8 GB laptop.

Ask a question in the chat box. By default, **retrieval-only mode** shows the highest-ranked passages with their source titles and page numbers, without an API call. Expand **Inspect source passages** below the answer.

For AI synthesis, enable **Use OpenAI for answers**, supply an OpenAI API key in the password field, and ask again. The key is held in the Streamlit session, not written to files. Alternatively supply `OPENAI_API_KEY` as an environment variable. The model is configurable; default `gpt-4.1-mini` requires API access and separate usage billing.

## Design

- **Local:** PyMuPDF extracts PDF text page by page; pages become overlapping ~180-word passages. SQLite stores documents, full text, FTS5 keyword index and 384-dimensional BGE-small embeddings. FastEmbed uses CPU ONNX Runtime, without installing a large generative model.
- **Hybrid retrieval:** SQLite FTS5 keyword rank and embedding cosine similarity rank are combined using reciprocal-rank fusion. The top eight source passages are displayed with filename/page number.
- **Cloud:** When explicitly enabled, only your question, limited dialogue context and up to eight retrieved passages are sent to OpenAI. The API receives no PDF files or local database file. OpenAI output is asked to cite `[S1]` etc.; unknown citation identifiers are flagged.
- **Incremental:** Unchanged PDFs are skipped on re-indexing; the model can be added to an existing keyword-only index later. PDF files are read in place and never modified.
- **Storage:** All databases are excluded from version control by `.gitignore`. The old Phase 1 page index is retained; Phase 2 has separate chunk tables. To move between computers, copy the code and re-index the local PDF folder.

## Limitations and safety

- Citations point to actual retrieved passages, but citation **claim verification is not automatic**. Read each supporting passage before using an answer in a manuscript.
- Scanned/image-only PDFs need OCR, not yet included. Figures, equations and complex tables may be missed or misread.
- The embedding model needs internet for its initial download; subsequent local retrieval can run offline. API answering requires internet.
- This prototype scans local vectors linearly; it is appropriate for the first 10–100 PDFs but needs a vector index for efficient querying of 3,000–4,000 PDFs.
- **Do not input confidential or unpublished papers into OpenAI mode without your laboratory's approval.** Prompt and retrieved text are transmitted to the API. ChatGPT Plus does not cover API billing.
- Do not expose the Streamlit app to the laboratory network or the public internet: there is no authentication or per-document authorisation.
- Never commit PDFs, databases, API credentials or unpublished research to GitHub. Check `git status` before pushing.

## Basic tests

```bat
python -m unittest discover -s tests -v
```

Tests exercise indexing and retrieval without downloading a model or using OpenAI. Model/GUI/API integration should be tested locally with your actual PDFs.

## Next

Claim-level citation validation, OCR, figure/table extraction, Zotero metadata, scalable vector search, document permissions and lab deployment.
