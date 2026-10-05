"""Compare SU8 transport routes without sending credentials or generating tokens."""
import argparse
import concurrent.futures
import json
import shutil
import statistics
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--count', type=int, default=10)
    parser.add_argument('--port', type=int, default=1080)
    args = parser.parse_args()
    if not 1 <= args.count <= 100 or not 1 <= args.port <= 65535:
        parser.error('count must be 1..100 and port 1..65535')
    curl = shutil.which('curl.exe') or shutil.which('curl')
    if not curl:
        parser.error('curl is required')
    routes = {
        'direct': ['--noproxy', '*'],
        'http_proxy': ['--noproxy', '', '--proxy', f'http://127.0.0.1:{args.port}'],
        'socks_proxy': ['--noproxy', '', '--proxy', f'socks5h://127.0.0.1:{args.port}'],
        'environment': [],
    }

    def probe(item):
        name, options = item
        samples = []
        for _ in range(args.count):
            result = subprocess.run(
                [curl, '--disable', '--silent', '--show-error', '--output',
                 'NUL' if curl.lower().endswith('.exe') else '/dev/null',
                 '--connect-timeout', '6', '--max-time', '12', *options,
                 '--write-out', '%{http_code} %{time_total}',
                 'https://www.su8.codes/v1/models'],
                capture_output=True, text=True, timeout=15,
            )
            fields = result.stdout.split()
            samples.append({
                'curl_exit': result.returncode,
                'http': int(fields[0]) if fields else 0,
                'seconds': float(fields[1]) if len(fields) == 2 else None,
            })
        valid = [s['seconds'] for s in samples
                 if s['curl_exit'] == 0 and s['http'] == 401]
        return {'route': name, 'expected_401': len(valid), 'count': args.count,
                'median_seconds': round(statistics.median(valid), 3) if valid else None,
                'samples': samples}

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(probe, routes.items()))
    print(json.dumps({'note': '401 is expected without a key; this does not test generation.',
                      'results': results}, indent=2))
    return 0 if all(r['expected_401'] == args.count for r in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
