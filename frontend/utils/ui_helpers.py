import streamlit as st


def render_citations(citations: list[dict]) -> None:
    if not citations:
        return
    with st.expander(f"📎 {len(citations)} citation(s)"):
        for c in citations:
            if c.get("url"):
                st.markdown(f"- [{c.get('source', c['url'])}]({c['url']})")
            else:
                page = f" (p. {c['page']})" if c.get("page") else ""
                st.markdown(f"- **{c.get('source', 'Unknown')}**{page}: _{c.get('snippet', '')}_")


def download_file_button(label: str, path: str, mime: str, key: str) -> None:
    try:
        with open(path, "rb") as f:
            st.download_button(label, f.read(), file_name=path.split("/")[-1], mime=mime, key=key)
    except FileNotFoundError:
        st.error(f"File not found on server: {path}")


_FILE_KINDS = [
    ("markdown_path", "⬇️ .md", "text/markdown"),
    ("docx_path", "⬇️ .docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ("pdf_path", "⬇️ .pdf", "application/pdf"),
    ("pptx_path", "⬇️ .pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
]


def render_downloads(files: dict, key_prefix: str) -> None:
    present = [(field, label, mime) for field, label, mime in _FILE_KINDS if files.get(field)]
    if not present:
        return
    columns = st.columns(len(present))
    for column, (field, label, mime) in zip(columns, present):
        with column:
            download_file_button(label, files[field], mime, f"{key_prefix}-{field}")
