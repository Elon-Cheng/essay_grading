"""Jamjams IPC watchdog: wait for the app, probe, and switch unhealthy nodes."""
import argparse
import csv
import io
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit

import httpx
from websockets.sync.client import connect


LOG = logging.getLogger('jamjams_watchdog')


class IPCError(RuntimeError):
    pass


class Jamjams:
    def __init__(self, url):
        self.url = url

    def call(self, method, params=None):
        # Context-managed connections work with websockets >= 15.
        with connect(self.url, open_timeout=5, close_timeout=2,
                     max_size=2_000_000, proxy=None) as websocket:
            websocket.send(json.dumps({'cid': 1, 'type': 0, 'method': method, 'params': params or {}}))
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                message = json.loads(websocket.recv(timeout=max(.1, deadline - time.monotonic())))
                if message.get('type') == 0:
                    websocket.send(json.dumps({'cid': message.get('cid'), 'type': 1, 'result': None}))
                elif message.get('type') == 1 and message.get('cid') == 1:
                    if message.get('error'):
                        # The app error can include subscription details. Never log it.
                        raise IPCError('Jamjams rejected IPC command')
                    return message.get('result')
        raise IPCError('Jamjams IPC timeout')


def running():
    if sys.platform != 'win32':
        return False
    result = subprocess.run(['tasklist.exe', '/FI', 'IMAGENAME eq Jamjams.exe', '/FO', 'CSV', '/NH'],
                            capture_output=True, timeout=8, creationflags=subprocess.CREATE_NO_WINDOW)
    rows = csv.reader(io.StringIO(result.stdout.decode(errors='replace')))
    return any(row and row[0].lower() == 'jamjams.exe' for row in rows)


def validate_ipc(value):
    try:
        parsed = urlsplit(value)
        if (parsed.scheme == 'ws' and parsed.hostname in ('127.0.0.1', 'localhost', '::1')
                and parsed.port and parsed.path == '/ipc' and not parsed.username
                and not parsed.password and not parsed.query and not parsed.fragment):
            return value
    except ValueError:
        pass
    raise argparse.ArgumentTypeError('IPC must be a loopback ws://host:port/ipc URL')


def probe(state):
    proxy = state['settings']['proxy']
    # HTTP CONNECT verified on the supplied Jamjams; fail closed on other protocols.
    port = int(proxy['port'])
    address = proxy.get('address', '127.0.0.1')
    if not 1 <= port <= 65535 or address not in ('127.0.0.1', 'localhost', '::1', '0.0.0.0'):
        raise IPCError('Unsupported local proxy listener')
    started = time.monotonic()
    try:
        with httpx.Client(proxy=f'http://127.0.0.1:{port}', trust_env=False,
                          timeout=httpx.Timeout(10, connect=5)) as client:
            response = client.get('https://www.su8.codes/v1/models')
        if response.status_code == 401 or 200 <= response.status_code < 300:
            return 'healthy', round(time.monotonic() - started, 3)
        # 429/5xx/403 are HTTP responses, not proof of a broken proxy node.
        return 'upstream_http', response.status_code
    except httpx.HTTPError:
        return 'network_failure', None


class Watchdog:
    def __init__(self, api, threshold=3, cooldown=300, settle=4, clock=time.monotonic, sleep=time.sleep):
        self.api = api
        self.threshold, self.cooldown, self.settle = threshold, cooldown, settle
        self.clock, self.sleep = clock, sleep
        self.failures = 0
        self.last_switch = float('-inf')
        self.selected = None

    def reset(self):
        self.failures = 0
        self.selected = None
        self.last_switch = float('-inf')

    def tick(self):
        state = self.api.call('getState')
        if not isinstance(state, dict):
            raise IPCError('Unexpected Jamjams state')
        if not state.get('isLoggedIn') or not state.get('isProxyEnabled'):
            self.failures = 0
            return {'status': 'paused'}
        account = state['account']
        nodes = account['servers']
        original = account['selectedServer']['id']
        if self.selected != original:
            if self.selected is not None:
                self.last_switch = self.clock()  # Respect a user's manual node change.
            self.failures = 0
            self.selected = original
        outcome, detail = probe(state)
        if outcome != 'network_failure':
            self.failures = 0
            return {'status': outcome, 'detail': detail}
        self.failures += 1
        if self.failures < self.threshold or self.clock() - self.last_switch < self.cooldown:
            return {'status': 'network_failure', 'consecutive': self.failures}
        # Do not assume checkStatus alone guarantees access to the target API.
        self.last_switch = self.clock()
        for index, node in enumerate(nodes):
            if node['id'] == original:
                continue
            result = self.api.call('checkStatus', {'server_id': node['id']})
            if not isinstance(result, dict) or result.get('status') != 2:
                continue
            self.api.call('changeServer', {'server_id': node['id']})
            self.selected = node['id']
            self.last_switch = self.clock()
            LOG.warning('Testing backup node position=%s', index + 1)
            try:
                self.sleep(self.settle)
                fresh = self.api.call('getState')
                if not fresh.get('isProxyEnabled'):
                    return {'status': 'paused'}
                # Stop if a user changed the node while we were checking.
                if fresh['account']['selectedServer']['id'] != node['id']:
                    self.selected = fresh['account']['selectedServer']['id']
                    self.failures = 0
                    return {'status': 'manual_change'}
                candidate, _ = probe(fresh)
            except Exception:
                # Roll back only when we can verify the currently selected node.
                current = self.api.call('getState')
                if current['account']['selectedServer']['id'] == node['id']:
                    self.api.call('changeServer', {'server_id': original})
                    self.selected = original
                raise
            if candidate == 'healthy':
                self.failures = 0
                return {'status': 'switched', 'position': index + 1}
            self.api.call('changeServer', {'server_id': original})
            self.selected = original
            if candidate == 'upstream_http':
                self.failures = 0
                return {'status': 'upstream_http'}
        return {'status': 'no_healthy_backup'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ipc-url', type=validate_ipc, default='ws://127.0.0.1:15734/ipc')
    parser.add_argument('--interval', type=int, default=30)
    parser.add_argument('--threshold', type=int, default=3)
    parser.add_argument('--cooldown', type=int, default=300)
    parser.add_argument('--inspect', action='store_true', help='Read-only IPC compatibility check; no probes or switches')
    parser.add_argument('--log-dir', type=Path, default=Path(__file__).resolve().parents[1] / 'logs')
    args = parser.parse_args()
    if args.interval < 10 or args.threshold < 2 or args.cooldown < 60:
        parser.error('interval >= 10, threshold >= 2, cooldown >= 60')
    api = Jamjams(args.ipc_url)
    if args.inspect:
        state = api.call('getState')
        proxy = state.get('settings', {}).get('proxy', {})
        print(json.dumps({'ipc_compatible': isinstance(state, dict),
                          'logged_in': state.get('isLoggedIn'), 'proxy_enabled': state.get('isProxyEnabled'),
                          'node_count': len(state.get('account', {}).get('servers', [])),
                          'local_proxy_port': proxy.get('port')}, indent=2))
        return
    args.log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(args.log_dir / 'jamjams-watchdog.log', maxBytes=1_000_000,
                                 backupCount=3, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    LOG.addHandler(handler)
    LOG.setLevel(logging.INFO)
    watchdog = Watchdog(api, args.threshold, args.cooldown)
    active = False
    # Startup task runs this lightweight monitor; node controls activate only while Jamjams runs.
    while True:
        try:
            if not running():
                if active:
                    LOG.info('Jamjams stopped; waiting for next launch')
                active = False
                watchdog.reset()
                time.sleep(5)
                continue
            if not active:
                LOG.info('Jamjams launch detected; controller active')
                active = True
            result = watchdog.tick()
            LOG.info('Check %s', json.dumps(result))
            time.sleep(args.interval)
        except KeyboardInterrupt:
            return
        except Exception as error:
            LOG.warning('Check failed: %s', type(error).__name__)
            time.sleep(10)


if __name__ == '__main__':
    main()
