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
import hashlib
from contextvars import ContextVar
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit
from html import escape
from pathlib import Path
from typing import Any
from review_annotations import split_response, normalize_annotations, report_sections, parse_annotations, validate_evaluation, EVALUATION_HEADINGS
from xml.etree import ElementTree as ET

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, UploadFile, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from scripts.render_grading_docx import source_paragraphs, marked_paragraphs, validate_markdown_fidelity, validate_output_shape
from scripts.render_grading_docx import validate_complete_report, validate_source_docx, validate_docx, render

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.resolve()
load_dotenv(ROOT / '.env')
import accounts
import saas
import payments

CURRENT_JOB = ContextVar('current_job', default=None)

DATA = Path(os.getenv('ESSAY_DATA_DIR',str(ROOT / 'data')))
DATA.mkdir(exist_ok=True)
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}
META_LOCK = threading.RLock()

def read_meta(path: Path) -> dict[str, Any]:
    with META_LOCK:
        return json.loads(path.read_text(encoding="utf-8"))

def write_meta(path: Path, meta: dict[str, Any] | list) -> None:
    with META_LOCK:
        temporary = path.with_suffix(path.suffix + '.tmp')
        temporary.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)

def grading_marker() -> str:
    text = (ROOT / "scripts" / "render_grading_docx.py").read_text(encoding="utf-8")
    match = re.search(r'line\.strip\(\) == "([^"]+)"', text)
    if not match:
        raise RuntimeError("无法读取渲染脚本的原文标记")
    return match.group(1)
app = FastAPI(title="Essay Grading Studio", version="0.1.0")
accounts.initialize()
app.include_router(accounts.router)
app.include_router(saas.router)
app.include_router(payments.router)
import credit_payments
app.include_router(credit_payments.router)
import manual_payments
app.include_router(manual_payments.router)
import review_translation
app.include_router(review_translation.router)


class RequestBodyLimit:
    """Bound chunked uploads too, before multipart parsing spools to disk."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope.get('method') in ('GET', 'HEAD', 'OPTIONS'):
            await self.app(scope, receive, send)
            return
        path = scope.get('path', '')
        limit = 12 * 1024 * 1024 if path == '/api/essays' else 3 * 1024 * 1024 if re.fullmatch(r'/api/(?:admin/payments/manual/(?:wechat|alipay)/qr|orders/[a-f0-9]{32}/proof)', path) else 256 * 1024
        consumed = 0
        async def limited_receive():
            nonlocal consumed
            message = await receive()
            consumed += len(message.get('body', b''))
            if consumed > limit:
                raise HTTPException(413, '请求内容过大')
            return message
        await self.app(scope, limited_receive, send)


app.add_middleware(RequestBodyLimit)

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")

@app.middleware('http')
async def protect_requests(request: Request, call_next):
    if request.method == 'POST':
        try:
            if int(request.headers.get('content-length', '0')) > 12 * 1024 * 1024:
                return JSONResponse({'detail': '请求内容过大'}, status_code=413)
        except ValueError:
            return JSONResponse({'detail': '请求长度无效'}, status_code=400)
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin=request.headers.get('origin')
        callback = request.url.path in ('/api/payments/wechat/notify', '/api/payments/alipay/notify', '/api/payments/paypro/notify', '/api/payment/callback')
        if not callback and (request.headers.get('sec-fetch-site')=='cross-site' or (origin and urlsplit(origin).netloc!=request.url.netloc)):
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


@app.get('/pricing', response_class=HTMLResponse)
def pricing_page():
    return (ROOT / 'static' / 'saas.html').read_text(encoding='utf-8')


@app.get('/account', response_class=HTMLResponse)
@app.get('/orders', response_class=HTMLResponse)
def account_page(user=Depends(accounts.current_user)):
    return (ROOT / 'static' / 'saas.html').read_text(encoding='utf-8')


@app.get('/admin', response_class=HTMLResponse)
def admin_page(user=Depends(accounts.administrator)):
    return (ROOT / 'static' / 'saas.html').read_text(encoding='utf-8')

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
        if len(zf.infolist()) > 1000 or sum(info.file_size for info in zf.infolist()) > 40 * 1024 * 1024:
            raise ValueError('文档解压内容过大')
        if zf.getinfo('word/document.xml').file_size > 4 * 1024 * 1024:
            raise ValueError('文档正文过大')
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
    parts = []
    for i, paragraph in enumerate(essay, 1):
        marked = paragraph
        parts.extend([
            marker,
            marked,
            "#### 段落点评",
            f"Demo only: paragraph {i} feedback will assess its purpose and development using the actual essay.",
            "#### 语言提升",
            "Demo only: language feedback will explain evidence-based corrections and useful optional improvements.",
            "#### 问题建议",
            "Demo only: practice tasks will include specific completion checks based on the paragraph.",
        ])
    parts.append("#### 全文综合评价和提升建议")
    for heading in EVALUATION_HEADINGS:
        if heading == '综合评价':
            parts.append(f'**{heading}**')
            for label in ('Strengths', 'Improvement Suggestions', 'Enhancement Path', 'Action Plan'):
                parts.append(f'{label}: Demo only: actual feedback must be based on the essay.')
            continue
        if heading == 'Task Response｜任务回应':
            parts.append(f'**{heading}**')
            for label in ('Position and Argument Analysis', 'Evidence and Examples Assessment', 'Content and Structure Optimization Suggestions', 'Improvement Suggestions'):
                parts.append(f'{label}: Demo only: actual feedback must be based on the essay.')
            continue
        if heading == 'Coherence and Cohesion｜连贯与衔接':
            parts.append(f'**{heading}**')
            for label in ('Paragraph Structure', 'Linking Devices', 'Logical Flow', 'Specific Improvements', 'Practical Examples'):
                parts.append(f'{label}: Demo only: actual feedback must be based on the essay.')
            continue
        if heading == 'Lexical Resource｜词汇':
            parts.append(f'**{heading}**')
            for label in ('词汇范围', '精确度', '学术风格', '改进方向', '举个例子'):
                parts.append(f'{label}：Demo only: actual feedback must be based on the essay.')
            continue
        if heading == 'Grammatical Range and Accuracy｜语法':
            parts.append(f'**{heading}**')
            for label in ('Sentence Variety', 'Advanced Structures', 'Error Patterns', 'Specific Corrections', 'Progressive Improvement'):
                parts.append(f'{label}: Demo only: actual feedback must be based on the essay.')
            continue
        parts.extend([f'**{heading}**', f'分析点评：演示模式，此处展示{heading}的反馈位置，实际判断需结合原文。',
                      '修改建议：配置批改服务后，将根据本篇原文给出具体修改动作。'])
    parts.append("本篇文章打分估计为：18—21分。")
    parts.append("| 档次 | 内容 | 语言 | 组织结构 |\n|---|---|---|---|\n| A | 9–10 | 9–10 | [[red]]4–5[[/red]] |\n| B | [[red]]7–8[[/red]] | [[red]]7–8[[/red]] | 3 |\n| C | 5–6 | 5–6 | 2 |\n| D | 3–4 | 3–4 | 1 |\n| E | 0–2 | 0–2 | 0 |")
    return "\n\n".join(parts) + "\n"


def validate_report(text, paragraphs):
    """One contract for fresh, repaired and cached reports."""
    errors = []
    for check in (lambda: validate_markdown_fidelity(paragraphs, marked_paragraphs(text)),
                  lambda: validate_output_shape(text), lambda: validate_complete_report(text),
                  lambda: validate_evaluation(text),
                  lambda: review_translation.validate_english_feedback({'review': report_sections(text)})):
        try:
            check()
        except ValueError as error:
            errors.append(str(error))
    if errors:
        raise ValueError('\n'.join(errors))


def call_openai(source: str, *, channel: str = 'report'):
    if channel not in {'report', 'annotations'}:
        raise ValueError('Unknown grading channel')
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        if os.getenv('APP_ENV') == 'production':
            raise RuntimeError('批改服务暂不可用，请联系管理员')
        return ""
    try:
        import httpx
        from skill_prompt import build_grading_prompt
        prompt = build_grading_prompt(ROOT, channel)
        paragraphs = source_paragraphs(source) if "## Essay" in source else [source.strip()]
        report_annotations = None
        payload = {"paragraphs": paragraphs}
        if channel == 'report' and CURRENT_JOB.get():
            annotation_file = DATA / CURRENT_JOB.get() / 'annotations.json'
            if annotation_file.exists():
                report_annotations = json.loads(annotation_file.read_text(encoding='utf-8'))
        body = {
            "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            "max_output_tokens": int(os.getenv('AI_MAX_OUTPUT_TOKENS', '12000')),
            "store": False,
            "input": [{"role": "system", "content": prompt}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        }
        base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        from grading_contract import output_schema
        structured = os.getenv('AI_STRUCTURED_OUTPUT', 'auto').lower()
        if structured not in {'auto', '0', '1'}:
            raise ValueError('AI_STRUCTURED_OUTPUT must be auto, 0 or 1')
        if structured != '0':
            body['text'] = {'format': {'type': 'json_schema', 'name': 'essay_' + channel,
                                      'strict': True, 'schema': output_schema(channel)}}
        if len(json.dumps(body, ensure_ascii=False)) > int(os.getenv('AI_MAX_PROMPT_CHARS', '100000')):
            raise RuntimeError('批改输入过长，请缩短作文后重试')
        attempts = max(2, min(4, int(os.getenv('AI_FORMAT_ATTEMPTS', '3'))))
        for attempt in range(attempts):
            encoded_body = json.dumps(body, ensure_ascii=False).encode('utf-8')
            if len(encoded_body) > int(os.getenv('AI_MAX_PROMPT_CHARS', '100000')) * 4:
                raise RuntimeError('批改修复输入过长，请联系管理员')
            call_id = saas.start_call(CURRENT_JOB.get(), body['model'], urlsplit(base_url).netloc, len(encoded_body), body['max_output_tokens'])
            try:
                from ai_transport import request_response
                response = request_response(f"{base_url}/responses", key, body)
            except Exception as exc:
                saas.finish_call(call_id, getattr(exc, 'data', None), getattr(exc, 'response', None), error=getattr(exc, 'reason', type(exc).__name__))
                if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
                    with accounts.database() as db:
                        db.execute("UPDATE ai_calls SET status='failed',error_code='connection_not_submitted' WHERE id=?", (call_id,))
                    raise RuntimeError('AI 连接失败，请稍后重试；原始作文已保留') from None
                if CURRENT_JOB.get():
                    progress = getattr(exc, 'data', None)
                    if progress:
                        interrupted = DATA / CURRENT_JOB.get() / 'ai-interrupted'
                        interrupted.mkdir(exist_ok=True)
                        (interrupted / (call_id + '.json')).write_text(json.dumps(progress, ensure_ascii=False), encoding='utf-8')
                    with accounts.database() as db:
                        db.execute('UPDATE jobs SET ai_uncertain=1 WHERE id=?', (CURRENT_JOB.get(),))
                raise RuntimeError('AI 调用结果待核查，原始作文已保留') from None
            try:
                data = response.json()
            except ValueError:
                data = {}
            saas.finish_call(call_id, data, response, error=f'http_{response.status_code}' if response.status_code >= 400 else None)
            from grading_contract import schema_unsupported
            if (structured == 'auto' and attempt == 0 and 'text' in body
                    and schema_unsupported(response.status_code, data)):
                logger.warning('Provider explicitly rejected JSON Schema; keeping local JSON validation')
                body.pop('text')
                continue
            if response.status_code == 429 and attempt == 0:
                try:
                    delay = max(1, min(30, float(response.headers.get('retry-after', '2'))))
                except ValueError:
                    delay = 2
                time.sleep(delay)
                continue
            response.raise_for_status()
            if data.get('status') in ('failed', 'incomplete'):
                raise RuntimeError('AI 输出未完成，已保留完成的批改；请稍后重试。')
            if any(content.get('type') == 'refusal' for item in data.get('output', [])
                   for content in item.get('content', [])):
                raise RuntimeError('AI 未返回批改内容，原始作文已保留。')
            text = data.get("output_text") or ""
            if not text:
                for item in data.get("output", []):
                    for content in item.get("content", []):
                        if content.get("type") in ("output_text", "text"):
                            text += content.get("text", "")
            if not text.strip():
                raise RuntimeError("API returned no grading text")
            raw_text = text
            try:
                if channel == 'annotations':
                    annotations = parse_annotations(text, paragraphs)
                    review_translation.validate_english_feedback({'annotations': annotations})
                    return annotations
                from grading_contract import parse_report, render_report
                structured_report = None
                if text.lstrip().startswith('#### '):
                    # Migration compatibility for old completed provider responses.
                    from report_normalization import normalize_report
                    from grading_protocol import repair_punctuation
                    text, _ = split_response(text, paragraphs)
                    text = normalize_report(text, paragraphs, report_annotations)
                    text = repair_punctuation(paragraphs, text)
                else:
                    structured_report = parse_report(text, paragraphs)
                    text = render_report(structured_report, paragraphs, report_annotations)
                validate_report(text, paragraphs)
                if structured_report is not None and CURRENT_JOB.get():
                    write_meta(DATA / CURRENT_JOB.get() / 'report.json', structured_report.model_dump())
                return text
            except ValueError as exc:
                logger.warning("AI grading format validation failed (attempt %s, type %s)", attempt + 1, type(exc).__name__)
                # Keep the completed provider output privately for repair without another billable call.
                if CURRENT_JOB.get():
                    rejected = DATA / CURRENT_JOB.get() / 'ai-rejected'
                    rejected.mkdir(exist_ok=True)
                    (rejected / (call_id + '.md')).write_text(raw_text, encoding='utf-8')
                    (rejected / (call_id + '.json')).write_text(json.dumps({'error': str(exc)[:6000]}, ensure_ascii=False), encoding='utf-8')
                with accounts.database() as db:
                    db.execute("UPDATE ai_calls SET status='format_error',error_code='format_validation' WHERE id=?", (call_id,))
                if attempt == attempts - 1:
                    raise RuntimeError("AI 批改格式校验失败，请重试；原始作文已保留。") from None
                # Keep only the latest candidate; repeated full reports inflated
                # repair requests and extended already fragile upstream streams.
                body['input'][2:] = [
                    {'role': 'assistant', 'content': raw_text},
                    {'role': 'user', 'content': (
                        'Repair the JSON to match the supplied schema. Return the complete JSON object only. '
                        'Keep valid feedback and grading decisions. All feedback prose must be English. '
                        + ('Use the annotations key; quote exact substrings of the input paragraphs. '
                           if channel == 'annotations' else
                           'Cover each paragraph once. Do not copy source paragraphs, headings or tables. ')
                        + 'Validation errors: ' + str(exc)[:6000])},
                ]
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"Grading API returned HTTP {exc.response.status_code}") from None
    except RuntimeError:
        raise
    except Exception:
        raise RuntimeError("Grading API request failed; check API configuration and connectivity") from None


def run_job(job_id: str, start: str | None) -> None:
    folder = DATA / job_id
    meta = read_meta(folder / "meta.json")
    owner = uuid.uuid4().hex
    with accounts.database() as db:
        registered = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
    if registered and not saas.claim(job_id, owner):
        return
    stop = threading.Event()
    def beat():
        while not stop.wait(30):
            try:
                if not saas.heartbeat(job_id, owner):
                    return
            except Exception:
                logger.exception('Task heartbeat failed for %s', job_id)
    if registered:
        threading.Thread(target=beat, daemon=True).start()
    def save():
        if registered:
            with accounts.database() as db:
                affected = db.execute('UPDATE jobs SET status=?,stage=?,error=?,updated=? WHERE id=? AND lease_owner=?', (meta['status'], meta['stage'], meta.get('error'), time.time(), job_id, owner)).rowcount
                if not affected:
                    raise RuntimeError('任务执行权已变更')
        write_meta(folder / 'meta.json', meta)
    token = CURRENT_JOB.set(job_id)
    try:
        meta.update(status="running", stage="extracting")
        save()
        essay = write_source_md(folder / "source.docx", folder / "source.md", start)
        source = (folder / "source.md").read_text(encoding="utf-8")
        meta.update(stage="grading")
        save()
        # Each channel has its own cache and lifecycle. Publishing annotations
        # does not depend on report validation or Word rendering.
        channels = meta.setdefault('channels', {})
        annotation_path = folder / 'annotations.json'
        if annotation_path.exists():
            channels['annotations'] = 'ready'
        else:
            channels['annotations'] = 'running'
            save()
            try:
                items = call_openai(source, channel='annotations') if os.getenv('OPENAI_API_KEY') else []
                if not isinstance(items, list):
                    raise ValueError('词句批注返回类型无效')
                write_meta(annotation_path, items)
                channels['annotations'] = 'ready'
            except Exception as exc:
                logger.warning('Independent annotation channel failed for %s', job_id)
                channels['annotations'] = 'failed'
                meta.setdefault('channel_errors', {})['annotations'] = str(exc)
            save()
        channels['report'] = 'running'
        save()
        cached = folder / 'grading.md'
        grading = ''
        structured_cache = folder / 'report.json'
        if structured_cache.exists():
            try:
                from grading_contract import parse_report, render_report
                report = parse_report(structured_cache.read_text(encoding='utf-8'), essay)
                grading = render_report(report, essay, read_meta(annotation_path) if annotation_path.exists() else None)
                validate_report(grading, essay)
            except ValueError:
                grading = ''
        if not grading and cached.exists():
            candidate = cached.read_text(encoding='utf-8')
            try:
                from report_normalization import normalize_report
                candidate = normalize_report(candidate, essay, read_meta(annotation_path) if annotation_path.exists() else None)
                validate_report(candidate, essay)
                grading = candidate
            except ValueError:
                pass
        if not grading:
            grading = call_openai(source)
            if not grading:
                grading = mock_grading(essay)
                meta['is_demo'] = True
                if registered:
                    with accounts.database() as db:
                        db.execute('UPDATE jobs SET is_demo=1 WHERE id=?', (job_id,))
        validate_report(grading, essay)
        temporary = folder / 'grading.md.tmp'
        temporary.write_text(grading, encoding='utf-8')
        temporary.replace(folder / 'grading.md')
        channels['report'] = 'ready'
        meta.update(stage="rendering")
        save()
        subprocess.run([sys.executable, str(ROOT / "scripts" / "render_grading_docx.py"), "--source-docx", str(folder / "source.docx"), "--source-md", str(folder / "source.md"), "--grading-md", str(folder / "grading.md"), "--output-docx", str(folder / "graded.docx")], check=True, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        if os.getenv('OPENAI_API_KEY') and not meta.get('is_demo'):
            channels['translation'] = 'running'
            meta.update(stage='translating')
            save()
            try:
                translation_preview = {'annotations': json.loads(annotation_path.read_text(encoding='utf-8')) if annotation_path.exists() else [],
                                       'review': report_sections(grading)}
                review_translation.prepare_translations(folder, translation_preview, job_id)
                channels['translation'] = 'ready'
            except Exception:
                logger.warning('Prepared translation failed for %s; English grading retained', job_id)
                channels['translation'] = 'failed'
        if os.getenv('REQUIRE_ANNOTATIONS', '0') == '1' and channels.get('annotations') != 'ready':
            raise RuntimeError('词句批改未完成，全文报告已保留；请重试补齐词句批改。')
        meta.pop('channel_errors', None)
        meta.update(status="succeeded", stage="done")
        meta.pop("error", None)
    except subprocess.CalledProcessError as exc:
        logger.error("DOCX rendering failed for job %s (exit %s)", job_id, exc.returncode)
        meta.update(status="failed", stage="error", error="批改文档生成失败，请重试；原始作文已保留。")
    except Exception as exc:
        meta.update(status="failed", stage="error", error=str(exc))
    finally:
        for channel, state in meta.get('channels', {}).items():
            if state == 'running':
                meta['channels'][channel] = 'failed'
        stop.set()
        CURRENT_JOB.reset(token)
    if registered:
        with accounts.database() as db:
            affected = db.execute('UPDATE jobs SET status=?,stage=?,error=?,updated=?,lease_owner=NULL,lease_until=NULL WHERE id=? AND lease_owner=?', (meta['status'], meta['stage'], meta.get('error'), time.time(), job_id, owner)).rowcount
            if not affected:
                return
            saas.settle(db, job_id, meta['status'] == 'succeeded')
    write_meta(folder / "meta.json", meta)
    if meta.get("user_id"):
        accounts.audit(meta["user_id"], meta["status"], meta.get("filename", job_id))


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    page=(ROOT / "static" / "landing.html").read_text(encoding="utf-8")
    return page.replace('rel="canonical" href="/"',f'rel="canonical" href="{escape(PUBLIC_BASE_URL,quote=True)}/"')


@app.post("/api/essays")
async def create_essay(request: Request, background: BackgroundTasks, file: UploadFile = File(...), start: str | None = Form(None), user=Depends(accounts.current_user)) -> dict[str, Any]:
    saas.rate_limit(request, user['id'], 'submit', 10)
    if not file.filename or not file.filename.lower().endswith(".docx"):
        raise HTTPException(400, "仅支持 .docx 文件")
    content = await file.read(10 * 1024 * 1024 + 1)
    if not content or len(content) > 10 * 1024 * 1024:
        raise HTTPException(413, "文件不能超过 10 MB")
    if start and len(start) > 8000:
        raise HTTPException(400, '首段定位文字过长')
    key = request.headers.get('Idempotency-Key')
    if os.getenv('APP_ENV') == 'production' and not key:
        raise HTTPException(400, '缺少提交幂等键，请刷新页面后重试')
    key = key or uuid.uuid4().hex
    if not 8 <= len(key) <= 128:
        raise HTTPException(400, '提交幂等键无效')
    content_hash = hashlib.sha256(content + b'\x00' + (start or '').encode()).hexdigest()
    with accounts.database() as db:
        prior = db.execute('SELECT * FROM jobs WHERE user_id=? AND request_key=?', (user['id'], key)).fetchone()
    if prior:
        if prior['content_hash'] != content_hash:
            raise HTTPException(409, '同一提交键不能用于不同作文')
        return saas.public_job(prior)
    if os.getenv('APP_ENV') == 'production' and not os.getenv('OPENAI_API_KEY'):
        raise HTTPException(503, '批改服务暂未开放')
    job_id = uuid.uuid4().hex
    folder = DATA / job_id
    folder.mkdir()
    try:
        (folder / 'source.docx').write_bytes(content)
        essay = write_source_md(folder / 'source.docx', folder / 'source.md', start)
        if sum(map(len, essay)) > int(os.getenv('ESSAY_MAX_CHARS', '20000')) or len(essay) > 100:
            raise ValueError('作文过长，请控制在 20000 字符及 100 段以内')
        with accounts.database() as db:
            prior = db.execute('SELECT * FROM jobs WHERE user_id=? AND request_key=?', (user['id'], key)).fetchone()
            if prior:
                if prior['content_hash'] != content_hash:
                    raise HTTPException(409, '同一提交键不能用于不同作文')
                for name in ('source.docx', 'source.md'):
                    (folder / name).unlink(missing_ok=True)
                folder.rmdir()
                return saas.public_job(prior)
            period = saas.reserve(db, user['id'], job_id)
            now = time.time()
            db.execute('INSERT INTO jobs(id,user_id,filename,start,created,updated,request_key,content_hash,quota_period_id,quota_state) VALUES(?,?,?,?,?,?,?,?,?,?)', (job_id,user['id'],file.filename,start,now,now,key,content_hash,period,'reserved'))
            meta = {'id':job_id,'filename':file.filename,'status':'queued','stage':'queued','user_id':user['id'],'created':now}
            write_meta(folder / 'meta.json', meta)
    except Exception as exc:
        for name in ('source.docx', 'source.md', 'meta.json'):
            (folder / name).unlink(missing_ok=True)
        folder.rmdir()
        if isinstance(exc, HTTPException):
            raise
        if isinstance(exc, (ValueError, KeyError, zipfile.BadZipFile, ET.ParseError)):
            raise HTTPException(400, '文档无效：' + str(exc)[:200]) from None
        raise
    accounts.audit(user["id"], "upload", file.filename)
    if os.getenv('INLINE_WORKER', '1') == '1' and os.getenv('APP_ENV') != 'production':
        background.add_task(run_job, job_id, start)
    return meta


@app.get("/api/essays/{job_id}")
def get_essay(job_id: str, user=Depends(accounts.current_user)) -> dict[str, Any]:
    return saas.public_job(accounts.owned_job(job_id,user))


@app.get("/api/essays")
def list_essays(user=Depends(accounts.current_user)) -> list[dict[str, Any]]:
    with accounts.database() as db:
        return [saas.public_job(row) for row in db.execute('SELECT * FROM jobs WHERE user_id=? ORDER BY created DESC LIMIT 500', (user['id'],))]


@app.post("/api/essays/{job_id}/retry")
def retry_essay(job_id: str, request: Request, background: BackgroundTasks, user=Depends(accounts.current_user)) -> dict[str, Any]:
    saas.rate_limit(request, user['id'], 'retry', 5)
    job=accounts.owned_job(job_id,user)
    folder = DATA / job_id
    meta_path = folder / "meta.json"
    if not meta_path.exists() or not (folder / "source.docx").exists():
        raise HTTPException(404, "任务不存在")
    meta = read_meta(meta_path)
    with accounts.database() as db:
        current = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if current['status'] != 'failed' or current['ai_uncertain'] or current['attempts'] >= 3:
            raise HTTPException(409,'仅可重试已确认失败且未超过重试上限的任务')
        if current['quota_state'] == 'committed':
            raise HTTPException(409, '已完成交付的任务不可重复扣费重试')
        # Ledger uniqueness is scoped to each submission attempt.
        period = saas.reserve(db, user['id'], job_id, current['attempts'] + 1)
        db.execute("UPDATE jobs SET status='queued',stage='queued',error=NULL,quota_period_id=?,quota_state='reserved',lease_owner=NULL,lease_until=NULL WHERE id=?", (period, job_id))
    meta.update(status="queued", stage="queued", error=None)
    write_meta(meta_path, meta)
    accounts.audit(user["id"], "retry", meta.get("filename",""))
    if os.getenv('INLINE_WORKER', '1') == '1' and os.getenv('APP_ENV') != 'production':
        background.add_task(run_job, job_id, job['start'])
    return meta


@app.get("/api/essays/{job_id}/preview")
def preview(job_id: str, user=Depends(accounts.current_user)) -> dict[str, Any]:
    job=accounts.owned_job(job_id,user)
    accounts.audit(user['id'],'preview',job['filename'])
    folder = DATA / job_id
    if not (folder / "meta.json").exists():
        raise HTTPException(404, "任务不存在")
    source = (folder / 'source.md').read_text(encoding='utf-8') if (folder / 'source.md').exists() else ''
    grading = (folder / 'grading.md').read_text(encoding='utf-8') if (folder / 'grading.md').exists() else ''
    paragraphs = source_paragraphs(source) if source else []
    meta = read_meta(folder / 'meta.json')
    channels = meta.get('channels', {})
    annotations = []
    if (folder / 'annotations.json').exists():
        try:
            saved = json.loads((folder / 'annotations.json').read_text(encoding='utf-8'))
            # Re-anchor persisted data; never trust stale offsets.
            for item in saved:
                if isinstance(item, dict) and type(item.get('paragraph')) is int and 1 <= item['paragraph'] <= len(paragraphs):
                    prefix = paragraphs[item['paragraph'] - 1][:item.get('start', 0)]
                    item['occurrence'] = prefix.count(item.get('quote', '')) + 1
            annotations = normalize_annotations(saved, paragraphs)
        except (ValueError, TypeError):
            pass
    prompt = ''
    if paragraphs and (folder / 'source.docx').exists():
        original = paragraphs_from_docx(folder / 'source.docx')
        if paragraphs[0] in original:
            prompt = '\n\n'.join(original[:original.index(paragraphs[0])])
        if not prompt:
            prefix = []
            for paragraph in paragraphs:
                if re.search(r'[\u4e00-\u9fff]', paragraph) or re.match(r'^(?:Task|Topic|题目|作文要求)[:：\s]', paragraph, re.I):
                    prefix.append(paragraph)
                else:
                    break
            prompt = '\n\n'.join(prefix)
    review = report_sections(grading)
    # Word keeps its language explanations; the paragraph UI owns only content,
    # logic and training. Vocabulary remains a separate projection for old reports.
    language = [{'paragraph': i + 1, 'text': feedback['text']}
                for i, part in enumerate(review['paragraphs']) for feedback in part['feedback']
                if feedback['title'] == '语言提升']
    for i, part in enumerate(review['paragraphs']):
        part['paragraph'] = i + 1
        part['feedback'] = [f for f in part['feedback'] if f['title'] != '语言提升']
    translations = review_translation.saved_translations(folder, {'annotations': annotations, 'review': review})
    return {'source': source, 'grading': grading, 'original': paragraphs, 'prompt': prompt,
            'translations': translations,
            'annotations': annotations, 'review': review, 'language_learning': language,
            'channels': {
                'annotations': channels.get('annotations', 'ready' if (folder / 'annotations.json').exists() else 'unavailable'),
                'report': channels.get('report', 'ready' if grading else 'pending'),
            }}


@app.get("/api/essays/{job_id}/download")
def download(job_id: str, user=Depends(accounts.current_user)) -> FileResponse:
    job=accounts.owned_job(job_id,user)
    folder = DATA / job_id
    meta_path = folder / "meta.json"
    if not meta_path.exists():
        raise HTTPException(404, "任务不存在")
    if job['status'] != "succeeded":
        raise HTTPException(409, "批改尚未完成，暂时无法下载完整报告")
    path = folder / "graded.docx"
    if not path.exists():
        raise HTTPException(404, "批改文件尚未生成")
    try:
        source = source_paragraphs((folder / "source.md").read_text(encoding="utf-8"))
        grading = (folder / "grading.md").read_text(encoding="utf-8")
        validate_source_docx(folder / "source.docx", source)
        validate_markdown_fidelity(source, marked_paragraphs(grading))
        validate_output_shape(grading)
        validate_complete_report(grading)
        _, expected = render(grading)
        validate_docx(path, source, grading, expected)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, ET.ParseError):
        logger.exception("Download validation failed for job %s", job_id)
        raise HTTPException(409, "报告不完整或文件已损坏，请重新上传作文生成完整报告") from None
    accounts.audit(user["id"], "download", job['filename'])
    stem = Path(job['filename'].replace('\\', '/')).stem
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', '_', stem).strip(' .')[:100] or '作文'
    return FileResponse(path, filename=f"{stem}-完整批改报告.docx", media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
