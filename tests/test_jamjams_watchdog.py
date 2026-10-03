import unittest
from unittest.mock import patch

from scripts.jamjams_watchdog import Watchdog, validate_ipc


class FakeJamjams:
    def __init__(self):
        self.selected = 'a'
        self.enabled = True
        self.calls = []

    def call(self, method, params=None):
        self.calls.append((method, params))
        if method == 'getState':
            return {'isLoggedIn': True, 'isProxyEnabled': self.enabled,
                    'account': {'servers': [{'id': ident} for ident in ('a', 'b', 'c')],
                                'selectedServer': {'id': self.selected}},
                    'settings': {'proxy': {'address': '127.0.0.1', 'port': 1080}}}
        if method == 'checkStatus':
            return {'status': 2}
        if method == 'changeServer':
            self.selected = params['server_id']
            return {'id': self.selected}
        raise AssertionError(method)


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeJamjams()
        self.now = 1000
        self.watchdog = Watchdog(self.api, threshold=3, cooldown=300, settle=0,
                                 clock=lambda: self.now, sleep=lambda _: None)

    def switches(self):
        return [params['server_id'] for method, params in self.api.calls if method == 'changeServer']

    @patch('scripts.jamjams_watchdog.probe', return_value=('healthy', .1))
    def test_healthy_node_is_sticky(self, probe):
        for _ in range(4):
            self.watchdog.tick()
        self.assertEqual(self.switches(), [])

    @patch('scripts.jamjams_watchdog.probe', return_value=('upstream_http', 503))
    def test_provider_errors_do_not_trigger_node_switch(self, probe):
        for _ in range(4):
            self.watchdog.tick()
        self.assertEqual(self.switches(), [])

    @patch('scripts.jamjams_watchdog.probe')
    def test_only_switch_after_threshold_and_verify_target(self, probe):
        probe.side_effect = [('network_failure', None)] * 3 + [('healthy', .2)]
        self.watchdog.tick()
        self.watchdog.tick()
        self.assertEqual(self.switches(), [])
        self.assertEqual(self.watchdog.tick()['status'], 'switched')
        self.assertEqual(self.switches(), ['b'])

    @patch('scripts.jamjams_watchdog.probe', return_value=('network_failure', None))
    def test_failed_backups_restore_original_and_cooldown(self, probe):
        for _ in range(3):
            result = self.watchdog.tick()
        self.assertEqual(result['status'], 'no_healthy_backup')
        self.assertEqual(self.switches(), ['b', 'a', 'c', 'a'])
        self.watchdog.tick()
        self.assertEqual(len(self.switches()), 4)
        self.assertEqual(self.api.selected, 'a')

    @patch('scripts.jamjams_watchdog.probe', return_value=('network_failure', None))
    def test_manual_selection_resets_failures_and_starts_cooldown(self, probe):
        self.watchdog.tick()
        self.watchdog.tick()
        self.api.selected = 'c'
        for _ in range(4):
            self.watchdog.tick()
        self.assertEqual(self.switches(), [])

    @patch('scripts.jamjams_watchdog.probe')
    def test_disabled_proxy_is_not_enabled_by_watchdog(self, probe):
        self.api.enabled = False
        self.assertEqual(self.watchdog.tick()['status'], 'paused')
        probe.assert_not_called()
        self.assertEqual(self.switches(), [])

    @patch('scripts.jamjams_watchdog.probe')
    def test_manual_change_during_candidate_probe_is_preserved(self, probe):
        probe.return_value = ('network_failure', None)
        self.watchdog.sleep = lambda _: setattr(self.api, 'selected', 'c')
        self.watchdog.tick()
        self.watchdog.tick()
        self.assertEqual(self.watchdog.tick()['status'], 'manual_change')
        self.assertEqual(self.switches(), ['b'])
        self.assertEqual(self.api.selected, 'c')

    def test_control_interface_is_loopback_only(self):
        self.assertEqual(validate_ipc('ws://127.0.0.1:15734/ipc'), 'ws://127.0.0.1:15734/ipc')
        import argparse
        for value in ('ws://example.com:15734/ipc', 'ws://user:password@localhost:15734/ipc'):
            with self.assertRaises(argparse.ArgumentTypeError):
                validate_ipc(value)


if __name__ == '__main__':
    unittest.main()
