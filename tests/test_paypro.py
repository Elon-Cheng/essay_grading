import os
import uuid
import unittest
from unittest.mock import patch, Mock

import accounts
import paypro_payments as paypro
from tests.test_saas import SaaSTests


class PayproTests(unittest.TestCase):
    def setUp(self):
        SaaSTests.setUp(self)
        self.paypro_env = patch.dict(os.environ, {
            'PAYMENTS_MODE': 'paypro', 'PRO_PRICE_FEN': '1990',
            'PAYPRO_BASE_URL': 'https://pay.example.com', 'PUBLIC_BASE_URL': 'https://essay.example.com',
            'PAYPRO_SECRET': 'a' * 32, 'PAYPRO_SETTLEMENT_VERIFIED': '1',
            'PAYPRO_WECHAT_ENABLED': '1', 'PAYPRO_ALIPAY_ENABLED': '1'})
        self.paypro_env.start()

    def tearDown(self):
        self.paypro_env.stop()
        SaaSTests.tearDown(self)

    def create_paypro(self, channel='wechat', actual='19.90'):
        def response(url, json, timeout):
            self.assertEqual(json['sign'], paypro.signature(json))
            return Mock(json=lambda: {'code': 200, 'data': {
                'orderNo': json['orderNo'], 'amount': '19.90', 'actualAmount': actual,
                'payType': json['payType'], 'payNum': '12345',
                'returnUrl': 'https://pay.example.com/payment.html?orderId=' + json['orderNo']}})
        with patch.object(paypro.httpx, 'post', side_effect=response):
            return self.client.post('/api/orders', json={'channel': channel},
                headers={'Idempotency-Key': uuid.uuid4().hex}).json()

    def receipt(self, order, amount='19.90'):
        params = {'orderNo': order['id'], 'amount': amount, 'payNum': '12345'}
        params['sign'] = paypro.signature(params)
        return params

    def test_paypro_settles_once_and_rejects_wrong_amount(self):
        order = self.create_paypro()
        self.assertEqual(order['payment_mode'], 'paypro')
        self.assertEqual(order['status'], 'pending')
        self.assertEqual(self.client.post('/api/payments/paypro/notify', json=self.receipt(order, '1.00')).status_code, 400)
        params = self.receipt(order)
        for _ in range(2):
            self.assertEqual(self.client.post('/api/payments/paypro/notify', json=params).text, 'success')
        with accounts.database() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM subscriptions WHERE source_order_id=?', (order['id'],)).fetchone()[0], 1)

    def test_paypro_bad_signature_and_decrement(self):
        order = self.create_paypro('alipay')
        params = self.receipt(order)
        params['sign'] = 'invalid'
        self.assertEqual(self.client.post('/api/payments/paypro/notify', json=params).status_code, 400)
        self.assertEqual(self.create_paypro(actual='19.89')['status'], 'creating')

    def test_paypro_verification_gate(self):
        with patch.dict(os.environ, {'PAYPRO_SETTLEMENT_VERIFIED': '0'}):
            self.assertFalse(paypro.configured('wechat'))
