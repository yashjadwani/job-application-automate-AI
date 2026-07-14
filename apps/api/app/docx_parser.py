"""DOCX → structured sections/bullets. Productionized from spikes/docx_roundtrip.py.

Bullets carry a stable (section-relative) index captured at parse time; the
exporter locates paragraphs by that index, never by text match (PRD §7.1).
"""

import io

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph


def _iter_paragraphs(doc):
    body = doc.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, doc)
        elif child.tag == qn("w:tbl"):
            for row in Table(child, doc).rows:
                for cell in row.cells:
                    yield from cell.paragraphs


def _is_heading(p: Paragraph) -> bool:
    style = (p.style.name or "").lower() if p.style else ""
    return style.startswith("heading") or style == "title"


def _is_bullet(p: Paragraph) -> bool:
    style = (p.style.name or "").lower() if p.style else ""
    if "list" in style:
        return True
    pPr = p._p.pPr
    return pPr is not None and pPr.find(qn("w:numPr")) is not None


def parse_docx(data: bytes) -> dict:
    """Return { personal: {}, sections: [{ id, title, bullets: [{index, text}] }] }."""
    doc = Document(io.BytesIO(data))
    sections: list[dict] = []
    current: dict | None = None
    preamble_lines: list[str] = []

    for para in _iter_paragraphs(doc):
        text = para.text.strip()
        if not text:
            continue
        if _is_heading(para):
            if current:
                sections.append(current)
            current = {"id": f"sec_{len(sections)}", "title": text, "bullets": []}
        elif _is_bullet(para) and current is not None:
            current["bullets"].append({"index": len(current["bullets"]), "text": text})
        elif current is None:
            preamble_lines.append(text)

    if current:
        sections.append(current)

    return {
        "personal": {"raw_header": preamble_lines[:6]},
        "sections": sections,
    }


def rewrite_docx(original: bytes, sections: list[dict], rewritten: dict[str, list[str]]) -> bytes:
    """Apply rewritten bullets onto the original DOCX, preserving all formatting.

    Locates each bullet by walking the doc in the same order as parse_docx and
    counting (section, bullet-index) — run properties are never touched.
    """
    doc = Document(io.BytesIO(original))
    section_i = -1
    bullet_i = 0

    for para in _iter_paragraphs(doc):
        if not para.text.strip():
            continue
        if _is_heading(para):
            section_i += 1
            bullet_i = 0
        elif _is_bullet(para) and section_i >= 0:
            sec_id = f"sec_{section_i}"
            new_bullets = rewritten.get(sec_id)
            if new_bullets and bullet_i < len(new_bullets):
                runs = para.runs
                if runs:
                    runs[0].text = new_bullets[bullet_i]
                    for r in runs[1:]:
                        r.text = ""
                else:
                    para.add_run(new_bullets[bullet_i])
            bullet_i += 1

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
