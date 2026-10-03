"""Bounded Responses transport; interrupted streams are never submitted again."""
import json
import os
import time
from urllib.parse import urlsplit

import httpx


class StreamFailure(ValueError):
    def __init__(self, reason, response, data=None):
        super().__init__(reason)
        self.reason = reason
        self.response = response
        self.data = data or {}


def connection_options(config=None):
    """Explicit AI-only proxy overrides inherited proxy and NO_PROXY settings."""
    config = os.environ if config is None else config
    proxy = (config.get('AI_PROXY_URL') or '').strip()
    if proxy:
        try:
            parsed = urlsplit(proxy)
            valid = (parsed.scheme in ('http', 'https') and parsed.hostname
                     and parsed.port and parsed.path in ('', '/')
                     and not parsed.query and not parsed.fragment)
        except ValueError:
            valid = False
        if not valid:
            raise ValueError('AI_PROXY_URL must be an HTTP proxy URL with a port')
        return {'proxy': proxy, 'trust_env': False}
    return {'trust_env': config.get('AI_TRUST_ENV', '1') == '1'}


def request_response(url, key, body):
    effort = os.getenv('AI_REASONING_EFFORT', '')
    if effort:
        if effort not in ('none', 'low', 'medium', 'high', 'xhigh'):
            raise ValueError('Invalid AI_REASONING_EFFORT')
        body = {**body, 'reasoning': {'effort': effort}}
    timeout = httpx.Timeout(
        float(os.getenv('AI_TIMEOUT_SECONDS', '120')),
        connect=float(os.getenv('AI_CONNECT_TIMEOUT_SECONDS', '10')),
        write=30, pool=10)
    connection = connection_options()
    if os.getenv('AI_STREAM', '0') != '1':
        return httpx.post(url, headers={'Authorization': 'Bearer ' + key},
                          json=body, timeout=timeout, **connection)
    deadline = time.monotonic() + float(os.getenv('AI_TOTAL_TIMEOUT_SECONDS', '600'))
    limit = int(os.getenv('AI_MAX_RESPONSE_BYTES', '2000000'))
    with httpx.Client(timeout=timeout, **connection) as client:
        with client.stream('POST', url, headers={'Authorization': 'Bearer ' + key},
                           json={**body, 'stream': True}) as response:
            if response.status_code >= 400:
                return httpx.Response(response.status_code, headers=response.headers,
                                      json={}, request=response.request)
            if 'text/event-stream' not in response.headers.get('content-type', ''):
                raise StreamFailure('stream_content_type', response)
            event_lines, total = [], 0
            for line in response.iter_lines():
                if time.monotonic() > deadline:
                    raise httpx.ReadTimeout('AI total deadline exceeded', request=response.request)
                total += len(line.encode('utf-8'))
                if total > limit:
                    raise StreamFailure('stream_size_limit', response)
                if line.startswith('data:'):
                    event_lines.append(line[5:].lstrip())
                if line == '' and event_lines:
                    payload = '\n'.join(event_lines)
                    event_lines = []
                    if payload == '[DONE]':
                        break
                    event = json.loads(payload)
                    if event.get('type') == 'response.completed':
                        data = event['response']
                        if data.get('status') != 'completed':
                            raise StreamFailure('stream_status', response, data)
                        return httpx.Response(response.status_code, headers=response.headers,
                                              json=data, request=response.request)
                    if event.get('type') in ('error', 'response.failed', 'response.incomplete'):
                        data = event.get('response') or {}
                        error = event.get('error') or data.get('error') or event
                        code = error.get('code') if isinstance(error, dict) else None
                        known = {'server_error', 'rate_limit_exceeded', 'upstream_error',
                                 'request_timeout', 'timeout', 'overloaded', 'content_filter',
                                 'invalid_request_error', 'insufficient_quota'}
                        reason = event['type'] + (':' + code if code in known else '')
                        raise StreamFailure(reason, response, data)
            raise StreamFailure('stream_no_completion', response)
