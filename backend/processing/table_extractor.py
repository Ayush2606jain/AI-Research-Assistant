from typing import Optional

import pdfplumber


def extract_tables_as_markdown(pdf_path: str) -> list[dict]:
    """Extract tables from a PDF, one entry per table, as Markdown strings.

    Returns a list of {"page": int, "markdown": str} dicts so callers can
    merge these back in as their own chunks alongside the regular page text.
    """
    tables: list[dict] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                if not table or len(table) < 2:
                    continue
                markdown = _table_to_markdown(table)
                if markdown:
                    tables.append({"page": page_number, "markdown": markdown})
    return tables


def _table_to_markdown(rows: list[list[Optional[str]]]) -> str:
    cleaned = [[cell.strip() if cell else "" for cell in row] for row in rows]
    header, *body = cleaned
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * len(header)) + " |",
    ]
    for row in body:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)
