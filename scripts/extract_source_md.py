from pathlib import Path
from zipfile import ZipFile
import argparse
import xml.etree.ElementTree as ET

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
ns = {"w": W}
parser = argparse.ArgumentParser()
parser.add_argument("--source-docx", type=Path, required=True)
parser.add_argument("--output-md", type=Path, required=True)
parser.add_argument("--start", required=True, help="Exact first essay paragraph")
args = parser.parse_args()

with ZipFile(args.source_docx) as archive:
    root = ET.fromstring(archive.read("word/document.xml"))
paragraphs = [
    "".join(t.text or "" for t in paragraph.findall(".//w:t", ns))
    for paragraph in root.findall(".//w:body/w:p", ns)
]
paragraphs = [p for p in paragraphs if p.strip()]
matches = [index for index, paragraph in enumerate(paragraphs) if paragraph.strip() == args.start]
if len(matches) != 1:
    raise ValueError(f"Expected one start paragraph {args.start!r}, found {len(matches)}")
paragraphs = paragraphs[matches[0] :]
args.output_md.parent.mkdir(parents=True, exist_ok=True)
args.output_md.write_text("## Essay\n\n" + "\n\n".join(paragraphs) + "\n", encoding="utf-8")
