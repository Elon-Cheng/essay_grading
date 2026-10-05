"""Compare direct and HTTP proxy routes on the server without keys or generation."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time

import httpx
from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[1]


def probe(route, options, count, interval):
    samples = []
    consecutive = longest = 0
    with httpx.Client(timeout=httpx.Timeout(12, connect=6), **options) as client:
        for index in range(count):
            started = time.monotonic()
            sample = {'sample': index + 1}
            try:
                response = client.get('https://www.su8.codes/v1/models')
                sample['http'] = response.status_code
                sample['reachable'] = response.status_code == 401
            except httpx.HTTPError as error:
                sample.update(reachable=False, error=type(error).__name__)
            sample['seconds'] = round(time.monotonic() - started, 3)
            samples.append(sample)
            consecutive = 0 if sample['reachable'] else consecutive + 1
            longest = max(longest, consecutive)
            if index + 1 < count and interval:
                time.sleep(interval)
    times = sorted(s['seconds'] for s in samples if s['reachable'])
    return {'route': route, 'success': len(times), 'count': count,
            'longest_failure_run': longest,
            'median_seconds': statistics.median(times) if times else None,
            'p95_seconds': times[max(0, math.ceil(len(times) * .95) - 1)] if times else None,
            'samples': samples}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--count', type=int, default=30)
    parser.add_argument('--interval', type=float, default=5)
    parser.add_argument('--port', type=int, default=1080)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if not 1 <= args.count <= 120 or not 0 <= args.interval <= 30 or not 1 <= args.port <= 65535:
        parser.error('count=1..120, interval=0..30, port=1..65535')
    config = {**dotenv_values(args.root / '.env'), **os.environ}
    sys.path.insert(0, str(ROOT))
    from backend.ai_transport import connection_options
    # Only these routing options are used; never load or send the API key.
    try:
        configured = connection_options(config)
    except ValueError:
        parser.error('Invalid AI_PROXY_URL; use an HTTP CONNECT proxy URL with a port')
    route_name = ('explicit_proxy' if configured.get('proxy') else
                  'environment' if configured['trust_env'] else 'direct')
    routes = [('direct', {'trust_env': False}),
              ('local_http_proxy', {'proxy': f'http://127.0.0.1:{args.port}', 'trust_env': False}),
              ('configured_ai_route', configured)]
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(probe, name, options, args.count, args.interval) for name, options in routes]
        results = [future.result() for future in futures]
    report = {'configured_ai_route': route_name,
              'stream_enabled': config.get('AI_STREAM', '0') == '1',
              'note': 'Expected unauthenticated 401 proves short-request reachability only. '
                      'No generation, node switching, or running-worker inspection performed.',
              'results': results}
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + '\n', encoding='utf-8')
    print(rendered)
    return 0 if results[2]['success'] == args.count else 1


if __name__ == '__main__':
    raise SystemExit(main())
