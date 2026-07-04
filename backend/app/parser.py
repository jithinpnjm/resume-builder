"""Resume parsing: uploaded file -> raw text -> best-effort ResumeJSON.

This is intentionally lossy. The onboarding UI is expected to let the user
review and correct the extracted ResumeJSON before it's saved as the source
of truth — see the build brief, step 1.
"""
from __future__ import annotations

import io

import pdfplumber
from docx import Document
from docx.document import Document as DocumentClass
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from .gemini_client import generate_json
from .schemas import ResumeJSON

SUPPORTED_EXTENSIONS = {".pdf", ".docx"}


def extract_text(filename: str, content: bytes) -> str:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return _extract_pdf_text(content)
    if lower.endswith(".docx"):
        return _extract_docx_text(content)
    raise ValueError(f"Unsupported file type: {filename}. Use one of {SUPPORTED_EXTENSIONS}")


def _extract_pdf_text(content: bytes) -> str:
    text_parts = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
    return "\n".join(text_parts)


def _iter_block_items(parent):
    """Yield paragraphs and tables in document order, recursing into table cells.

    Many resume templates (including two-column layouts) lay out all content
    inside tables — document.paragraphs alone misses that content entirely.
    """
    parent_elm = parent.element.body if isinstance(parent, DocumentClass) else parent._tc
    for child in parent_elm.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, parent)
        elif child.tag == qn("w:tbl"):
            table = Table(child, parent)
            for row in table.rows:
                for cell in row.cells:
                    yield from _iter_block_items(cell)


def _extract_docx_text(content: bytes) -> str:
    document = Document(io.BytesIO(content))
    lines = []
    for block in _iter_block_items(document):
        if isinstance(block, Paragraph) and block.text.strip():
            lines.append(block.text.strip())
    return "\n".join(lines)


_EXTRACTION_SYSTEM_PROMPT = """You are extracting structured data from a raw resume text
dump. Return ONLY valid JSON matching this schema:

{
  "contact": { "name": "", "location": "", "email": "", "phone": "", "linkedin": "", "github": "" },
  "summary": "",
  "accomplishments": [ { "id": "acc1", "text": "", "tags": [] } ],
  "skills": { "categories": [ { "name": "", "items": [""] } ] },
  "experience": [
    {
      "id": "exp_1",
      "company": "", "title": "", "location": "", "start": "", "end": "",
      "bullets": [ { "id": "exp_1_b1", "text": "", "tags": [] } ]
    }
  ],
  "projects": [ { "id": "proj_1", "name": "", "bullets": [ { "id": "proj_1_pb1", "text": "" } ] } ],
  "education": [ { "degree": "", "institution": "", "year": "" } ],
  "languages": [ { "name": "", "level": "" } ],
  "certifications": []
}

Rules:
- Preserve bullet text verbatim from the source — do not reword, summarize, or embellish.
- Assign sequential ids: acc1, acc2, ... for top-level accomplishments/highlights (if the
  resume has such a section separate from work history); exp_1, exp_2, ... for experience
  entries; proj_1, proj_2, ... for projects.
- Bullet ids MUST be globally unique across the whole document — prefix each bullet with
  its parent's id: exp_1_b1, exp_1_b2, ... for exp_1's bullets, exp_2_b1, exp_2_b2, ... for
  exp_2's bullets, and proj_1_pb1, proj_1_pb2, ... for proj_1's bullets. Never reuse a bare
  "b1"/"b2" style id across two different experience or project entries.
- start/end dates: use "YYYY-MM" where determinable, else copy the source string as-is.
  Use "present" for current roles.
- If a field cannot be determined, use an empty string or empty list — never invent data.
- tags: leave as an empty list; this is filled in later by the user, not by you.
"""


def parse_resume_to_json(raw_text: str) -> ResumeJSON:
    data = generate_json(_EXTRACTION_SYSTEM_PROMPT, raw_text)
    return ResumeJSON.model_validate(data)
