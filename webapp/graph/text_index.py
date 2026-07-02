"""Extract free-form text from P&ID PDFs (notes, holds, annotations).

Saves page_text.json in the job output directory:
  {"pages": [{"page_index": 0, "sheet": 1, "text": "..."}]}

Uses PyMuPDF (already in requirements.txt) for fast text-layer extraction.
Falls back gracefully if the PDF has no text layer (scanned drawings).
"""
import json
import os
from typing import List, Dict


def extract_and_save(job_dir: str) -> int:
    """Extract text from input.pdf, save page_text.json. Returns page count."""
    import fitz  # PyMuPDF

    pdf_path = os.path.join(job_dir, "input.pdf")
    if not os.path.exists(pdf_path):
        return 0

    pages: List[Dict] = []
    doc = fitz.open(pdf_path)
    for i, page in enumerate(doc):
        text = page.get_text("text") or ""
        pages.append({"page_index": i, "sheet": i + 1, "text": text})
    doc.close()

    out_path = os.path.join(job_dir, "page_text.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"pages": pages}, f, ensure_ascii=False)

    return len(pages)


def search(job_dir: str, query: str, max_results: int = 20) -> List[Dict]:
    """Search page_text.json for query. Returns list of {page_index, sheet, snippet}."""
    out_path = os.path.join(job_dir, "page_text.json")
    if not os.path.exists(out_path):
        return []

    with open(out_path, encoding="utf-8") as f:
        data = json.load(f)

    q = query.lower()
    results = []
    for page in data.get("pages", []):
        text = page.get("text", "")
        if not text or q not in text.lower():
            continue
        # Find all occurrences and pick the first snippet
        idx = text.lower().index(q)
        start = max(0, idx - 80)
        end = min(len(text), idx + len(query) + 80)
        raw = text[start:end].replace("\n", " ").strip()
        snippet = ("…" if start > 0 else "") + raw + ("…" if end < len(text) else "")
        results.append({
            "page_index": page["page_index"],
            "sheet": page["sheet"],
            "snippet": snippet,
        })
        if len(results) >= max_results:
            break

    return results
