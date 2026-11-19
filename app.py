"""Lab Research Agent Phase 2.4: collapsible settings / conversation / source explorer."""
from __future__ import annotations
import os
from pathlib import Path
import fitz
import streamlit as st
from core import connect
from retrieval import ensure_schema, index_semantic, retrieve
from answer import ask_openai
from gemini_answer import ask_gemini
from source_viewer import local_pdf_server, read_metadata
from evidence import citation_audit, review_with_gemini
from backend.credentials import get_key, save_key, delete_key

st.set_page_config(page_title='Lab Research Agent', page_icon='🔬', layout='wide', initial_sidebar_state='collapsed')
st.markdown('''<style>
.block-container{max-width:100%;padding:1rem 1.1rem 3rem}
[data-testid="stChatMessage"]{padding:.7rem}
[data-testid="stChatInput"]{max-width:100%}
</style>''', unsafe_allow_html=True)

for key, default in [('dialogue', []), ('selected_source', None), ('source_view', 'metadata'),
                     ('show_settings', True), ('show_source', True), ('pdf_page', 1)]:
    if key not in st.session_state:
        st.session_state[key] = default

st.title('🔬 Lab Research Agent')
st.caption('Phase 2.4 · Scientific evidence workspace')
controls = st.columns([0.55, 5.4, 0.55])
with controls[0]:
    if st.button('☰' if not st.session_state.show_settings else '◀', help='Toggle library and settings', key='settings_toggle'):
        st.session_state.show_settings = not st.session_state.show_settings
        st.rerun()
with controls[2]:
    if st.button('▶' if not st.session_state.show_source else '✕', help='Toggle reference explorer', key='source_toggle'):
        st.session_state.show_source = not st.session_state.show_source
        st.rerun()

weights = ([1.0] if st.session_state.show_settings else []) + [2.7] + ([1.45] if st.session_state.show_source else [])
cols = st.columns(weights, gap='medium')
idx = 0
settings_col = cols[idx] if st.session_state.show_settings else None
idx += int(st.session_state.show_settings)
conversation_col = cols[idx]
idx += 1
source_col = cols[idx] if st.session_state.show_source else None

with connect() as db:
    ensure_schema(db)
    docs = db.execute('SELECT COUNT(*) FROM chunk_documents').fetchone()[0]
    chunks = db.execute('SELECT COUNT(*) FROM chunks').fetchone()[0]
    embedded = db.execute('SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL').fetchone()[0]

    # Keep provider controls alive even when settings are collapsed.
    if 'provider' not in st.session_state:
        st.session_state.provider = st.session_state.get('_saved_provider', 'Gemini (free-tier eligible)')
    if 'semantic_search' not in st.session_state:
        st.session_state.semantic_search = st.session_state.get('_saved_semantic_search', True)
    if 'gemini_model' not in st.session_state:
        st.session_state.gemini_model = st.session_state.get('_saved_gemini_model', 'gemini-3.8-flash')
    if 'openai_model' not in st.session_state:
        st.session_state.openai_model = st.session_state.get('_saved_openai_model', 'gpt-4.1-mini')
    if 'gemini_api_key' not in st.session_state:
        st.session_state.gemini_api_key = st.session_state.get('_saved_gemini_api_key', '')
    if 'openai_api_key' not in st.session_state:
        st.session_state.openai_api_key = st.session_state.get('_saved_openai_api_key', '')

    if 'source_count' not in st.session_state:
        st.session_state.source_count = 8

    if settings_col is not None:
        with settings_col:
            st.subheader('Library & settings')
            a, b = st.columns(2)
            a.metric('PDFs', docs)
            b.metric('Passages', chunks)
            st.caption(f'Embeddings {embedded}/{chunks}')
            st.selectbox('Answer mode', ['Retrieval only', 'Gemini (free-tier eligible)', 'OpenAI (paid API)'], key='provider')
            if st.session_state.provider in ('Gemini (free-tier eligible)', 'OpenAI (paid API)'):
                credential_provider = 'Gemini' if st.session_state.provider.startswith('Gemini') else 'OpenAI'
                try:
                    stored = bool(get_key(credential_provider))
                except RuntimeError as exc:
                    stored = False
                    st.warning(str(exc))
                st.caption('API key stored in Windows Credential Manager' if stored else 'No saved key for this provider')
                input_name = 'gemini_api_key' if credential_provider == 'Gemini' else 'openai_api_key'
                st.text_input('New API key (optional)', type='password', key=input_name,
                              help='Use Save key once; the value is never committed to Git.')
                save_col, delete_col = st.columns(2)
                with save_col:
                    if st.button('Save key', key='save_' + credential_provider, use_container_width=True):
                        try:
                            save_key(credential_provider, st.session_state[input_name])
                            st.success('Saved in Windows Credential Manager. You can clear the input field after the next page reload.')
                        except (RuntimeError, ValueError) as exc:
                            st.error(str(exc))
                with delete_col:
                    if st.button('Forget key', key='forget_' + credential_provider, use_container_width=True):
                        try:
                            delete_key(credential_provider)
                            st.success('Stored key removed. Clear any key still entered in the input field.')
                        except (RuntimeError, ValueError) as exc:
                            st.error(str(exc))
                if credential_provider == 'Gemini':
                    st.text_input('Gemini model', key='gemini_model')
                else:
                    st.text_input('OpenAI model', key='openai_model')
            st.checkbox('Semantic search', key='semantic_search', disabled=not bool(embedded))
            st.slider('Number of source passages', min_value=3, max_value=25,
                      step=1, key='source_count', help='More passages can increase cloud API token usage.')
            with st.expander('Library indexing'):
                folder = st.text_input('PDF folder',
                                       value=r'C:\Users\petar\Desktop\all pdf papers',
                                       help='Audit reports do not index PDFs. Choose the complete library and index it here.')
                if st.button('Count PDFs in selected folder', use_container_width=True):
                    target = Path(folder).expanduser()
                    if target.is_dir():
                        disk_count = sum(1 for p in target.rglob('*') if p.is_file() and p.suffix.lower() == '.pdf')
                        st.info(f'{disk_count} PDFs on disk; {docs} PDF paths currently in the search index.')
                    else:
                        st.warning('Folder does not exist on this computer.')
                semantic_index = st.checkbox('Create embeddings for new PDFs', value=True)
                if st.button('Index / update PDFs', type='primary', use_container_width=True):
                    try:
                        with st.spinner('Indexing local PDFs…'):
                            result = index_semantic(folder, db, semantic_index)
                        fresh_count = db.execute('SELECT COUNT(*) FROM chunk_documents').fetchone()[0]
                        st.success(f"Added/updated {result['indexed']} · unchanged {result['unchanged']} · total indexed {fresh_count}")
                        if result.get('errors'):
                            st.error(f"{len(result['errors'])} files had indexing errors. Review the warnings below.")
                        for error in result.get('errors', [])[:30]:
                            st.warning(error)
                    except Exception as exc:
                        st.error(str(exc))
            if st.button('Clear conversation', use_container_width=True):
                st.session_state.dialogue = []
                st.session_state.selected_source = None
                st.rerun()
            st.caption('PDFs/index remain local. Cloud answers and evidence reviews send selected excerpts to the provider.')
            for key in ('provider','semantic_search','gemini_model','openai_model','gemini_api_key','openai_api_key'):
                st.session_state['_saved_' + key] = st.session_state[key]

    if source_col is not None:
        with source_col:
            st.subheader('Source explorer')
            selected = st.session_state.selected_source
            if selected is None:
                st.info('Select a citation below an answer. Paper metadata appears here first, followed by the PDF on request.')
            else:
                path = Path(selected['path'])
                st.caption(f"[{selected['citation']}] · PDF page {selected['page']}")
                st.markdown(f"**{selected['title']}**")
                if not path.is_file():
                    st.error('Original PDF is missing at its indexed location.')
                else:
                    try:
                        metadata = read_metadata(str(path), path.stat().st_mtime_ns)
                    except Exception as exc:
                        metadata = {'abstract': None, 'pages': 0}
                        st.warning(f'Metadata unavailable: {exc}')
                    row = db.execute('SELECT id FROM chunk_documents WHERE path=?', (str(path),)).fetchone()
                    url = local_pdf_server().url(row['id'], selected['page']) if row else None
                    actions = st.columns(2)
                    with actions[0]:
                        if st.button('Paper details', use_container_width=True):
                            st.session_state.source_view = 'metadata'
                            st.rerun()
                    with actions[1]:
                        if st.button('Read PDF here', use_container_width=True):
                            st.session_state.source_view = 'pdf'
                            st.session_state.pdf_page = int(selected['page'])
                            st.rerun()
                    if url:
                        st.link_button('Open PDF in new tab ↗', url, use_container_width=True)
                    st.divider()
                    if st.session_state.source_view == 'metadata':
                        for label, key in [('Authors', 'author'), ('Subject', 'subject')]:
                            if metadata.get(key):
                                st.caption(label)
                                st.write(metadata[key])
                        st.caption(f"Total pages: {metadata.get('pages','?')}")
                        st.markdown('**Abstract**')
                        if metadata.get('abstract'):
                            st.write(metadata['abstract'])
                        else:
                            st.info('Abstract not reliably extracted. Open the PDF to read it.')
                        with st.expander('Retrieved passage', expanded=True):
                            st.write(selected['content'])
                        st.caption(path.name)
                    else:
                        # Render a real PDF page as PNG so in-pane viewing works even if
                        # browsers refuse to embed a cross-origin local PDF server.
                        try:
                            with fitz.open(path) as pdf:
                                total = len(pdf)
                                page = min(max(1, st.session_state.pdf_page), total)
                                st.session_state.pdf_page = page
                                previous, indicator, following = st.columns([1, 2, 1])
                                with previous:
                                    if st.button('◀ Previous', disabled=page <= 1, use_container_width=True):
                                        st.session_state.pdf_page = page - 1
                                        st.rerun()
                                with indicator:
                                    st.caption(f'Page {page} / {total}')
                                with following:
                                    if st.button('Next ▶', disabled=page >= total, use_container_width=True):
                                        st.session_state.pdf_page = page + 1
                                        st.rerun()
                                pix = pdf[page - 1].get_pixmap(matrix=fitz.Matrix(1.4, 1.4), alpha=False)
                                st.image(pix.tobytes('png'), use_container_width=True)
                        except Exception as exc:
                            st.error(f'PDF preview unavailable: {exc}')

    with conversation_col:
        st.subheader('Research conversation')
        for ti, turn in enumerate(st.session_state.dialogue):
            with st.chat_message('user'):
                st.write(turn['question'])
            with st.chat_message('assistant'):
                st.markdown(turn['answer'])
                sources = turn['sources']
                if sources:
                    audit = citation_audit(turn['answer'], sources)
                    with st.expander('Citation check (identifiers only)', expanded=False):
                        st.write(f"Cited sources: {', '.join('[' + s + ']' for s in audit['cited']) or 'none'}")
                        if audit['unknown']:
                            st.error(f"Unknown references: {', '.join(audit['unknown'])}")
                        else:
                            st.caption('No invalid source identifiers detected. This does NOT verify scientific support.')
                    st.markdown('**Sources — select to inspect on the right**')
                    with st.expander(f'Show {len(sources)} sources', expanded=False):
                        for s in sources:
                            if st.button(f"[{s['citation']}] {s['title']} · p. {s['page']}", key=f'pick_{ti}_{s["id"]}', use_container_width=True):
                                st.session_state.selected_source = s
                                st.session_state.source_view = 'metadata'
                                st.session_state.show_source = True
                                st.rerun()
                    st.markdown('**Scientific evidence review**')
                    st.caption('Optional second Gemini request. Model-assessed claims, not independent fact-checking. Exact supporting quotations are checked against retrieved passages.')
                    if turn.get('review'):
                        for c in turn['review']:
                            st.markdown(f"**{c['verdict'].upper()}** — {c['claim']}")
                            st.caption(c['reason'])
                            if c['quote_verified']:
                                st.write(f"Verified excerpt [{c['source_id']}]: “{c['quote']}”")
                            else:
                                st.caption('No exact supporting quotation verified in retrieved excerpts.')
                    if st.button('Review claims against excerpts (Gemini)', key=f'review_{ti}'):
                        key = st.session_state.gemini_api_key or get_key('Gemini') or os.environ.get('GEMINI_API_KEY', '')
                        try:
                            with st.spinner('Assessing claims against retrieved passages…'):
                                turn['review'] = review_with_gemini(turn['question'], turn['answer'], sources,
                                                                  key, st.session_state.gemini_model)
                            st.rerun()
                        except Exception as exc:
                            st.error(f'Evidence review failed: {exc}')
        question = st.chat_input('Ask about your research papers…')
        if question:
            try:
                with st.spinner('Retrieving source passages…'):
                    sources = retrieve(question, db, limit=st.session_state.source_count, semantic=st.session_state.semantic_search and bool(embedded))
                history = [('user', item['question']) for item in st.session_state.dialogue[-3:]]
                provider = st.session_state.provider
                if provider == 'Gemini (free-tier eligible)' and sources:
                    key = st.session_state.gemini_api_key or get_key('Gemini') or os.environ.get('GEMINI_API_KEY', '')
                    with st.spinner('Generating Gemini answer…'):
                        answer = ask_gemini(question, sources, key, st.session_state.gemini_model, history)
                elif provider == 'OpenAI (paid API)' and sources:
                    key = st.session_state.openai_api_key or get_key('OpenAI') or os.environ.get('OPENAI_API_KEY', '')
                    with st.spinner('Generating OpenAI answer…'):
                        answer = ask_openai(question, sources, key, st.session_state.openai_model, history)
                else:
                    answer = ('**Retrieval-only:** Inspect the retrieved passages in the Sources panel.' if sources else
                              'No passages retrieved; try a different question or index more papers.')
                st.session_state.dialogue.append({'question': question, 'answer': answer, 'sources': sources, 'review': None})
                st.rerun()
            except Exception as exc:
                st.error(f'Could not answer: {exc}')
