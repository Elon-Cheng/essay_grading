import json
import os
import socketserver
import threading
import unittest
from unittest.mock import patch
import httpx
from backend import ai_transport


class TransportTests(unittest.TestCase):
    def test_real_connect_uses_explicit_proxy_despite_no_proxy(self):
        requests = []

        class RejectingProxy(socketserver.BaseRequestHandler):
            def handle(self):
                self.request.settimeout(2)
                requests.append(self.request.recv(4096))
                self.request.sendall(b'HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')

        with socketserver.TCPServer(('127.0.0.1', 0), RejectingProxy) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                for stream in ('0', '1'):
                    with self.subTest(stream=stream), patch.dict(os.environ, {
                        'AI_STREAM': stream, 'AI_PROXY_URL': f'http://127.0.0.1:{server.server_address[1]}',
                        'AI_TRUST_ENV': '1', 'NO_PROXY': '*',
                    }):
                        with self.assertRaises(httpx.ProxyError):
                            ai_transport.request_response('https://example.invalid/v1/responses', 'private-api-key', {})
            finally:
                server.shutdown()
                thread.join(timeout=3)
        self.assertEqual(len(requests), 2)
        for request in requests:
            self.assertTrue(request.startswith(b'CONNECT example.invalid:443 '))
            self.assertNotIn(b'private-api-key', request)

    def test_explicit_proxy_overrides_environment_for_nonstream(self):
        with patch.dict(os.environ, {'AI_STREAM': '0', 'AI_PROXY_URL': 'http://127.0.0.1:1080',
                                     'AI_TRUST_ENV': '1', 'NO_PROXY': '*'}), \
                patch.object(ai_transport.httpx, 'post') as post:
            ai_transport.request_response('https://example.com/v1/responses', 'test', {})
        self.assertEqual(post.call_args.kwargs['proxy'], 'http://127.0.0.1:1080')
        self.assertFalse(post.call_args.kwargs['trust_env'])
        self.assertEqual(post.call_count, 1)

    def test_explicit_proxy_applies_to_stream_and_retries_handshake_once(self):
        with patch.dict(os.environ, {'AI_STREAM': '1', 'AI_PROXY_URL': 'http://127.0.0.1:1080'}), \
                patch.object(ai_transport.httpx, 'Client', side_effect=httpx.ConnectError('offline')) as client:
            with self.assertRaises(httpx.ConnectError):
                ai_transport.request_response('https://example.com/v1/responses', 'test', {})
        self.assertEqual(client.call_args.kwargs['proxy'], 'http://127.0.0.1:1080')
        self.assertFalse(client.call_args.kwargs['trust_env'])
        self.assertEqual(client.call_count, 2)

    def test_invalid_proxy_fails_without_exposing_credentials(self):
        with patch.dict(os.environ, {'AI_PROXY_URL': 'socks5://user:private@localhost:1080'}):
            with self.assertRaises(ValueError) as caught:
                ai_transport.connection_options()
        self.assertNotIn('private', str(caught.exception))

    def test_empty_proxy_preserves_direct_mode(self):
        with patch.dict(os.environ, {'AI_PROXY_URL': '', 'AI_TRUST_ENV': '0'}):
            self.assertEqual(ai_transport.connection_options(), {'trust_env': False})

    def request(self, content):
        real_client = httpx.Client
        transport = httpx.MockTransport(lambda r: httpx.Response(200,
            headers={'content-type': 'text/event-stream', 'x-request-id': 'test-id'}, content=content))
        with patch.dict(os.environ, {'AI_STREAM': '1'}), patch.object(ai_transport.httpx, 'Client',
                side_effect=lambda **kw: real_client(transport=transport, **kw)):
            return ai_transport.request_response('https://example.com/v1/responses', 'test', {'model': 'test'})

    def test_completed_keeps_usage_and_request_id(self):
        data = {'status': 'completed', 'output_text': 'OK', 'usage': {'output_tokens': 1}}
        response = self.request(('data: ' + json.dumps({'type': 'response.completed', 'response': data}) + '\n\n').encode())
        self.assertEqual(response.json(), data)
        self.assertEqual(response.headers['x-request-id'], 'test-id')

    def test_stream_parameter_rejection_keeps_json_for_schema_negotiation(self):
        error = {'error': {'param': 'text.format', 'code': 'unsupported_parameter'}}
        real_client = httpx.Client
        transport = httpx.MockTransport(lambda request: httpx.Response(400, json=error))
        with patch.dict(os.environ, {'AI_STREAM': '1'}), patch.object(ai_transport.httpx, 'Client',
                side_effect=lambda **kw: real_client(transport=transport, **kw)):
            response = ai_transport.request_response('https://example.com/v1/responses', 'test', {})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), error)

    def test_completed_event_without_trailing_blank_line(self):
        data={'status':'completed','output_text':'OK','usage':{'output_tokens':1}}
        response=self.request(('data: '+json.dumps({'type':'response.completed','response':data})).encode())
        self.assertEqual(response.json(),data)

    def test_partial_protocol_failure_keeps_progress_without_resubmitting(self):
        class BrokenStream(httpx.SyncByteStream):
            def __iter__(self):
                yield b'data: {"type":"response.created","response":{"id":"resp_test","status":"in_progress"}}\n\n'
                yield b'data: {"type":"response.output_text.delta","delta":"partial"}\n\n'
                raise httpx.RemoteProtocolError('connection lost')
        requests=[];real_client=httpx.Client
        def handler(request):
            requests.append(request)
            return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=BrokenStream())
        with patch.dict(os.environ,{'AI_STREAM':'1'}),patch.object(ai_transport.httpx,'Client',side_effect=lambda **kw:real_client(transport=httpx.MockTransport(handler),**kw)):
            with self.assertRaises(ai_transport.StreamFailure) as caught:
                ai_transport.request_response('https://example.com/v1/responses','test',{})
        self.assertEqual(len(requests),1)
        self.assertEqual(caught.exception.data['id'],'resp_test')
        self.assertEqual(caught.exception.data['output_text'],'partial')
        self.assertEqual(caught.exception.reason,'RemoteProtocolError')

    def test_partial_stream_is_rejected(self):
        with self.assertRaises(ValueError):
            self.request(b'data: {"type":"response.output_text.delta","delta":"partial"}\n\ndata: [DONE]\n\n')

    def test_incomplete_is_rejected(self):
        with self.assertRaises(ValueError):
            self.request(b'data: {"type":"response.incomplete"}\n\n')

    def test_stream_size_is_bounded(self):
        with patch.dict(os.environ, {'AI_MAX_RESPONSE_BYTES': '10'}), self.assertRaises(ValueError):
            self.request(b'data: {"type":"response.completed"}\n\n')

    def test_failure_preserves_usage_for_accounting(self):
        event = {'type': 'response.incomplete', 'response': {
            'status': 'incomplete', 'usage': {'output_tokens': 1200}}}
        with self.assertRaises(ai_transport.StreamFailure) as caught:
            self.request(('data: ' + json.dumps(event) + '\n\n').encode())
        self.assertEqual(caught.exception.reason, 'response.incomplete')
        self.assertEqual(caught.exception.data['usage']['output_tokens'], 1200)
        self.assertEqual(caught.exception.response.headers['x-request-id'], 'test-id')

    def test_provider_error_code_is_recorded_without_message(self):
        with self.assertRaises(ai_transport.StreamFailure) as caught:
            self.request(b'data: {"type":"error","code":"server_error","message":"private provider details"}\n\n')
        self.assertEqual(caught.exception.reason, 'error:server_error')
        self.assertNotIn('private', str(caught.exception))
