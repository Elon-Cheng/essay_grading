"""Check OpenAI connectivity from the machine running this script; never print keys."""
import argparse
import os
import platform
import socket
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from dotenv import load_dotenv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generate', action='store_true', help='Send a small billable Responses request')
    parser.add_argument('--direct', action='store_true', help='Ignore environment proxies')
    args = parser.parse_args()
    load_dotenv(Path(__file__).resolve().parents[1] / '.env', override=False)
    base = os.getenv('OPENAI_BASE_URL', 'https://api.openai.com/v1').rstrip('/')
    model = os.getenv('OPENAI_MODEL', 'gpt-4.1-mini')
    key = os.getenv('OPENAI_API_KEY', '')
    parsed = urlsplit(base)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        print('FAIL: invalid base URL (expected an HTTP(S) URL without credentials or query)')
        return 1
    print('Machine:', platform.node())
    print('Base URL:', base)
    print('Model:', model)
    print('API key configured:', bool(key))
    print('Use environment proxies:', not args.direct)
    print('Proxy variables present:', ', '.join(n for n in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY') if os.getenv(n)) or 'none')
    try:
        addresses = sorted({item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80), type=socket.SOCK_STREAM)})
        print('DNS:', ', '.join(addresses))
    except OSError as exc:
        print('DNS failed:', type(exc).__name__)

    def request(client, label, method, url, **kwargs):
        start = time.monotonic()
        try:
            response = client.request(method, url, **kwargs)
            print(f'{label}: HTTP {response.status_code}, {time.monotonic() - start:.2f}s')
            # Error bodies may contain credentials; report only status and exception type.
            return response
        except httpx.HTTPError as exc:
            print(f'{label}: {type(exc).__name__}, {time.monotonic() - start:.2f}s')
            return None

    with httpx.Client(timeout=httpx.Timeout(20, connect=10), trust_env=not args.direct) as client:
        official = request(client, 'Official API (no key)', 'GET', 'https://api.openai.com/v1/models')
        print('Official transport reachable:', official is not None)
        if not key:
            print('Configured API authentication: skipped (no key; app uses demo grading)')
            return 1
        headers = {'Authorization': f'Bearer {key}'}
        models = request(client, 'Configured API models', 'GET', base + '/models', headers=headers)
        if models is not None and models.status_code == 200:
            try:
                ids = {item.get('id') for item in models.json().get('data', [])}
                print('Configured model listed:', model in ids)
            except (ValueError, AttributeError, TypeError):
                print('Models response is not a standard model list')
        if args.generate:
            response = request(client, 'Configured Responses API', 'POST', base + '/responses', headers=headers,
                               json={'model': model, 'input': 'Reply with OK only.', 'max_output_tokens': 64}, timeout=120)
            if response is not None and response.is_success:
                try:
                    data = response.json()
                    has_text = bool(data.get('output_text')) or any(
                        part.get('text') for item in data.get('output', [])
                        for part in item.get('content', []) if part.get('type') in ('output_text', 'text'))
                    print('Response status:', data.get('status'))
                    print('Generated text present:', has_text)
                    return 0 if has_text else 1
                except (ValueError, AttributeError, TypeError):
                    print('Responses body is not in the expected format')
            return 1
        print('Generation skipped; use --generate to verify real model calls (small API charge).')
        return 0 if models is not None and models.status_code == 200 else 1


if __name__ == '__main__':
    raise SystemExit(main())
