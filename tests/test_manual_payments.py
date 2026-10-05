import io
import os
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from PIL import Image
from fastapi import HTTPException
from fastapi.testclient import TestClient
import accounts
import app
import payments
import test_saas


class ManualPaymentTests(unittest.TestCase):
    def setUp(self):
        test_saas.SaaSTests.setUp(self)
        self.mode = patch.dict(os.environ, {'PAYMENTS_MODE':'manual'})
        self.mode.start()
        self.admin = TestClient(app.app)
        user = self.admin.post('/api/auth/register',json={'username':'payment_admin','password':'testing-password'}).json()
        with accounts.database() as db:
            db.execute("UPDATE users SET role='admin' WHERE id=?",(user['id'],))
            db.execute("UPDATE plans SET price_fen=NULL WHERE id='pro'")
        output = io.BytesIO()
        Image.new('RGB',(16,16),'white').save(output,format='PNG')
        self.image = output.getvalue()

    def tearDown(self):
        self.admin.close()
        self.mode.stop()
        test_saas.SaaSTests.tearDown(self)

    def configure(self,price=2900):
        response=self.admin.put('/api/admin/payments/manual',json={'price_fen':price,'wechat_receiver':'测试收款人','alipay_receiver':'支付宝收款人'})
        self.assertEqual(response.status_code,200,response.text)
        for channel in ('wechat','alipay'):
            response=self.admin.post('/api/admin/payments/manual/'+channel+'/qr',files={'file':('code.png',self.image)})
            self.assertEqual(response.status_code,200,response.text)

    def order(self,channel='wechat',key=None):
        response=self.client.post('/api/orders',json={'channel':channel},headers={'Idempotency-Key':key or uuid.uuid4().hex})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def proof(self,ident,client=None):
        return (client or self.client).post('/api/orders/'+ident+'/proof',data={'payer':'付款人','reference':'claimed-transaction'},files={'file':('receipt.png',self.image)})

    def approve(self,ident,transaction='real-transaction',amount=2900):
        return self.admin.post('/api/admin/orders/'+ident+'/review',json={'decision':'approve','reason':'已核对实际到账','amount_fen':amount,'transaction_id':transaction,'confirmed_received':True})

    def test_unpriced_and_missing_code_keep_checkout_closed(self):
        self.configure(None)
        plans=self.client.get('/api/plans').json()
        self.assertEqual(plans['payment_mode'],'manual')
        self.assertFalse(next(p for p in plans['plans'] if p['id']=='pro')['purchasable'])
        self.assertEqual(self.client.post('/api/orders',json={'channel':'wechat'},headers={'Idempotency-Key':uuid.uuid4().hex}).status_code,503)
        with accounts.database() as db:
            db.execute("UPDATE plans SET price_fen=2900 WHERE id='pro'")
            db.execute('DELETE FROM manual_payment_settings')
        self.assertEqual(self.client.post('/api/orders',json={'channel':'wechat'},headers={'Idempotency-Key':uuid.uuid4().hex}).status_code,503)

    def test_teacher_price_gate_and_matching_subscription(self):
        self.configure(1990)
        r=self.admin.put('/api/admin/payments/manual',json={'teacher_price_fen':3990,'teacher_enabled':False,'wechat_receiver':'测试收款人','alipay_receiver':'支付宝收款人'})
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.json()['prices'],{'pro':1990,'teacher':3990})
        rows={p['id']:p for p in self.client.get('/api/plans').json()['plans']}
        self.assertEqual(rows['pro']['price_fen'],1990)
        self.assertTrue(rows['pro']['purchasable'])
        self.assertEqual(rows['teacher']['price_fen'],3990)
        self.assertFalse(rows['teacher']['purchasable'])
        create=lambda:self.client.post('/api/orders',json={'plan':'teacher','channel':'wechat'},headers={'Idempotency-Key':uuid.uuid4().hex})
        self.assertEqual(create().status_code,503)
        self.admin.put('/api/admin/payments/manual',json={'teacher_enabled':True,'wechat_receiver':'测试收款人','alipay_receiver':'支付宝收款人'})
        response=create();self.assertEqual(response.status_code,200,response.text)
        order=response.json();self.assertEqual((order['plan'],order['amount_fen'],order['quota']),('teacher',3990,100))
        self.proof(order['id'])
        self.assertEqual(self.approve(order['id'],amount=1990).status_code,400)
        self.assertEqual(self.approve(order['id'],amount=3990).status_code,200)
        state=self.client.get('/api/subscription').json()
        self.assertEqual((state['plan'],state['quota']),('teacher',100))
        # Older settings clients changing only Pro must not clear Teacher price.
        self.configure(2990)
        self.assertEqual(self.admin.get('/api/admin/payments/manual').json()['prices']['teacher'],3990)

    def test_manual_order_is_idempotent_and_freezes_price_receiver_and_code(self):
        self.configure()
        key=uuid.uuid4().hex
        order=self.order(key=key)
        self.configure(4900)
        replay=self.order(key=key)
        self.assertEqual(order['id'],replay['id'])
        self.assertEqual(replay['amount_fen'],2900)
        self.assertEqual(replay['code_url'],order['code_url'])
        self.assertEqual(self.client.get('/api/orders/'+order['id']+'/qr').status_code,200)
        with patch('payments.query_order') as query:
            self.client.post('/api/orders/'+order['id']+'/refresh')
            payments.reconcile()
            query.assert_not_called()

    def test_receipt_requires_admin_actual_amount_and_grants_once(self):
        self.configure();order=self.order();ident=order['id']
        self.assertEqual(self.proof(ident).json()['status'],'review_pending')
        self.assertEqual(self.client.get('/api/subscription').json()['plan'],'free')
        self.assertEqual(self.client.post('/api/admin/orders/'+ident+'/review',json={'decision':'approve','reason':'伪造审核请求'}).status_code,403)
        self.assertEqual(self.approve(ident,amount=1).status_code,400)
        self.assertEqual(self.admin.post('/api/admin/orders/'+ident+'/review',json={'decision':'approve','reason':'未确认实际到账','amount_fen':2900,'transaction_id':'real-transaction'}).status_code,400)
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses=list(pool.map(lambda _:self.approve(ident),range(2)))
        self.assertEqual([r.status_code for r in responses],[200,200])
        state=self.client.get('/api/subscription').json()
        self.assertEqual((state['plan'],state['quota']),('pro',100))
        with accounts.database() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM subscriptions WHERE source_order_id=?',(ident,)).fetchone()[0],1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM audit_logs WHERE action='manual_payment_approve'").fetchone()[0],1)

    def test_transaction_cannot_activate_two_orders(self):
        self.configure();a=self.order();b=self.order()
        self.proof(a['id']);self.proof(b['id'])
        self.assertEqual(self.approve(a['id']).status_code,200)
        self.assertEqual(self.approve(b['id']).status_code,409)
        self.assertEqual(self.approve(b['id'],transaction='another-transaction').status_code,200)
        with accounts.database() as db:
            rows=db.execute('SELECT start_at,expire_at FROM subscriptions ORDER BY start_at').fetchall()
            self.assertEqual(rows[0]['expire_at'],rows[1]['start_at'])

    def test_rejected_proof_can_be_resubmitted_and_late_transfer_reported(self):
        self.configure();ident=self.order()['id'];self.proof(ident)
        r=self.admin.post('/api/admin/orders/'+ident+'/review',json={'decision':'reject','reason':'未找到对应到账记录'})
        self.assertEqual(r.json()['status'],'rejected')
        self.assertEqual(self.client.get('/api/orders/'+ident+'/proof').json()['review_note'],'未找到对应到账记录')
        with accounts.database() as db:db.execute('UPDATE orders SET expires=? WHERE id=?',(time.time()-1,ident))
        self.assertEqual(self.client.get('/api/orders/'+ident+'/qr').status_code,409)
        self.assertEqual(self.proof(ident).json()['status'],'review_pending')
        self.assertEqual(self.approve(ident).status_code,200)

    def test_private_images_and_settings_are_not_accessible_to_other_users(self):
        self.configure();ident=self.order()['id'];self.proof(ident)
        other=TestClient(app.app)
        try:
            self.assertEqual(other.get('/api/orders/'+ident+'/proof/image').status_code,401)
            other.post('/api/auth/register',json={'username':'other_buyer','password':'testing-password'})
            for path in ('/api/orders/'+ident+'/qr','/api/orders/'+ident+'/proof','/api/orders/'+ident+'/proof/image'):
                self.assertEqual(other.get(path).status_code,404)
            self.assertEqual(self.proof(ident,other).status_code,404)
            self.assertEqual(other.get('/api/admin/payments/manual').status_code,403)
            self.assertEqual(other.get('/api/admin/payments/manual/wechat/qr').status_code,403)
            self.assertEqual(other.post('/api/admin/payments/manual/wechat/qr',files={'file':('code.png',self.image)}).status_code,403)
        finally:other.close()

    def test_invalid_and_oversized_receipt_images_rejected(self):
        self.configure();ident=self.order()['id']
        for raw,expected in ((b'<svg>not an image</svg>',400),(b'x'*(2*1024*1024+1),413)):
            r=self.client.post('/api/orders/'+ident+'/proof',data={'payer':'name','reference':'transaction'},files={'file':('image.png',raw)})
            self.assertEqual(r.status_code,expected,r.text)
        self.assertEqual(self.client.get('/api/orders/'+ident).json()['status'],'pending')

    def test_merchant_notifications_cannot_settle_manual_orders(self):
        self.configure();order=self.order()
        with self.assertRaises(HTTPException):
            payments.apply_trade('wechat',{'order_id':order['id'],'transaction_id':'spoofed-transaction','success':True,'amount':2900,'currency':'CNY'},'event','hash')
        self.assertEqual(self.client.get('/api/subscription').json()['plan'],'free')

    def test_manual_refund_requires_confirmation_and_revokes_entitlement(self):
        self.configure();ident=self.order()['id'];self.proof(ident);self.approve(ident)
        self.assertEqual(self.admin.post('/api/admin/orders/'+ident+'/refund',json={'reason':'不应调用商户退款'}).status_code,409)
        data={'reason':'已完成原渠道实际退款','transaction_id':'refund-transaction','amount_fen':2900,'confirmed_refunded':True}
        bad={**data,'confirmed_refunded':False}
        self.assertEqual(self.admin.post('/api/admin/orders/'+ident+'/manual-refund',json=bad).status_code,422)
        for _ in range(2):self.assertEqual(self.admin.post('/api/admin/orders/'+ident+'/manual-refund',json=data).status_code,200)
        self.assertEqual(self.client.get('/api/subscription').json()['plan'],'free')
        self.assertEqual(self.client.get('/api/orders/'+ident).json()['status'],'refunded')
        with patch('payments.process_refund') as process:
            payments.reconcile();process.assert_not_called()
        second=self.order()['id'];self.proof(second);self.approve(second,transaction='second-real-receipt')
        self.assertEqual(self.admin.post('/api/admin/orders/'+second+'/manual-refund',json=data).status_code,409)


if __name__=='__main__':unittest.main()
