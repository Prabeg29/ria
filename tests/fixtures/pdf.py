from pathlib import Path

import pytest
from fpdf import FPDF

_SAMPLE_RESUME_MD = Path(__file__).parent / "data" / "sample_resume.md"


@pytest.fixture(scope="session")
def resume_pdf_bytes() -> bytes:
    lines = _SAMPLE_RESUME_MD.read_text().splitlines()

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    for line in lines:
        latin_line = line.encode("latin-1", errors="replace").decode("latin-1")
        pdf.cell(0, 6, latin_line, new_x="LMARGIN", new_y="NEXT")

    return bytes(pdf.output())
