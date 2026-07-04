"""One-time script: turn the source resume docx into a docxtpl template.

Walks the document in the exact order the layout was authored (paragraphs,
including inside nested tables) and replaces the text of specific runs with
Jinja placeholders. Only run TEXT is touched — every run's font, bold,
color, and spacing is left untouched, so the rendered layout stays
byte-for-byte identical to the source for any input data.

This script is tied to the specific structure of resume_template_source.docx
(dumped via the run-level inspection in the build session). If the source
resume's structure ever changes, this script needs to be re-derived by
walking the new document's paragraphs/runs and updating REPLACEMENTS.
"""
from __future__ import annotations

import sys
from pathlib import Path

import docx
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "app" / "templates"
SOURCE = TEMPLATES_DIR / "resume_template_source.docx"
OUTPUT = TEMPLATES_DIR / "resume_template.docx"


def iter_paragraphs(parent):
    """Yield paragraphs in document order, recursing into nested table cells."""
    parent_elm = parent.element.body if isinstance(parent, docx.document.Document) else parent._tc
    for child in parent_elm.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, parent)
        elif child.tag == qn("w:tbl"):
            table = Table(child, parent)
            for row in table.rows:
                for cell in row.cells:
                    yield from iter_paragraphs(cell)


# Ordered list of Jinja replacements for every non-empty paragraph, in the
# exact order they appear in the source document. `None` means "leave this
# paragraph's text untouched" (section headers like "Skills", "Education").
REPLACEMENTS: list[str | None] = [
    "{{ contact.email }}",
    "{{ contact.phone }}",
    "{{ contact.location }}",
    "{{ contact.location }}",
    "{{ contact.linkedin }}",
    None,  # "Education"
    "{{ education[0].degree }}",
    "{{ education[0].institution }}",
    "{{ education[0].year }}",
    None,  # "Languages"
    "{{ languages[0].name }}",
    "{{ languages[0].level }}",
    "{{ languages[1].name }}",
    "{{ languages[1].level }}",
    "{{ contact.name }}",
    None,  # "Professional Summary"
    "{{r summary }}",
    None,  # "Accomplishments"
    "{{r accomplishments[0] }}",
    "{{r accomplishments[1] }}",
    "{{r accomplishments[2] }}",
    "{{r accomplishments[3] }}",
    "{{r accomplishments[4] }}",
    "{{r accomplishments[5] }}",
    None,  # "Skills"
    "{{ skills[0] }}",
    "{{ skills[1] }}",
    "{{ skills[2] }}",
    "{{ skills[3] }}",
    "{{ skills[4] }}",
    "{{ skills[5] }}",
    "{{ skills[6] }}",
    "{{ skills[7] }}",
    "{{ skills[8] }}",
    "{{ skills[9] }}",
    None,  # "Work History"
    "{{ jobs[0].dates }}",
    "{{ jobs[0].header }}",
    "{{r jobs[0].bullets[0] }}",
    "{{r jobs[0].bullets[1] }}",
    "{{r jobs[0].bullets[2] }}",
    "{{r jobs[0].bullets[3] }}",
    "{{r jobs[0].bullets[4] }}",
    "{{r jobs[0].bullets[5] }}",
    "{{r jobs[0].bullets[6] }}",
    "{{r jobs[0].bullets[7] }}",
    "{{r jobs[0].bullets[8] }}",
    "{{ jobs[1].dates }}",
    "{{ jobs[1].header }}",
    "{{r jobs[1].bullets[0] }}",
    "{{r jobs[1].bullets[1] }}",
    "{{r jobs[1].bullets[2] }}",
    "{{r jobs[1].bullets[3] }}",
    "{{r jobs[1].bullets[4] }}",
    "{{r jobs[1].bullets[5] }}",
    "{{r jobs[1].bullets[6] }}",
    "{{r jobs[1].bullets[7] }}",
    "{{ jobs[2].dates }}",
    "{{ jobs[2].header }}",
    "{{r jobs[2].bullets[0] }}",
    "{{r jobs[2].bullets[1] }}",
    "{{r jobs[2].bullets[2] }}",
    "{{r jobs[2].bullets[3] }}",
    "{{r jobs[2].bullets[4] }}",
    "{{r jobs[2].bullets[5] }}",
    "{{r jobs[2].bullets[6] }}",
    "{{ jobs[3].dates }}",
    "{{ jobs[3].header }}",
    "{{r jobs[3].bullets[0] }}",
    "{{r jobs[3].bullets[1] }}",
    "{{r jobs[3].bullets[2] }}",
    None,  # "Certifications"
    "{{ certifications[0] }}",
    "{{ certifications[1] }}",
    "{{ certifications[2] }}",
    "{{ certifications[3] }}",
    "{{ certifications[4] }}",
    "{{ certifications[5] }}",
    None,  # trailing stray "." paragraph outside the layout table
]


def main() -> None:
    doc = docx.Document(SOURCE)

    non_empty_paragraphs = [p for p in iter_paragraphs(doc) if p.text.strip()]

    if len(non_empty_paragraphs) != len(REPLACEMENTS):
        print(
            f"MISMATCH: document has {len(non_empty_paragraphs)} non-empty paragraphs, "
            f"REPLACEMENTS has {len(REPLACEMENTS)}. Re-derive the map before proceeding.",
            file=sys.stderr,
        )
        for i, p in enumerate(non_empty_paragraphs):
            print(f"  [{i}] {p.text!r}", file=sys.stderr)
        sys.exit(1)

    for paragraph, replacement in zip(non_empty_paragraphs, REPLACEMENTS):
        if replacement is None:
            continue
        runs = paragraph.runs
        runs[0].text = replacement
        for run in runs[1:]:
            run.text = ""

    doc.save(OUTPUT)
    print(f"Template written to {OUTPUT}")


if __name__ == "__main__":
    main()
