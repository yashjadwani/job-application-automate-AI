"""PDF generation.

Cover letter: HTML template → WeasyPrint (needs pango/cairo — present in the
Modal image; on a local Windows box this raises a clear error instead).
CV: DOCX → PDF via LibreOffice headless.
"""

import shutil
import subprocess
import tempfile
from datetime import date
from html import escape
from pathlib import Path

COVER_TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  @page {{ size: A4; margin: 2.4cm 2.6cm; }}
  body {{
    font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
    font-size: 11pt; line-height: 1.55; color: #1d1d1f;
  }}
  .header {{ margin-bottom: 28px; }}
  .name {{ font-size: 17pt; font-weight: 600; letter-spacing: -0.02em; }}
  .contact {{ color: #6e6e73; font-size: 9.5pt; margin-top: 3px; }}
  .date {{ color: #6e6e73; font-size: 9.5pt; margin-top: 18px; }}
  .body p {{ margin: 0 0 12px 0; white-space: pre-wrap; }}
</style></head>
<body>
  <div class="header">
    <div class="name">{name}</div>
    <div class="contact">{contact}</div>
    <div class="date">{today}</div>
  </div>
  <div class="body"><p>{body}</p></div>
</body></html>"""


def cover_letter_pdf(name: str, contact: str, body: str) -> bytes:
    try:
        from weasyprint import HTML
    except Exception as exc:  # missing native libs locally
        raise RuntimeError(
            "WeasyPrint unavailable in this environment (needs pango/cairo). "
            "Works in the Modal deployment."
        ) from exc

    html = COVER_TEMPLATE.format(
        name=escape(name or ""),
        contact=escape(contact or ""),
        today=date.today().strftime("%d %B %Y"),
        body=escape(body).replace("\n\n", "</p><p>").replace("\n", "<br>"),
    )
    return HTML(string=html).write_pdf()


def docx_to_pdf(docx_bytes: bytes) -> bytes:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise RuntimeError(
            "LibreOffice not found in this environment. "
            "Works in the Modal deployment."
        )
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "cv.docx"
        src.write_bytes(docx_bytes)
        subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", tmp, str(src)],
            check=True, capture_output=True, timeout=120,
        )
        out = Path(tmp) / "cv.pdf"
        if not out.exists():
            raise RuntimeError("LibreOffice produced no output")
        return out.read_bytes()
