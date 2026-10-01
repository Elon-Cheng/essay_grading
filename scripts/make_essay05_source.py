from pathlib import Path
from docx import Document

source = Path("tests/cases/essay-05.md").read_text(encoding="utf-8")
body = source.split("## Essay", 1)[1].strip()
blocks = [block.strip() for block in body.split("\n\n") if block.strip()]
doc = Document()
for block in blocks:
    doc.add_paragraph(block)
doc.save("outcome/essay-05-source.docx")
