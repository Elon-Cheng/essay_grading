#!/usr/bin/env python3
"""Render a grading Markdown file into a teacher-style DOCX and verify fidelity."""

from __future__ import annotations

import argparse
import re
import tempfile
import xml.etree.ElementTree as ET
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_NS = "http://www.w3.org/XML/1998/namespace"
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
ET.register_namespace("w", W_NS)


def q(name: str) -> str:
    return f"{{{W_NS}}}{name}"


def clean_markdown(text: str) -> str:
    return text.replace("**", "").replace("`", "").replace("[[red]]", "").replace("[[/red]]", "")


def source_paragraphs(source_markdown: str) -> list[str]:
    marker = "## Essay"
    if marker not in source_markdown:
        raise ValueError("Source Markdown does not contain an Essay section")
    body = source_markdown.split(marker, 1)[1].strip()
    return [block.strip() for block in re.split(r"\n\s*\n", body) if block.strip()]


def normalized_paragraph(text: str) -> str:
    return re.sub(r"[ \t]+$", "", text.strip(), flags=re.M)


def docx_body_paragraphs(source_docx: Path) -> list[str]:
    with ZipFile(source_docx) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    body = root.find(q("body"))
    if body is None:
        raise ValueError("Source DOCX has no document body")
    paragraphs: list[str] = []
    for paragraph in body.findall(q("p")):
        text = "".join(t.text or "" for t in paragraph.findall(".//" + q("t")))
        if text.strip():
            paragraphs.append(normalized_paragraph(text))
    return paragraphs


def validate_source_docx(source_docx: Path, source: list[str]) -> None:
    docx_paragraphs = docx_body_paragraphs(source_docx)
    expected = [normalized_paragraph(paragraph) for paragraph in source]
    matches = [
        start
        for start in range(len(docx_paragraphs) - len(expected) + 1)
        if docx_paragraphs[start : start + len(expected)] == expected
    ]
    if len(matches) != 1:
        raise ValueError(
            "Source DOCX to Markdown validation failed: essay paragraphs must form "
            f"one exact contiguous block, found {len(matches)} matches"
        )


def parse_xml_preserving_namespaces(xml_bytes: bytes) -> ET.Element:
    for _, namespace in ET.iterparse(BytesIO(xml_bytes), events=("start-ns",)):
        prefix, uri = namespace
        try:
            ET.register_namespace(prefix or "", uri)
        except ValueError:
            pass
    return ET.fromstring(xml_bytes)


def marked_paragraphs(grading_markdown: str) -> list[str]:
    lines = grading_markdown.splitlines()
    blocks: list[str] = []
    in_original = False
    current: list[str] = []

    def flush() -> None:
        if current:
            blocks.append("\n".join(current).strip())
            current.clear()

    for line in lines:
        if line.strip() == "#### 原文及红色修改":
            flush()
            in_original = True
            continue
        if in_original and line.startswith("#### "):
            flush()
            in_original = False
            continue
        if not in_original:
            continue
        if not line.strip():
            flush()
        else:
            current.append(line)
    flush()
    return blocks


def recover_original(marked: str) -> str:
    without_additions = re.sub(r"\{\+\+.*?\+\+\}", "", marked, flags=re.S)
    restored = re.sub(r"~~(.*?)~~", r"\1", without_additions, flags=re.S)
    return clean_markdown(restored).strip()


def validate_markdown_fidelity(source: list[str], marked: list[str]) -> None:
    recovered = [recover_original(block) for block in marked]
    normalized_source = [normalized_paragraph(p) for p in source]
    normalized_recovered = [normalized_paragraph(p) for p in recovered]
    if normalized_source != normalized_recovered:
        details = []
        for index in range(max(len(normalized_source), len(normalized_recovered))):
            left = normalized_source[index] if index < len(normalized_source) else "<missing>"
            right = normalized_recovered[index] if index < len(normalized_recovered) else "<missing>"
            if left != right:
                details.append(f"paragraph {index + 1}: source={left!r}; recovered={right!r}")
        raise ValueError("Original-text reversibility failed: " + " | ".join(details))

    for index, block in enumerate(marked):
        original = source[index]
        for old in re.findall(r"~~(.*?)~~", block, flags=re.S):
            if original.count(clean_markdown(old)) != 1:
                raise ValueError(
                    f"Edit target must occur exactly once in source paragraph {index + 1}: {old!r}"
                )


def validate_output_shape(grading_markdown: str) -> None:
    forbidden_labels = (
        "写作身份：",
        "写作对象：",
        "写作目的：",
        "必答要点：",
        "实际字数：",
        "审题情况：",
        "评分：",
        "一句话诊断：",
    )
    for line in grading_markdown.splitlines():
        stripped = line.strip().lstrip("-*• ")
        if re.match(r"^#{1,3}\s", line):
            raise ValueError("Visible title and A/B/C or Paragraph heading levels are not allowed")
        if line.startswith("### Paragraph") or stripped.startswith(forbidden_labels):
            raise ValueError(f"Front-matter grading field is not allowed in output: {line!r}")


def add_run(
    paragraph: ET.Element,
    text: str,
    *,
    color: str,
    bold: bool = False,
    strike: bool = False,
    strike_color: str | None = None,
    underline: bool = False,
    underline_color: str | None = None,
    replacement: bool = False,
    size: int = 22,
) -> None:
    if not text:
        return
    run = ET.SubElement(paragraph, q("r"))
    props = ET.SubElement(run, q("rPr"))
    if replacement:
        ET.SubElement(props, q("rStyle"), {q("val"): "ReplacementText"})
    if bold:
        ET.SubElement(props, q("b"))
    if strike:
        # w:strike only accepts an on/off value.  A w:color attribute on this
        # element is invalid WordprocessingML and makes Microsoft Word reject
        # the generated DOCX as corrupt.
        ET.SubElement(props, q("strike"))
    if underline:
        underline_attrs = {q("val"): "single"}
        if underline_color:
            underline_attrs[q("color")] = underline_color
        ET.SubElement(props, q("u"), underline_attrs)
    ET.SubElement(props, q("color"), {q("val"): color})
    ET.SubElement(props, q("sz"), {q("val"): str(size)})
    text_element = ET.SubElement(run, q("t"))
    if text[:1].isspace() or text[-1:].isspace():
        text_element.set(f"{{{XML_NS}}}space", "preserve")
    text_element.text = text


def new_paragraph(body: ET.Element, *, student_original: bool = False) -> ET.Element:
    paragraph = ET.SubElement(body, q("p"))
    props = ET.SubElement(paragraph, q("pPr"))
    if student_original:
        ET.SubElement(props, q("pStyle"), {q("val"): "StudentOriginal"})
    ET.SubElement(
        props,
        q("spacing"),
        {q("after"): "120", q("line"): "300", q("lineRule"): "auto"},
    )
    return paragraph


def add_plain_paragraph(
    body: ET.Element, text: str, *, color: str = "C00000", bold: bool = False, size: int = 22
) -> None:
    paragraph = new_paragraph(body)
    add_run(paragraph, clean_markdown(text), color=color, bold=bold, size=size)


def add_marked_paragraph(body: ET.Element, text: str) -> None:
    paragraph = new_paragraph(body, student_original=True)
    cursor = 0
    pattern = re.compile(r"~~(.*?)~~|\{\+\+(.*?)\+\+\}", re.S)
    for match in pattern.finditer(text):
        add_run(paragraph, clean_markdown(text[cursor : match.start()]), color="000000")
        if match.group(1) is not None:
            add_run(
                paragraph,
                clean_markdown(match.group(1)),
                color="000000",
                strike=True,
                strike_color="C00000",
            )
        else:
            add_run(
                paragraph,
                clean_markdown(match.group(2)),
                color="C00000",
                replacement=True,
            )
        cursor = match.end()
    add_run(paragraph, clean_markdown(text[cursor:]), color="000000")


def add_table(body: ET.Element, lines: list[str]) -> None:
    rows = [
        [cell.strip().replace("**", "").replace("`", "") for cell in line.strip().strip("|").split("|")]
        for line in lines
    ]
    if len(rows) > 1 and all(re.fullmatch(r":?-{3,}:?", cell) for cell in rows[1]):
        rows.pop(1)
    table = ET.SubElement(body, q("tbl"))
    table_props = ET.SubElement(table, q("tblPr"))
    ET.SubElement(table_props, q("tblW"), {q("w"): "5000", q("type"): "pct"})
    borders = ET.SubElement(table_props, q("tblBorders"))
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        ET.SubElement(
            borders,
            q(edge),
            {q("val"): "single", q("sz"): "4", q("space"): "0", q("color"): "000000"},
        )
    for row_index, cells in enumerate(rows):
        row = ET.SubElement(table, q("tr"))
        for cell in cells:
            tc = ET.SubElement(row, q("tc"))
            paragraph = new_paragraph(tc)
            cursor = 0
            pattern = re.compile(r"\[\[red\]\](.*?)\[\[/red\]\]")
            for match in pattern.finditer(cell):
                add_run(paragraph, cell[cursor : match.start()], color="000000", bold=row_index == 0, size=22)
                add_run(paragraph, match.group(1), color="C00000", bold=row_index == 0, size=22)
                cursor = match.end()
            add_run(paragraph, cell[cursor:], color="000000", bold=row_index == 0, size=22)


def render(grading_markdown: str) -> tuple[bytes, list[str]]:
    document = ET.Element(q("document"))
    body = ET.SubElement(document, q("body"))
    lines = grading_markdown.splitlines()
    expected_text: list[str] = []
    in_original = False
    index = 0

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped == "#### 原文及红色修改":
            in_original = True
            index += 1
            continue
        if in_original and line.startswith("#### "):
            in_original = False
        if not stripped:
            index += 1
            continue
        if stripped.startswith("|"):
            table_lines = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                table_lines.append(lines[index])
                index += 1
            add_table(body, table_lines)
            for row in table_lines:
                if not re.fullmatch(r"\|?[\s:|-]+\|?", row):
                    expected_text.extend(clean_markdown(c.strip()) for c in row.strip().strip("|").split("|"))
            continue
        if line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            content = line[level:].strip()
            add_plain_paragraph(body, content, bold=True, size=22)
            expected_text.append(content)
        elif in_original:
            add_marked_paragraph(body, stripped)
            expected_text.append(clean_markdown(re.sub(r"~~|\{\+\+|\+\+\}", "", stripped)))
        else:
            content = re.sub(r"^[-*]\s+", "• ", stripped)
            add_plain_paragraph(body, content)
            expected_text.append(clean_markdown(content))
        index += 1

    section = ET.SubElement(body, q("sectPr"))
    ET.SubElement(section, q("pgSz"), {q("w"): "11906", q("h"): "16838"})
    ET.SubElement(
        section,
        q("pgMar"),
        {q("top"): "1200", q("right"): "1100", q("bottom"): "1200", q("left"): "1100"},
    )
    return ET.tostring(document, encoding="utf-8", xml_declaration=True), expected_text


def is_rendered_original(paragraph: ET.Element) -> bool:
    style = paragraph.find(q("pPr") + "/" + q("pStyle"))
    return style is not None and style.get(q("val")) == "StudentOriginal"


def is_source_paragraph(paragraph: ET.Element) -> bool:
    bookmark = paragraph.find(q("bookmarkStart"))
    return bookmark is not None and (bookmark.get(q("name")) or "").startswith("_EssaySource")


def put_marked_runs_on_source_paragraph(
    source_paragraph: ET.Element,
    rendered_paragraph: ET.Element,
    index: int,
) -> None:
    for child in list(source_paragraph):
        if child.tag != q("pPr"):
            source_paragraph.remove(child)
    bookmark_id = str(9000 + index)
    source_paragraph.append(
        ET.Element(q("bookmarkStart"), {q("id"): bookmark_id, q("name"): f"_EssaySource{index}"})
    )
    for child in list(rendered_paragraph):
        if child.tag != q("pPr"):
            source_paragraph.append(child)
    source_paragraph.append(ET.Element(q("bookmarkEnd"), {q("id"): bookmark_id}))


def merge_grading_into_source(
    source_docx: Path,
    source: list[str],
    grading_document_xml: bytes,
) -> bytes:
    with ZipFile(source_docx) as archive:
        source_xml = archive.read("word/document.xml")
    root = parse_xml_preserving_namespaces(source_xml)
    # ElementTree omits namespace declarations that are not used by an
    # element or attribute.  The source may nevertheless list those prefixes
    # in mc:Ignorable; leaving undeclared names there makes Word report a
    # corrupt document.  The merged document retains w14 attributes, while
    # the other extension namespaces are not present in this document body.
    if root.get(f"{{{MC_NS}}}Ignorable") is not None:
        root.set(f"{{{MC_NS}}}Ignorable", "w14")
    body = root.find(q("body"))
    if body is None:
        raise ValueError("Source DOCX has no document body")

    nonempty_paragraphs = [
        paragraph
        for paragraph in body.findall(q("p"))
        if "".join(t.text or "" for t in paragraph.findall(".//" + q("t"))).strip()
    ]
    expected = [normalized_paragraph(paragraph) for paragraph in source]
    matches = [
        start
        for start in range(len(nonempty_paragraphs) - len(expected) + 1)
        if [
            normalized_paragraph("".join(t.text or "" for t in paragraph.findall(".//" + q("t"))))
            for paragraph in nonempty_paragraphs[start : start + len(expected)]
        ]
        == expected
    ]
    if len(matches) != 1:
        raise ValueError("Cannot locate one unique essay block in source DOCX")
    source_targets = nonempty_paragraphs[matches[0] : matches[0] + len(expected)]

    grading_root = ET.fromstring(grading_document_xml)
    grading_body = grading_root.find(q("body"))
    if grading_body is None:
        raise ValueError("Rendered grading document has no body")
    grading_children = [child for child in list(grading_body) if child.tag != q("sectPr")]
    rendered_originals = [
        child for child in grading_children if child.tag == q("p") and is_rendered_original(child)
    ]
    if len(rendered_originals) != len(source_targets):
        raise ValueError(
            "Grading Markdown paragraph count does not match source DOCX: "
            f"{len(rendered_originals)} vs {len(source_targets)}"
        )

    mapped_children: list[ET.Element] = []
    source_index = 0
    for child in grading_children:
        if child.tag == q("p") and is_rendered_original(child):
            target = source_targets[source_index]
            put_marked_runs_on_source_paragraph(target, child, source_index + 1)
            mapped_children.append(target)
            source_index += 1
        else:
            mapped_children.append(child)

    for table in list(body.findall(q("tbl"))):
        table_text = "".join(t.text or "" for t in table.findall(".//" + q("t")))
        if all(label in table_text for label in ("档次", "内容", "语言", "组织结构", "A", "B", "C", "D", "E")):
            body.remove(table)

    insertion_index = list(body).index(source_targets[0])
    for paragraph in source_targets:
        body.remove(paragraph)
    for offset, child in enumerate(mapped_children):
        body.insert(insertion_index + offset, child)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def write_docx_from_source(path: Path, source_docx: Path, document_xml: bytes) -> None:
    with ZipFile(source_docx) as source_archive, ZipFile(path, "w", ZIP_DEFLATED) as output_archive:
        for item in source_archive.infolist():
            data = document_xml if item.filename == "word/document.xml" else source_archive.read(item.filename)
            output_archive.writestr(item, data)


def validate_docx(
    path: Path,
    source: list[str],
    grading_markdown: str,
    expected_text: list[str],
) -> None:
    with ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError("DOCX ZIP validation failed")
        root = ET.fromstring(archive.read("word/document.xml"))

    recovered: list[str] = []
    for paragraph in root.findall(".//" + q("p")):
        if not is_source_paragraph(paragraph):
            continue
        parts: list[str] = []
        for run in paragraph.findall(q("r")):
            props = run.find(q("rPr"))
            style = props.find(q("rStyle")) if props is not None else None
            is_replacement = style is not None and style.get(q("val")) == "ReplacementText"
            if is_replacement:
                continue
            parts.append("".join(t.text or "" for t in run.findall(q("t"))))
        recovered.append("".join(parts).strip())

    normalized_source = [normalized_paragraph(p) for p in source]
    normalized_recovered = [normalized_paragraph(p) for p in recovered]
    if normalized_source != normalized_recovered:
        raise ValueError("DOCX reverse-recovery does not match source Markdown")

    paragraphs = root.findall(".//" + q("p"))
    actual_text = ["".join(t.text or "" for t in paragraph.findall(".//" + q("t"))) for paragraph in paragraphs]
    nonempty_items = [(paragraph, text) for paragraph, text in zip(paragraphs, actual_text) if text]
    nonempty_text = [text for _, text in nonempty_items]
    matches = [
        start
        for start in range(len(nonempty_text) - len(expected_text) + 1)
        if nonempty_text[start : start + len(expected_text)] == expected_text
    ]
    if len(matches) != 1:
        raise ValueError(
            "Grading Markdown must appear once as an exact contiguous block in the source-based DOCX; "
            f"found {len(matches)} matches"
        )
    grading_paragraphs = [paragraph for paragraph, _ in nonempty_items[matches[0] : matches[0] + len(expected_text)]]
    table_paragraphs = {
        id(paragraph)
        for table in root.findall(".//" + q("tbl"))
        for paragraph in table.findall(".//" + q("p"))
    }

    all_text = "\n".join(actual_text)
    if "Revised Version" in all_text or "修改后版本" in all_text or "完整修改稿" in all_text:
        raise ValueError("A full revised-version section was generated")
    if "?" in all_text:
        # Question marks are allowed only if they exist in the source or grading Markdown.
        allowed = "?" in "\n".join(source) or "?" in grading_markdown
        if not allowed:
            raise ValueError("Unexpected question mark found in DOCX")

    for paragraph in grading_paragraphs:
        student_paragraph = is_source_paragraph(paragraph)
        for run in paragraph.findall(q("r")):
            text = "".join(t.text or "" for t in run.findall(q("t")))
            if not text:
                continue
            props = run.find(q("rPr"))
            color = props.find(q("color")) if props is not None else None
            size = props.find(q("sz")) if props is not None else None
            strike = props.find(q("strike")) if props is not None else None
            underline = props.find(q("u")) if props is not None else None
            if student_paragraph and strike is not None:
                expected_colors = {"000000"}
            elif student_paragraph:
                expected_colors = {"000000", "C00000"}
                if underline is not None:
                    raise ValueError(f"Replacement text must not be underlined for {text!r}")
            else:
                expected_colors = (
                {"000000", "C00000"} if id(paragraph) in table_paragraphs else {"C00000"}
                )
            if color is None or color.get(q("val")) not in expected_colors:
                raise ValueError(f"Unexpected text color for {text!r}")
            if size is None or size.get(q("val")) != "22":
                raise ValueError(f"Grading text must use body size for {text!r}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-docx", required=True, type=Path)
    parser.add_argument("--source-md", required=True, type=Path)
    parser.add_argument("--grading-md", required=True, type=Path)
    parser.add_argument("--output-docx", required=True, type=Path)
    args = parser.parse_args()

    source_text = args.source_md.read_text(encoding="utf-8")
    grading_text = args.grading_md.read_text(encoding="utf-8")
    source = source_paragraphs(source_text)
    marked = marked_paragraphs(grading_text)
    validate_source_docx(args.source_docx, source)
    validate_markdown_fidelity(source, marked)
    validate_output_shape(grading_text)

    grading_document_xml, expected_text = render(grading_text)
    document_xml = merge_grading_into_source(args.source_docx, source, grading_document_xml)
    args.output_docx.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=args.output_docx.stem + ".",
            suffix=".tmp.docx",
            dir=args.output_docx.parent,
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
        temporary_path = Path(temporary_name)
        write_docx_from_source(temporary_path, args.source_docx, document_xml)
        validate_docx(temporary_path, source, grading_text, expected_text)
        temporary_path.replace(args.output_docx)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
    print(f"generated={args.output_docx}")
    print(f"source_paragraphs={len(source)}")
    print("source_docx_match=ok")
    print("source_base=ok")
    print("reversibility=ok")
    print("content_match=ok")
    print("format=ok")


if __name__ == "__main__":
    main()
