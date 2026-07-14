import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv
import streamlit as st

from utils.api_client import chat_stream, delete_document, list_documents, upload_document
from utils.ui_helpers import render_citations, render_downloads

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

st.set_page_config(page_title="AI Research Assistant", page_icon="🧠", layout="wide")

TITLE_MAX_LEN = 40


def _new_conversation() -> str:
    thread_id = uuid.uuid4().hex
    st.session_state.conversations[thread_id] = {"title": "New conversation", "messages": []}
    return thread_id


if "conversations" not in st.session_state:
    st.session_state.conversations = {}
if st.session_state.get("active_thread_id") not in st.session_state.conversations:
    st.session_state.active_thread_id = _new_conversation()

with st.sidebar:
    st.header("💬 Conversations")
    if st.button("➕ New conversation", use_container_width=True):
        st.session_state.active_thread_id = _new_conversation()
        st.rerun()
    st.divider()
    for thread_id, convo in reversed(list(st.session_state.conversations.items())):
        is_active = thread_id == st.session_state.active_thread_id
        label = ("🟢 " if is_active else "") + convo["title"]
        if st.button(label, key=f"convo-{thread_id}", use_container_width=True):
            st.session_state.active_thread_id = thread_id
            st.rerun()
    st.caption("Conversations last for this browser session — they reset if the app restarts.")

active = st.session_state.conversations[st.session_state.active_thread_id]

st.title("🧠 AI Research Assistant")
st.caption(
    "Ask a question, paste a URL, or ask for a report/presentation — all in one place. "
    "The planner figures out which agent(s) to use: a document agent, a web agent, a URL agent, "
    "a report agent, or a presentation agent."
)

with st.expander("📎 Upload a document (PDF, DOCX, TXT, PPTX)"):
    col1, col2 = st.columns([3, 1])
    uploaded = col1.file_uploader("File", type=["pdf", "docx", "txt", "pptx"], label_visibility="collapsed")
    if col2.button("Ingest", type="primary", disabled=uploaded is None, use_container_width=True):
        with st.spinner(f"Processing {uploaded.name}..."):
            try:
                result = upload_document(uploaded.getvalue(), uploaded.name)
                st.success(f"Ingested **{result['filename']}** into {result['num_chunks']} chunks.")
            except Exception as exc:
                st.error(f"Upload failed: {exc}")

    try:
        docs = list_documents()
    except Exception:
        docs = []
        st.warning("⚠️ Can't reach the backend — make sure `uvicorn` is running on port 8000.")
    if docs:
        st.caption(f"{len(docs)} document(s) in your library:")
        for doc in docs:
            cols = st.columns([4, 2, 2, 1])
            cols[0].write(doc["filename"])
            cols[1].write(doc["doc_type"])
            cols[2].write(f"{doc['num_chunks']} chunks")
            if cols[3].button("🗑️", key=f"del-{doc['doc_id']}"):
                delete_document(doc["doc_id"])
                st.rerun()

for message in active["messages"]:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        render_citations(message.get("citations", []))
        render_downloads(message.get("files") or {}, key_prefix=message["id"])

query = st.chat_input(
    "Ask about your documents, paste a URL, search the web, or ask for a report/presentation..."
)
if query:
    if not active["messages"]:
        active["title"] = query[:TITLE_MAX_LEN] + ("…" if len(query) > TITLE_MAX_LEN else "")
    active["messages"].append({"id": uuid.uuid4().hex, "role": "user", "content": query})
    with st.chat_message("user"):
        st.markdown(query)

    result_holder: dict = {}

    def _stream():
        try:
            for event in chat_stream(query, st.session_state.active_thread_id):
                if event["type"] == "token":
                    yield event["content"]
                elif event["type"] == "error":
                    result_holder["error"] = event.get("message", "Something went wrong.")
                else:
                    result_holder.update(event)
        except Exception as exc:
            result_holder["error"] = (
                f"Couldn't reach the backend ({exc}). Make sure `uvicorn` is running on port 8000."
            )

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            streamed_answer = st.write_stream(_stream())
        if result_holder.get("error"):
            st.error(result_holder["error"])
            answer = f"⚠️ {result_holder['error']}"
        else:
            answer = streamed_answer or result_holder.get("answer", "")
            if not streamed_answer and answer:
                st.markdown(answer)
        render_citations(result_holder.get("citations", []))

        files = {
            "markdown_path": result_holder.get("markdown_path"),
            "docx_path": result_holder.get("docx_path"),
            "pdf_path": result_holder.get("pdf_path"),
            "pptx_path": result_holder.get("pptx_path"),
        }
        message_id = uuid.uuid4().hex
        render_downloads(files, key_prefix=message_id)

    active["messages"].append(
        {
            "id": message_id,
            "role": "assistant",
            "content": answer,
            "citations": result_holder.get("citations", []),
            "files": files,
        }
    )
    st.rerun()
