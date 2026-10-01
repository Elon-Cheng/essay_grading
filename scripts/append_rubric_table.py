from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
import xml.etree.ElementTree as ET
import argparse

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
ET.register_namespace("w", W)
q = lambda name: f"{{{W}}}{name}"


def run(paragraph, text, bold=False, color="000000"):
    r = ET.SubElement(paragraph, q("r"))
    props = ET.SubElement(r, q("rPr"))
    if bold:
        ET.SubElement(props, q("b"))
    ET.SubElement(props, q("color"), {q("val"): color})
    ET.SubElement(props, q("sz"), {q("val"): "22"})
    t = ET.SubElement(r, q("t"))
    t.text = text


def paragraph(parent, text="", bold=False):
    p = ET.SubElement(parent, q("p"))
    props = ET.SubElement(p, q("pPr"))
    ET.SubElement(props, q("spacing"), {q("after"): "120", q("line"): "300", q("lineRule"): "auto"})
    cursor = 0
    marker = "[[red]]"
    end_marker = "[[/red]]"
    while marker in text[cursor:]:
        start = text.index(marker, cursor)
        run(p, text[cursor:start], bold=bold)
        end = text.index(end_marker, start)
        run(p, text[start + len(marker):end], bold=bold, color="C00000")
        cursor = end + len(end_marker)
    run(p, text[cursor:], bold=bold)
    return p


def add_borders(table):
    props = table.find(q("tblPr"))
    borders = props.find(q("tblBorders"))
    if borders is None:
        borders = ET.SubElement(props, q("tblBorders"))
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        node = borders.find(q(edge))
        if node is None:
            node = ET.SubElement(borders, q(edge))
        node.attrib.update({q("val"): "single", q("sz"): "4", q("space"): "0", q("color"): "000000"})


def make_table(body):
    rows = [
        ("档次", "内容", "语言", "组织结构"),
        ("A", "9–10", "9–10", "[[red]]4–5[[/red]]"),
        ("B", "[[red]]7–8[[/red]]", "7–8", "3"),
        ("C", "5–6", "[[red]]5–6[[/red]]", "2"),
        ("D", "3–4", "3–4", "1"),
        ("E", "0–2", "0–2", "0"),
    ]
    table = ET.Element(q("tbl"))
    props = ET.SubElement(table, q("tblPr"))
    ET.SubElement(props, q("tblW"), {q("w"): "5000", q("type"): "pct"})
    ET.SubElement(props, q("tblBorders"))
    add_borders(table)
    for row_index, cells in enumerate(rows):
        tr = ET.SubElement(table, q("tr"))
        for cell in cells:
            tc = ET.SubElement(tr, q("tc"))
            paragraph(tc, cell, bold=row_index == 0)
    body.insert(list(body).index(body.find(q("sectPr"))), table)


def remove_existing_rubric_tables(body):
    for table in list(body.findall(q("tbl"))):
        text = "".join(t.text or "" for t in table.findall(".//" + q("t")))
        if "档次" in text and "组织结构" in text:
            body.remove(table)


def make_score_table(body):
    rows = [
        ("维度", "得分", "评价依据"),
        ("Content", "8/10", "成立目的、两项活动及理由完整；文化价值有展开，但具体例子不足。"),
        ("Language", "6/10", "大意清楚；但词义、搭配、逻辑主语和冠词问题较明显。"),
        ("Organization", "4/5", "段落功能明确，活动按顺序推进，结尾能够回扣主题。"),
        ("总分", "18/25", "内容和结构完成度较好，语言准确性是目前的主要限制。"),
    ]
    table = ET.Element(q("tbl"))
    props = ET.SubElement(table, q("tblPr"))
    ET.SubElement(props, q("tblW"), {q("w"): "5000", q("type"): "pct"})
    ET.SubElement(props, q("tblBorders"))
    add_borders(table)
    for row_index, cells in enumerate(rows):
        tr = ET.SubElement(table, q("tr"))
        for cell in cells:
            tc = ET.SubElement(tr, q("tc"))
            paragraph(tc, cell, bold=row_index == 0)
    rubric = next((t for t in body.findall(q("tbl")) if "档次" in "".join(x.text or "" for x in t.findall(".//" + q("t")))), None)
    body.insert(list(body).index(rubric) if rubric is not None else list(body).index(body.find(q("sectPr"))), table)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.source
    output = args.output
    with ZipFile(source) as zin:
        document = ET.fromstring(zin.read("word/document.xml"))
        body = document.find(q("body"))
        tables = body.findall(q("tbl"))
        for table in tables:
            add_borders(table)
        for table in list(body.findall(q("tbl"))):
            text = "".join(t.text or "" for t in table.findall(".//" + q("t")))
            if "维度" in text and "评价依据" in text:
                body.remove(table)
        remove_existing_rubric_tables(body)
        make_table(body)
        xml = ET.tostring(document, encoding="utf-8", xml_declaration=True)
        temp = output.with_suffix(".tmp.docx")
        with ZipFile(temp, "w", ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                zout.writestr(item, xml if item.filename == "word/document.xml" else zin.read(item.filename))
    temp.replace(output)


if __name__ == "__main__":
    main()
