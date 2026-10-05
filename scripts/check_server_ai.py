"""Read-only server diagnostics. No generation calls, secrets or essay text printed."""
import argparse
import json
import os
from pathlib import Path
import socket
import sqlite3
import time
from urllib.parse import urlsplit

import httpx
from dotenv import load_dotenv


def emit(section, data):
    print(json.dumps({'section': section, 'data': data}, ensure_ascii=True), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    load_dotenv(args.root / '.env', override=False)
    base = os.getenv('OPENAI_BASE_URL', '').rstrip('/')
    parsed = urlsplit(base)
    # Never send the production key to an unexpected host during this diagnostic.
    if parsed.scheme != 'https' or parsed.netloc != 'www.su8.codes' or parsed.path != '/v1' or parsed.query or parsed.fragment:
        parser.error('Expected OPENAI_BASE_URL=https://www.su8.codes/v1')
    key = os.getenv('OPENAI_API_KEY', '')
    emit('config', {'base_url': base, 'key_present': bool(key),
                    'model': os.getenv('OPENAI_MODEL'),
                    'timeout_seconds': os.getenv('AI_TIMEOUT_SECONDS', '120'),
                    'stream_enabled': os.getenv('AI_STREAM', '0') == '1',
                    'reasoning_effort': os.getenv('AI_REASONING_EFFORT', '') or 'provider_default',
                    'ai_trust_env': os.getenv('AI_TRUST_ENV', '1') == '1',
                    'explicit_ai_proxy_configured': bool(os.getenv('AI_PROXY_URL', '').strip()),
                    'connect_timeout_seconds': os.getenv('AI_CONNECT_TIMEOUT_SECONDS', '10'),
                    'total_timeout_seconds': os.getenv('AI_TOTAL_TIMEOUT_SECONDS', '600'),
                    'proxy_variables_present': [k for k in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY') if os.getenv(k)],
                    'note': 'Diagnostic process environment; not the running worker environment.'})
    try:
        emit('dns', sorted({r[4][0] for r in socket.getaddrinfo(parsed.hostname, 443)}))
    except OSError as exc:
        emit('dns_error', type(exc).__name__)
    for trust in (False, True):
        with httpx.Client(trust_env=trust, timeout=httpx.Timeout(15, connect=6), follow_redirects=False) as client:
            for _ in range(3):
                started = time.monotonic()
                result = {'route': 'environment' if trust else 'direct'}
                try:
                    response = client.get(base + '/models', headers={'Authorization': 'Bearer ' + key} if key else {})
                    result['http_status'] = response.status_code
                except httpx.HTTPError as exc:
                    result['error_type'] = type(exc).__name__
                result['seconds'] = round(time.monotonic() - started, 3)
                emit('models_probe', result)
    db = None
    try:
        url = os.getenv('DATABASE_URL', '')
        if url.startswith(('postgresql://', 'postgres://')):
            import psycopg
            from psycopg.rows import dict_row
            db = psycopg.connect(url, row_factory=dict_row, connect_timeout=6)
            db.execute('SET TRANSACTION READ ONLY')
            db.execute("SET LOCAL statement_timeout = '5s'")
        else:
            path = Path(os.getenv('ESSAY_DATA_DIR', str(args.root / 'data'))) / 'accounts.sqlite3'
            db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA query_only=ON')
        for section, query in (
            ('recent_ai_calls', 'SELECT id,job_id,model,returned_model,request_id,started,latency_ms,status,error_code,input_tokens,output_tokens FROM ai_calls ORDER BY started DESC LIMIT 15'),
            ('job_counts', 'SELECT status,COUNT(*) AS count FROM jobs GROUP BY status'),
        ):
            emit(section, [dict(r) for r in db.execute(query).fetchall()])
    except Exception as exc:
        emit('database_error', type(exc).__name__)
    finally:
        if db is not None:
            db.rollback()
            db.close()


if __name__ == '__main__':
    main()
