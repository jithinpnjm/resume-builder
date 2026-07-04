"""One-time script: extract inline bold segments from the original resume docx
into fixtures/jithin_resume.json.

Deterministic (python-docx runs → segments), never LLM-derived. Matches
document paragraphs to fixture bullets/summary by normalized flattened text,
so fidelity for untouched bullets is exact by construction.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import docx
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

SOURCE = Path(__file__).resolve().parent.parent / "app" / "templates" / "resume_template_source.docx"
FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "jithin_resume.json"


def iter_paragraphs(parent):
    parent_elm = parent.element.body if isinstance(parent, docx.document.Document) else parent._tc
    for child in parent_elm.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, parent)
        elif child.tag == qn("w:tbl"):
            for row in Table(child, parent).rows:
                for cell in row.cells:
                    yield from iter_paragraphs(cell)


def extract_segments(paragraph) -> list[dict]:
    segments: list[dict] = []
    for run in paragraph.runs:
        if not run.text:
            continue
        bold = bool(run.bold)
        if segments and segments[-1]["bold"] == bold:
            segments[-1]["text"] += run.text
        else:
            segments.append({"text": run.text, "bold": bold})
    return segments


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def main() -> None:
    doc = docx.Document(SOURCE)
    by_text: dict[str, list[dict]] = {}
    for p in iter_paragraphs(doc):
        if p.text.strip():
            by_text.setdefault(norm(p.text), extract_segments(p))

    fixture = json.loads(FIXTURE.read_text())

    matched, missed = 0, []

    def attach(obj: dict, key_text: str = "text", key_seg: str = "segments") -> None:
        nonlocal matched
        segs = by_text.get(norm(obj[key_text]))
        if segs:
            obj[key_seg] = segs
            matched += 1
        else:
            missed.append(obj[key_text][:60])

    summary_segs = by_text.get(norm(fixture["summary"]))
    if summary_segs:
        fixture["summary_segments"] = summary_segs
        matched += 1
    else:
        missed.append("SUMMARY")

    for b in fixture["accomplishments"]:
        attach(b)
    for exp in fixture["experience"]:
        for b in exp["bullets"]:
            attach(b)

    FIXTURE.write_text(json.dumps(fixture, indent=2, ensure_ascii=False))
    print(f"matched {matched} paragraphs; missed: {missed or 'none'}")
    if missed:
        sys.exit(1)


if __name__ == "__main__":
    main()
