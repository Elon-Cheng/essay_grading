from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import uuid
import zipfile
import sys
import time
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit
from html import escape
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, UploadFile, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from scripts.render_grading_docx import source_paragraphs, marked_paragraphs, validate_markdown_fidelity, validate_output_shape

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.resolve()
load_dotenv(ROOT / '.env')
import accounts

DATA = Path(os.getenv('ESSAY_DATA_DIR',str(ROOT / 'data')))
DATA.mkdir(exist_ok=True)
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}
META_LOCK = threading.RLock()

def read_meta(path: Path) -> dict[str, Any]:
    with META_LOCK:
        return json.loads(path.read_text(encoding="utf-8"))

def write_meta(path: Path, meta: dict[str, Any]) -> None:
    with META_LOCK:
        path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

def grading_marker() -> str:
    text = (ROOT / "scripts" / "render_grading_docx.py").read_text(encoding="utf-8")
    match = re.search(r'line\.strip\(\) == "([^"]+)"', text)
    if not match:
        raise RuntimeError("无法读取渲染脚本的原文标记")
    return match.group(1)
app = FastAPI(title="Essay Grading Studio", version="0.1.0")
accounts.initialize()
app.include_router(accounts.router)

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")

@app.middleware('http')
async def protect_requests(request: Request, call_next):
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin=request.headers.get('origin')
        if request.headers.get('sec-fetch-site')=='cross-site' or (origin and urlsplit(origin).netloc!=request.url.netloc):
            return JSONResponse({'detail':'请求来源不受信任'},status_code=403)
    response=await call_next(request)
    if request.url.path.startswith('/api/') or request.url.path in ('/','/login','/workspace') or request.url.path.startswith('/static/'):
        response.headers['Cache-Control']='no-store'
    if request.url.path in ('/login','/workspace'):
        response.headers['X-Robots-Tag']='noindex, nofollow'
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    return response

@app.get('/login',response_class=HTMLResponse)
def login_page():
    return (ROOT / 'static' / 'login.html').read_text(encoding='utf-8')

@app.get('/workspace',response_class=HTMLResponse)
def workspace_page(user=Depends(accounts.current_user)):
    return (ROOT / 'static' / 'index.html').read_text(encoding='utf-8')

@app.get('/healthz')
def healthz():
    return {'status': 'ok'}

@app.get('/robots.txt', response_class=HTMLResponse)
def robots():
    return HTMLResponse(f"User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /workspace\nDisallow: /login\nSitemap: {PUBLIC_BASE_URL}/sitemap.xml\n", media_type='text/plain')

@app.get('/sitemap.xml', response_class=HTMLResponse)
def sitemap():
    return HTMLResponse(f'''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{escape(PUBLIC_BASE_URL)}/</loc><changefreq>weekly</changefreq><priority>1.0</priority></url>
</urlset>''', media_type='application/xml')

if (ROOT / "static").exists():
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


def paragraphs_from_docx(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as zf:
        root = ET.fromstring(zf.read("word/document.xml"))
    return [
        "".join(t.text or "" for t in p.findall(".//w:t", NS)).strip()
        for p in root.findall(".//w:body/w:p", NS)
        if "".join(t.text or "" for t in p.findall(".//w:t", NS)).strip()
    ]


def write_source_md(docx: Path, out: Path, start: str | None) -> list[str]:
    paragraphs = paragraphs_from_docx(docx)
    if not paragraphs:
        raise ValueError("DOCX 中没有可读取的正文段落")
    chosen = start.strip() if start else paragraphs[0]
    try:
        index = paragraphs.index(chosen)
    except ValueError as exc:
        raise ValueError("未找到指定的作文首段，请检查首段文字是否完全一致") from exc
    essay = paragraphs[index:]
    out.write_text("## Essay\n\n" + "\n\n".join(essay) + "\n", encoding="utf-8")
    return essay


def mock_grading(essay: list[str]) -> str:
    marker = grading_marker()
    parts = [
        "全文综合评价和提升建议：文章基本围绕主题展开，建议进一步补充具体事例和因果解释，使观点更有说服力。",
        "本篇文章打分估计为：18—21分。",
        "| 档次 | 内容 | 语言 | 组织结构 |\n|---|---|---|---|\n| A | 主题明确，细节充分 | 表达准确自然 | 衔接清晰 |\n| B | 基本切题，部分展开 | 有少量错误 | 结构基本完整 |\n| C | 内容较简单 | 错误影响表达 | 组织较弱 |\n| D | 偏题或内容不足 | 错误较多 | 结构混乱 |\n| E | 未完成任务 | 难以理解 | 缺少结构 |",
    ]
    for i, paragraph in enumerate(essay, 1):
        marked = paragraph
        if i == 1 and len(paragraph) > 12:
            target = paragraph.split()[0]
            marked = paragraph.replace(target, f"~~{target}~~{{++{target}++}}", 1)
        parts.extend([
            marker,
            marked,
            "#### 段落点评",
            f"第{i}段能够承担文章的表达任务，内容与前后文基本连贯。建议增加具体信息，说明观点如何由事实得到支持。",
            "#### 语言提升",
            "1. 注意句子之间的连接关系，并优先使用准确、自然的固定搭配。",
            "#### 问题建议",
            "结合本段内容补充一个具体例子，再检查主语和指代是否清晰。",
        ])
    parts.append("#### 全文综合评价和提升建议")
    parts.append("建议围绕中心观点补充细节，完成后通读全文检查句间衔接和时态一致性。")
    return "\n\n".join(parts) + "\n"


def call_openai(source: str) -> str:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return ""
    try:
        import httpx
        prompt = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for name in ("scoring-rubric.md", "writing-rubric.md", "teacher-style.md", "output-format.md", "error-taxonomy.md"):
            prompt += "\n\n" + (ROOT / "references" / name).read_text(encoding="utf-8")
        paragraphs = source_paragraphs(source) if "## Essay" in source else [source.strip()]
        prompt += """

Web 应用内部输出协议（必须遵守，优先于前述文档的展示版式）：
你只生成供程序转换的批改 Markdown；原始 DOCX 已保存在服务器，程序负责生成 Word。
不要调用工具、解释无法生成 Word、添加交付说明或用代码围栏包裹全文。
输入 paragraphs 是从原始 DOCX 逐段提取的完整原文，顺序和段落边界不可改变。
包含题目、中文说明、称呼、署名的段落也必须逐段保留，非作文内容原样输出且不添加点评。
每个原文段落必须以独占一行的 `#### 原文及红色修改` 开始，下一段为该原文的完整批改标记文本。
删除用 ~~原文~~，新增用 {++新文字++}，替换用 ~~原文~~{++新文字++}。
禁止直接改写原文或用加粗表示修改。去掉 {++...++} 并恢复 ~~...~~ 后，必须逐字还原输入段落。
删除或替换的片段在对应原文段落中必须只出现一次；插入文字不能替代或吞掉原文空格。
正文段后的评语分别以 `#### 段落点评`、`#### 语言提升`、`#### 问题建议` 分隔。
称呼、署名等无需完整点评时，也必须用 `#### 格式说明` 结束原文区块（可写“保留原文。”）。
正文点评写完后再开始下一个原文区块，不得合并段落、遗漏或重复段落。
开头可用 `#### 审题情况` 加一段说明；不要使用一级至三级标题或“审题情况：”等前置信息字段。
文末用 `#### 全文综合评价和提升建议`，再写本篇分数及 A–E 分档参考表。
这些四级标题是内部解析标记，程序会使用正文字号渲染，不是放大的章节标题。
"""
        body = {
            "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            "input": [{"role": "system", "content": prompt}, {"role": "user", "content": json.dumps({"source_markdown": source, "paragraphs": paragraphs}, ensure_ascii=False)}],
        }
        base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        for attempt in range(2):
            response = httpx.post(f"{base_url}/responses", headers={"Authorization": f"Bearer {key}"}, json=body, timeout=120)
            response.raise_for_status()
            data = response.json()
            text = data.get("output_text") or ""
            if not text:
                for item in data.get("output", []):
                    for content in item.get("content", []):
                        if content.get("type") in ("output_text", "text"):
                            text += content.get("text", "")
            if not text.strip():
                raise RuntimeError("API returned no grading text")
            try:
                validate_markdown_fidelity(paragraphs, marked_paragraphs(text))
                validate_output_shape(text)
                return text
            except ValueError as exc:
                logger.warning("AI grading format validation failed (attempt %s): %s", attempt + 1, exc)
                if attempt == 1:
                    raise RuntimeError("AI 批改格式校验失败，请重试；原始作文已保留。") from None
                body["input"].extend([
                    {"role": "assistant", "content": text},
                    {"role": "user", "content": "修正上次 Markdown 的格式与原文保真错误，返回完整批改 Markdown。不得改动输入原文。校验错误：" + str(exc)[:6000]},
                ])
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"Grading API returned HTTP {exc.response.status_code}") from None
    except RuntimeError:
        raise
    except Exception:
        raise RuntimeError("Grading API request failed; check API configuration and connectivity") from None


def run_job(job_id: str, start: str | None) -> None:
    folder = DATA / job_id
    meta = read_meta(folder / "meta.json")
    try:
        meta.update(status="running", stage="extracting")
        write_meta(folder / "meta.json", meta)
        essay = write_source_md(folder / "source.docx", folder / "source.md", start)
        source = (folder / "source.md").read_text(encoding="utf-8")
        meta.update(stage="grading")
        write_meta(folder / "meta.json", meta)
        grading = call_openai(source) or mock_grading(essay)
        (folder / "grading.md").write_text(grading, encoding="utf-8")
        meta.update(stage="rendering")
        write_meta(folder / "meta.json", meta)
        subprocess.run([sys.executable, str(ROOT / "scripts" / "render_grading_docx.py"), "--source-docx", str(folder / "source.docx"), "--source-md", str(folder / "source.md"), "--grading-md", str(folder / "grading.md"), "--output-docx", str(folder / "graded.docx")], check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
        meta.update(status="succeeded", stage="done")
        meta.pop("error", None)
    except subprocess.CalledProcessError as exc:
        logger.error("DOCX rendering failed for job %s: %s", job_id, exc.stderr)
        meta.update(status="failed", stage="error", error="批改文档生成失败，请重试；原始作文已保留。")
    except Exception as exc:
        meta.update(status="failed", stage="error", error=str(exc))
    write_meta(folder / "meta.json", meta)
    if meta.get("user_id"):
        accounts.audit(meta["user_id"], meta["status"], meta.get("filename", job_id))


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    page=(ROOT / "static" / "landing.html").read_text(encoding="utf-8")
    return page.replace('rel="canonical" href="/"',f'rel="canonical" href="{escape(PUBLIC_BASE_URL,quote=True)}/"')


@app.post("/api/essays")
async def create_essay(background: BackgroundTasks, file: UploadFile = File(...), start: str | None = Form(None), user=Depends(accounts.current_user)) -> dict[str, Any]:
    if not file.filename or not file.filename.lower().endswith(".docx"):
        raise HTTPException(400, "仅支持 .docx 文件")
    job_id = uuid.uuid4().hex
    folder = DATA / job_id
    folder.mkdir()
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(413, "文件不能超过 10 MB")
    if user["role"] == "user":
        today = datetime.now(ZoneInfo("Asia/Shanghai")).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        with accounts.database() as db:
            used = db.execute("SELECT COUNT(*) FROM jobs WHERE user_id=? AND created>=?", (user["id"], today)).fetchone()[0]
        if used >= 1:
            raise HTTPException(429, "普通用户每天只能使用一次批改功能，请明天再试")
    (folder / "source.docx").write_bytes(content)
    meta = {"id": job_id, "filename": file.filename, "status": "queued", "stage": "queued", "user_id": user["id"]}
    write_meta(folder / "meta.json", meta)
    with accounts.database() as db:
        db.execute("INSERT INTO jobs(id,user_id,filename,start,created) VALUES(?,?,?,?,?)", (job_id,user["id"],file.filename,start,time.time()))
    accounts.audit(user["id"], "upload", file.filename)
    background.add_task(run_job, job_id, start)
    return meta


@app.get("/api/essays/{job_id}")
def get_essay(job_id: str, user=Depends(accounts.current_user)) -> dict[str, Any]:
    accounts.owned_job(job_id,user)
    path = DATA / job_id / "meta.json"
    if not path.exists():
        raise HTTPException(404, "任务不存在")
    return read_meta(path)


@app.get("/api/essays")
def list_essays(user=Depends(accounts.current_user)) -> list[dict[str, Any]]:
    items = []
    for path in DATA.glob("*/meta.json"):
        try:
            item=read_meta(path)
            if item.get("user_id")==user["id"]:
                items.append(item)
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(items, key=lambda item: item.get("id", ""), reverse=True)


@app.post("/api/essays/{job_id}/retry")
def retry_essay(job_id: str, background: BackgroundTasks, user=Depends(accounts.current_user)) -> dict[str, Any]:
    job=accounts.owned_job(job_id,user)
    folder = DATA / job_id
    meta_path = folder / "meta.json"
    if not meta_path.exists() or not (folder / "source.docx").exists():
        raise HTTPException(404, "任务不存在")
    meta = read_meta(meta_path)
    if meta['status'] != 'failed':
        raise HTTPException(409,'仅可重试失败的任务')
    meta.update(status="queued", stage="queued", error=None)
    write_meta(meta_path, meta)
    accounts.audit(user["id"], "retry", meta.get("filename",""))
    background.add_task(run_job, job_id, job['start'])
    return meta


@app.get("/api/essays/{job_id}/preview")
def preview(job_id: str, user=Depends(accounts.current_user)) -> dict[str, str]:
    job=accounts.owned_job(job_id,user)
    accounts.audit(user['id'],'preview',job['filename'])
    folder = DATA / job_id
    if not (folder / "meta.json").exists():
        raise HTTPException(404, "任务不存在")
    return {"source": (folder / "source.md").read_text(encoding="utf-8") if (folder / "source.md").exists() else "", "grading": (folder / "grading.md").read_text(encoding="utf-8") if (folder / "grading.md").exists() else ""}


@app.get("/api/essays/{job_id}/download")
def download(job_id: str, user=Depends(accounts.current_user)) -> FileResponse:
    job=accounts.owned_job(job_id,user)
    path = DATA / job_id / "graded.docx"
    if not path.exists():
        raise HTTPException(404, "批改文件尚未生成")
    accounts.audit(user["id"], "download", job['filename'])
    return FileResponse(path, filename=f"graded-{job_id[:8]}.docx", media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
