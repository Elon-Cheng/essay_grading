import os
import time
import uuid
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient
import accounts
import app
import paypro_payments
import credit_payments
import saas
from tests.test_saas import SaaSTests


class CreditPaymentTests(unittest.TestCase):
    def setUp(self):
        SaaSTests.setUp(self)
        self.config = patch.dict(os.environ,{'PAYPRO_BASE_URL':'https://pay.example.com','PUBLIC_BASE_URL':'https://essay.example.com',
            'PAYPRO_SECRET':'x'*32,'PAYPRO_SETTLEMENT_VERIFIED':'1','PAYPRO_WECHAT_ENABLED':'1','PAYPRO_ALIPAY_ENABLED':'1'})
        self.config.start()

    def tearDown(self):
        self.config.stop()
        SaaSTests.tearDown(self)

    def create(self,key=None,actual='9.90',method='wechat'):
        def response(url,json,timeout):
            self.assertEqual(json['sign'],paypro_payments.signature(json))
            self.assertNotIn('productId',json)
            return Mock(json=lambda:{'code':200,'data':{'orderNo':json['orderNo'],'amount':'9.90','actualAmount':actual,
                'payType':json['payType'],'payNum':'98765','returnUrl':'https://pay.example.com/payment.html?id=123',
                'qrCodeUrl':'https://pay.example.com/qr.png','qrCode':'https://qr.alipay.com/test-native-order','orderId':'provider-123'}})
        with patch.object(credit_payments.httpx,'post',side_effect=response) as call:
            result=self.client.post('/api/payment/create',json={'productId':2,'paymentMethod':method},headers={'Idempotency-Key':key or uuid.uuid4().hex})
            return result,call.call_count

    def receipt(self,order,amount='9.90'):
        params={'orderNo':order['orderNo'],'amount':amount,'payNum':'98765'}
        params['sign']=paypro_payments.signature(params)
        return params

    def test_purchase_once_and_no_subscription(self):
        order=self.create()[0].json()
        self.assertEqual((order['status'],order['essayCredits'],order['amountFen']),('PENDING',5,990))
        self.assertEqual(order['payNum'],'98765')
        self.assertEqual(self.client.get('/api/subscription').json()['essay_credits'],0)
        for _ in range(3):
            self.assertEqual(self.client.post('/api/payment/callback',json=self.receipt(order)).text,'success')
        self.assertEqual(self.client.get('/api/subscription').json()['essay_credits'],5)
        self.assertEqual(self.client.get('/api/payment/'+order['orderNo']+'/status').json()['status'],'PAID')
        self.assertEqual(self.client.get('/payment/'+order['orderNo']).status_code,200)
        with accounts.database() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM subscriptions').fetchone()[0],0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM quota_ledger WHERE action=?",('purchase:'+order['orderNo'],)).fetchone()[0],1)

    def test_bad_amount_signature_remark_unknown_order(self):
        order=self.create()[0].json()
        variants=[self.receipt(order,'0.01'),{**self.receipt(order),'sign':'bad'}]
        for field,value in [('payNum','wrong'),('orderNo','unknown')]:
            params=self.receipt(order);params[field]=value;params['sign']=paypro_payments.signature(params);variants.append(params)
        for params in variants:
            self.assertEqual(self.client.post('/api/payment/callback',json=params).status_code,400)
        self.assertEqual(self.client.get('/api/subscription').json()['essay_credits'],0)

    def test_alipay_native_qr_and_cross_site_receipt(self):
        order=self.create(method='alipay')[0].json()
        self.assertEqual(order['qrCodeUrl'],'/api/payment/'+order['orderNo']+'/qr')
        response=self.client.get(order['qrCodeUrl'])
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers['content-type'],'image/png')
        self.assertTrue(response.content.startswith(b'\x89PNG'))
        self.assertEqual(self.client.post('/api/payment/callback',json=self.receipt(order),headers={'Origin':'https://pay.example.com','Sec-Fetch-Site':'cross-site'}).status_code,200)
        self.assertEqual(self.client.get(order['qrCodeUrl']).status_code,409)
        self.assertEqual(self.client.get('/api/subscription').json()['essay_credits'],5)

    def test_expired_and_duplicate_paid_receipt(self):
        order=self.create()[0].json()
        with accounts.database() as db:db.execute('UPDATE payment_orders SET expired_at=? WHERE order_no=?',(time.time()-1,order['orderNo']))
        self.assertEqual(self.client.post('/api/payment/callback',json=self.receipt(order)).status_code,400)
        self.assertEqual(self.client.get('/api/payment/'+order['orderNo']).json()['status'],'EXPIRED')
        self.assertEqual(self.client.get('/api/subscription').json()['essay_credits'],0)

    def test_idempotent_create_and_reject_client_price(self):
        key=uuid.uuid4().hex
        first,calls=self.create(key);second,calls2=self.create(key)
        self.assertEqual(first.json()['orderNo'],second.json()['orderNo'])
        self.assertEqual((calls,calls2),(1,0))
        self.assertEqual(self.client.post('/api/payment/create',json={'productId':2,'paymentMethod':'wechat','price':0.01},headers={'Idempotency-Key':uuid.uuid4().hex}).status_code,422)
        with patch.object(credit_payments.httpx,'post',side_effect=http_error()):
            order=self.client.post('/api/payment/create',json={'productId':2,'paymentMethod':'wechat'},headers={'Idempotency-Key':uuid.uuid4().hex}).json()
            self.assertEqual(order['status'],'PENDING');self.assertIsNone(order['paymentUrl'])
        self.assertIsNone(self.create(actual='9.88')[0].json()['paymentUrl'])

    def test_concurrent_callbacks_and_credit_job_lifecycle(self):
        order=self.create()[0].json();receipt=self.receipt(order)
        def notify(_):
            with TestClient(app.app) as client:return client.post('/api/payment/callback',json=receipt).status_code
        with ThreadPoolExecutor(max_workers=4) as pool:self.assertEqual(list(pool.map(notify,range(4))),[200]*4)
        self.assertEqual(self.client.get('/api/subscription').json()['essay_credits'],5)
        with accounts.database() as db:
            state=saas.entitlement(db,self.user['id'])
            db.execute('UPDATE quota_periods SET used=quota WHERE id=?',(state['period_id'],))
            ident=uuid.uuid4().hex;period=saas.reserve(db,self.user['id'],ident)
            db.execute('INSERT INTO jobs(id,user_id,created,quota_period_id,quota_state,attempts) VALUES(?,?,?,?,?,?)',(ident,self.user['id'],time.time(),period,'reserved',1))
            self.assertEqual(period,f'credits-{self.user["id"]}')
            self.assertEqual(saas.entitlement(db,self.user['id'])['available_credits'],4)
            saas.settle(db,ident,False)
            self.assertEqual(saas.entitlement(db,self.user['id'])['available_credits'],5)
            period=saas.reserve(db,self.user['id'],ident,2)
            db.execute("UPDATE jobs SET quota_state='reserved',attempts=2 WHERE id=?",(ident,))
            saas.settle(db,ident,True);saas.settle(db,ident,True)
            self.assertEqual(saas.entitlement(db,self.user['id'])['essay_credits'],4)

    def test_daily_free_limit_can_use_credits_and_order_is_private(self):
        order=self.create()[0].json()
        self.client.post('/api/payment/callback',json=self.receipt(order))
        with patch.dict(os.environ,{'FREE_DAILY_QUOTA':'1'}):
            with accounts.database() as db:
                for index in range(2):
                    ident=uuid.uuid4().hex;period=saas.reserve(db,self.user['id'],ident)
                    db.execute('INSERT INTO jobs(id,user_id,created,quota_period_id,quota_state) VALUES(?,?,?,?,?)',(ident,self.user['id'],time.time(),period,'reserved'))
                    self.assertEqual(period.startswith('credits-'),bool(index))
        self.client.post('/api/auth/logout')
        self.client.post('/api/auth/register',json={'username':'another_user','password':'testing-password'})
        self.assertEqual(self.client.get('/api/payment/'+order['orderNo']).status_code,404)
        self.assertEqual(self.client.get('/api/admin/payments').status_code,403)


def http_error():
    import httpx
    return httpx.ReadTimeout('Provider response unknown')
