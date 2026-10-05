import base64
import hashlib
import io
import json
import os
import tempfile
import time
import unittest
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

import httpx
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from backend import accounts
from backend import app
from backend import payments
from backend import saas
from backend import worker


class SaaSTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.postgres = os.getenv('TEST_DATABASE_URL', '')
        if self.postgres and '/essay_test_' not in self.postgres:
            raise RuntimeError('Test database name must start with essay_test_')
        self.env = patch.dict(os.environ, {'ESSAY_DATA_DIR':str(self.root),'PAYMENTS_MODE':'merchant','DATABASE_URL':self.postgres,'APP_ENV':'development','INLINE_WORKER':'0','FREE_DAILY_QUOTA':'0','USER_MAX_PENDING':'20','PRO_PRICE_FEN':'','AI_DAILY_BUDGET':'','AI_INPUT_PRICE_PER_MILLION':'','AI_CACHED_PRICE_PER_MILLION':'','AI_OUTPUT_PRICE_PER_MILLION':''})
        self.env.start()
        self.patches = [patch.object(accounts,'DB',self.root/'accounts.sqlite3'),patch.object(app,'DATA',self.root)]
        for p in self.patches:p.start()
        accounts.initialize()
        if self.postgres:
            with accounts.database() as db:
                for table in ('sessions','users','jobs','events','attempts','subscriptions','quota_periods','quota_ledger','ai_calls','orders','payment_orders','payment_events','refunds','audit_logs','rate_limits','product_events','manual_payment_settings','manual_payment_proofs'):
                    db.execute(f'DELETE FROM {table}')
        self.client=TestClient(app.app)
        self.user=self.client.post('/api/auth/register',json={'username':'saas_user','password':'testing-password'}).json()
        self.fixture=next((app.ROOT/'tests'/'cases').glob('*.docx'))

    def tearDown(self):
        self.client.close()
        for p in reversed(self.patches):p.stop()
        self.env.stop();self.temp.cleanup()

    def submit(self,key=None,contents=None):
        return self.client.post('/api/essays',files={'file':('Essay.docx',contents or self.fixture.read_bytes())},headers={'Idempotency-Key':key or uuid.uuid4().hex})

    def admin(self):
        with accounts.database() as db:db.execute("UPDATE users SET role='admin' WHERE id=?",(self.user['id'],))

    def order(self,channel='wechat',ident=None):
        ident=ident or uuid.uuid4().hex
        with accounts.database() as db:
            db.execute('INSERT INTO orders(id,user_id,plan,quota,amount_fen,currency,channel,status,request_key,created,expires) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(ident,self.user['id'],'pro',100,2900,'CNY',channel,'pending',uuid.uuid4().hex,time.time(),time.time()+1800))
        return ident

    def trade(self,ident,channel='wechat',amount=2900):
        return {'order_id':ident,'transaction_id':'tx-'+ident,'success':True,'amount':amount,'currency':'CNY'}

    def test_admin_unlimited_ignores_monthly_and_daily_quota(self):
        with accounts.database() as db:
            db.execute("UPDATE users SET role='admin' WHERE id=?", (self.user['id'],))
            state = saas.entitlement(db, self.user['id'])
            db.execute('UPDATE quota_periods SET used=999 WHERE id=?', (state['period_id'],))
        with patch.dict(os.environ, {'FREE_DAILY_QUOTA':'1'}):
            for _ in range(4):
                self.assertEqual(self.submit().status_code, 200)
        data = self.client.get('/api/subscription').json()
        self.assertTrue(data['unlimited'])
        self.assertIsNone(data['remaining_quota'])
        with accounts.database() as db:
            db.execute("UPDATE users SET role='user' WHERE id=?", (self.user['id'],))
        self.assertEqual(self.submit().status_code, 429)

    def test_subscription_defaults_and_prices_unset(self):
        data=self.client.get('/api/subscription').json()
        self.assertEqual((data['plan'],data['quota'],data['remaining_quota']),('free',3,3))
        plans=self.client.get('/api/plans').json()['plans']
        self.assertEqual(next(p for p in plans if p['id']=='pro')['quota'],100)
        self.assertFalse(next(p for p in plans if p['id']=='pro')['purchasable'])
        self.assertEqual(self.client.post('/api/orders',json={'channel':'wechat'},headers={'Idempotency-Key':uuid.uuid4().hex}).status_code,503)
        with accounts.database() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM orders').fetchone()[0],0)

    def test_idempotent_submission_and_hash_conflict(self):
        key=uuid.uuid4().hex
        first=self.submit(key);second=self.submit(key)
        self.assertEqual(first.status_code,200)
        self.assertEqual(first.json()['id'],second.json()['id'])
        self.assertEqual(self.client.get('/api/subscription').json()['reserved_quota'],1)
        self.assertEqual(self.submit(key,self.fixture.read_bytes()+b'changed').status_code,409)
        with accounts.database() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],1)

    def test_monthly_limit_is_atomic_under_concurrency(self):
        with ThreadPoolExecutor(max_workers=6) as pool:
            results=list(pool.map(lambda _:self.submit().status_code,range(6)))
        self.assertEqual(results.count(200),3)
        self.assertEqual(results.count(429),3)
        self.assertEqual(self.client.get('/api/subscription').json()['reserved_quota'],3)

    def test_invalid_docx_does_not_reserve_or_leave_folder(self):
        self.assertEqual(self.submit(contents=b'invalid').status_code,400)
        self.assertEqual(self.client.get('/api/subscription').json()['remaining_quota'],3)
        self.assertEqual([p for p in self.root.iterdir() if p.is_dir()],[])

    def test_success_commits_once_failure_releases_once(self):
        ident=self.submit().json()['id']
        with patch.object(app,'call_openai',return_value=''):app.run_job(ident,None)
        data=self.client.get('/api/subscription').json()
        self.assertEqual((data['used_quota'],data['reserved_quota']),(1,0))
        app.run_job(ident,None)
        self.assertEqual(self.client.get('/api/subscription').json()['used_quota'],1)
        ident=self.submit().json()['id']
        with patch.object(app,'call_openai',side_effect=RuntimeError('test failure')):app.run_job(ident,None)
        self.assertEqual(self.client.get('/api/subscription').json()['remaining_quota'],2)
        with accounts.database() as db:
            saas.settle(db,ident,False)
            self.assertEqual(db.execute('SELECT SUM(reserved) FROM quota_periods').fetchone()[0],0)

    def test_retry_re_reserves_and_does_not_erase_ledger(self):
        ident=self.submit().json()['id']
        with patch.object(app,'call_openai',side_effect=RuntimeError('confirmed failure')):app.run_job(ident,None)
        self.assertEqual(self.client.post(f'/api/essays/{ident}/retry').status_code,200)
        self.assertEqual(self.client.post(f'/api/essays/{ident}/retry').status_code,409)
        with patch.object(app,'call_openai',return_value=''):app.run_job(ident,None)
        with accounts.database() as db:
            rows=db.execute('SELECT action FROM quota_ledger WHERE job_id=?',(ident,)).fetchall()
        self.assertEqual({r['action'] for r in rows},{'reserve:1','release:1','reserve:2','commit:2'})

    def test_worker_picks_up_persisted_job_and_render_retry_reuses_ai(self):
        ident=self.submit().json()['id']
        with patch.object(app,'call_openai',return_value=''):self.assertTrue(worker.tick())
        self.assertEqual(self.client.get('/api/essays/'+ident).json()['status'],'succeeded')
        ident=self.submit().json()['id']
        with patch.object(app,'call_openai',return_value=app.mock_grading(app.paragraphs_from_docx(self.fixture))),patch('backend.app.subprocess.run',side_effect=RuntimeError('render failed')):app.run_job(ident,None)
        self.assertEqual(self.client.post(f'/api/essays/{ident}/retry').status_code,200)
        with patch.object(app,'call_openai') as call:app.run_job(ident,None)
        call.assert_not_called()
        self.assertEqual(self.client.get('/api/essays/'+ident).json()['status'],'succeeded')

    def test_recovery_distinguishes_unknown_ai_from_safe_queue(self):
        first=self.submit().json()['id'];second=self.submit().json()['id']
        saas.claim(first,'dead');saas.claim(second,'dead')
        saas.start_call(first,'test','test')
        with accounts.database() as db:db.execute('UPDATE jobs SET lease_until=0')
        saas.recover()
        self.assertEqual(self.client.get('/api/essays/'+first).json()['status'],'failed')
        self.assertEqual(self.client.get('/api/essays/'+second).json()['status'],'queued')
        self.assertEqual(self.client.post('/api/essays/'+first+'/retry').status_code,409)

    def test_subscription_grants_expiry_and_renewal(self):
        self.admin()
        endpoint='/api/admin/users/'+str(self.user['id'])+'/subscription'
        result=self.client.post(endpoint,json={'plan':'pro','months':1,'reason':'测试会员发放'}).json()
        self.assertEqual((result['plan'],result['quota']),('pro',100))
        self.client.post(endpoint,json={'plan':'pro','months':1,'reason':'测试顺延会员'})
        with accounts.database() as db:
            rows=db.execute('SELECT * FROM subscriptions ORDER BY start_at').fetchall()
            self.assertEqual(rows[0]['expire_at'],rows[1]['start_at'])
            self.assertTrue(saas.entitlement(db,self.user['id'],rows[0]['expire_at']+1)['unlimited'])
            db.execute("UPDATE users SET role='user' WHERE id=?", (self.user['id'],))
            self.assertEqual(saas.entitlement(db,self.user['id'],rows[0]['expire_at']+1)['remaining_quota'],100)
            self.assertEqual(saas.entitlement(db,self.user['id'],rows[1]['expire_at']+1)['plan'],'free')

    def test_payment_duplicate_and_late_notify_grant_once(self):
        ident=self.order();trade=self.trade(ident)
        with accounts.database() as db:db.execute("UPDATE orders SET status='closed',expires=0 WHERE id=?",(ident,))
        payments.apply_trade('wechat',trade,'event1','hash1')
        payments.apply_trade('wechat',trade,'event1','hash1')
        payments.apply_trade('wechat',trade,'event2','hash2')
        with accounts.database() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM subscriptions').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT status FROM orders').fetchone()[0],'paid')

    def test_payment_amount_mismatch_recorded_and_no_grant(self):
        ident=self.order()
        with self.assertRaises(Exception):payments.apply_trade('wechat',self.trade(ident,amount=1),'bad','hash')
        with accounts.database() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM subscriptions').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT status FROM payment_events').fetchone()[0],'rejected')

    def test_provider_transaction_cannot_pay_two_orders(self):
        first,second=self.order(),self.order()
        trade=self.trade(first);payments.apply_trade('wechat',trade,'one','one')
        trade['order_id']=second
        with self.assertRaises(Exception):payments.apply_trade('wechat',trade,'two','two')
        with accounts.database() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM subscriptions').fetchone()[0],1)

    def keys(self,channel):
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        private=self.root/(channel+'-private.pem');public=self.root/(channel+'-public.pem')
        private.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        public.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
        os.environ.update({channel.upper()+'_PRIVATE_KEY_PATH':str(private),channel.upper()+'_PUBLIC_KEY_PATH':str(public),'PUBLIC_BASE_URL':'https://essay.test'})
        return key

    def test_wechat_signed_encrypted_callback_and_forgery(self):
        self.keys('wechat');os.environ.update({'WECHAT_APP_ID':'app','WECHAT_MCH_ID':'merchant','WECHAT_SERIAL':'serial','WECHAT_API_V3_KEY':'x'*32,'WECHAT_PUBLIC_KEY_ID':'PUB_KEY_ID_1'})
        ident=self.order()
        resource={'appid':'app','mchid':'merchant','out_trade_no':ident,'transaction_id':'wx-1','trade_state':'SUCCESS','amount':{'total':2900,'currency':'CNY'}}
        nonce='123456789012'
        cipher=AESGCM(b'x'*32).encrypt(nonce.encode(),json.dumps(resource).encode(),b'transaction')
        raw=json.dumps({'id':'event-wx','event_type':'TRANSACTION.SUCCESS','resource':{'algorithm':'AEAD_AES_256_GCM','nonce':nonce,'associated_data':'transaction','ciphertext':base64.b64encode(cipher).decode()}}).encode()
        stamp=str(int(time.time()));headers={'Wechatpay-Timestamp':stamp,'Wechatpay-Nonce':'n','Wechatpay-Serial':'PUB_KEY_ID_1','Wechatpay-Signature':payments.sign('wechat',stamp+'\nn\n'+raw.decode()+'\n')}
        response=self.client.post('/api/payments/wechat/notify',content=raw,headers=headers)
        self.assertEqual(response.status_code,204)
        self.assertEqual(self.client.post('/api/payments/wechat/notify',content=raw,headers=headers).status_code,204)
        headers['Wechatpay-Signature']='invalid'
        self.assertEqual(self.client.post('/api/payments/wechat/notify',content=raw,headers=headers).status_code,400)
        self.assertEqual(self.client.get('/api/subscription').json()['quota'],100)

    def test_alipay_signed_callback_and_wrong_seller(self):
        self.keys('alipay');os.environ.update({'ALIPAY_APP_ID':'ali-app','ALIPAY_SELLER_ID':'seller'})
        ident=self.order('alipay')
        params={'app_id':'ali-app','seller_id':'seller','out_trade_no':ident,'trade_no':'ali-1','trade_status':'TRADE_SUCCESS','total_amount':'29.00','notify_id':'ali-event','sign_type':'RSA2'}
        def send():
            canonical='&'.join(f'{k}={params[k]}' for k in sorted(params) if k not in ('sign','sign_type'))
            params['sign']=payments.sign('alipay',canonical)
            return self.client.post('/api/payments/alipay/notify',content=urlencode(params),headers={'Content-Type':'application/x-www-form-urlencoded'})
        self.assertEqual(send().text,'success');self.assertEqual(send().text,'success')
        params['seller_id']='other';params['notify_id']='bad'
        self.assertEqual(send().status_code,400)

    def test_order_creation_idempotence_and_owner_isolation(self):
        os.environ['PRO_PRICE_FEN']='2900'
        key=uuid.uuid4().hex
        with patch('backend.payments.configured',return_value=True),patch('backend.payments.precreate',return_value='weixin://test') as pre:
            first=self.client.post('/api/orders',json={'channel':'wechat'},headers={'Idempotency-Key':key})
            second=self.client.post('/api/orders',json={'channel':'wechat'},headers={'Idempotency-Key':key})
        self.assertEqual(first.json()['id'],second.json()['id']);pre.assert_called_once()
        other=TestClient(app.app)
        other.post('/api/auth/register',json={'username':'other_user','password':'testing-password'})
        self.assertEqual(other.get('/api/orders/'+first.json()['id']).status_code,404)
        self.assertEqual(other.get('/api/orders/'+first.json()['id']+'/qr').status_code,404)
        other.close()

    def test_refund_idempotence_and_revoke_entitlement(self):
        self.admin();ident=self.order();payments.apply_trade('wechat',self.trade(ident),'paid','hash')
        with patch('backend.payments.process_refund') as process:
            first=self.client.post('/api/admin/orders/'+ident+'/refund',json={'reason':'测试订单退款'})
            second=self.client.post('/api/admin/orders/'+ident+'/refund',json={'reason':'测试重复退款'})
            process.assert_called_once()
        self.assertEqual(first.json()['id'],second.json()['id'])
        self.assertEqual(self.client.get('/api/subscription').json()['plan'],'free')
        with patch('backend.payments.wechat_request',return_value={'status':'SUCCESS','refund_id':'wx-refund'}):payments.process_refund(first.json())
        with accounts.database() as db:self.assertEqual(db.execute('SELECT status FROM orders WHERE id=?',(ident,)).fetchone()[0],'refunded')

    def test_ai_usage_pricing_and_unknown_not_zero(self):
        with patch.dict(os.environ,{'AI_INPUT_PRICE_PER_MILLION':'2','AI_CACHED_PRICE_PER_MILLION':'1','AI_OUTPUT_PRICE_PER_MILLION':'8'}):
            ident=saas.start_call(None,'model','provider')
            saas.finish_call(ident,{'model':'returned','usage':{'input_tokens':1000,'input_tokens_details':{'cached_tokens':200},'output_tokens':500}})
        with accounts.database() as db:
            row=db.execute('SELECT * FROM ai_calls WHERE id=?',(ident,)).fetchone()
            self.assertAlmostEqual(row['estimated_cost'],.0058)
            self.assertEqual(row['returned_model'],'returned')
        ident=saas.start_call(None,'model','provider');saas.finish_call(ident,{})
        with accounts.database() as db:self.assertIsNone(db.execute('SELECT estimated_cost FROM ai_calls WHERE id=?',(ident,)).fetchone()[0])

    def test_budget_concurrency_and_unknown_usage_circuit(self):
        with patch.dict(os.environ,{'AI_DAILY_BUDGET':'1','AI_CALL_BUDGET_RESERVATION':'1','AI_INPUT_PRICE_PER_MILLION':'1','AI_CACHED_PRICE_PER_MILLION':'1','AI_OUTPUT_PRICE_PER_MILLION':'1'}):
            first=saas.start_call(None,'model','provider')
            with self.assertRaises(RuntimeError):saas.start_call(None,'model','provider')
            saas.finish_call(first,{})
            with self.assertRaises(RuntimeError):saas.start_call(None,'model','provider')

    def test_production_never_uses_demo_or_accepts_missing_idempotency(self):
        with patch.dict(os.environ,{'APP_ENV':'production','OPENAI_API_KEY':''}):
            with self.assertRaises(RuntimeError):app.call_openai('Essay')
            self.assertEqual(self.submit().status_code,503)
            self.assertEqual(self.client.post('/api/essays',files={'file':('Essay.docx',self.fixture.read_bytes())}).status_code,400)

    def test_admin_routes_dau_and_funnel(self):
        self.assertEqual(self.client.get('/admin').status_code,403)
        self.assertEqual(self.client.get('/api/admin/overview').status_code,403)
        self.client.post('/api/product/visit')
        self.client.post('/api/activity/active');self.client.post('/api/activity/active')
        self.admin()
        data=self.client.get('/api/admin/overview').json()
        self.assertEqual(data['dau'],1)
        self.assertEqual(data['users'],1)
        self.assertEqual(data['registration_conversion'],0)
        self.assertEqual(self.client.get('/api/admin/records/not-a-table').status_code,404)

    def test_backup_and_restore_preserve_db_and_report(self):
        if self.postgres:
            self.skipTest('PostgreSQL dump/restore is exercised separately by integration script')
        from scripts.backup_saas import backup,verify
        ident=self.submit().json()['id']
        with patch.object(app,'call_openai',return_value=''):app.run_job(ident,None)
        with tempfile.TemporaryDirectory() as output:
            archive=Path(output)/'backup.zip';restore=Path(output)/'restore'
            with patch.dict(os.environ,{'ESSAY_DATA_DIR':str(self.root)}):backup(archive)
            verify(archive,restore)
            self.assertEqual((restore/'data'/ident/'graded.docx').read_bytes(),(self.root/ident/'graded.docx').read_bytes())
            with patch.object(accounts,'DB',restore/'data'/'accounts.sqlite3'),patch.object(app,'DATA',restore/'data'):
                self.assertEqual(self.client.get('/api/essays/'+ident+'/download').status_code,200)

    def test_manual_quota_adjustment_requires_reason_and_cannot_undercut_reserved(self):
        self.admin();self.submit()
        endpoint='/api/admin/users/'+str(self.user['id'])+'/quota'
        self.assertEqual(self.client.post(endpoint,json={'delta':3,'reason':'x'}).status_code,422)
        self.assertEqual(self.client.post(endpoint,json={'delta':-3,'reason':'测试非法扣除额度'}).status_code,409)
        result=self.client.post(endpoint,json={'delta':2,'reason':'补偿批改失败次数'}).json()
        self.assertEqual(result['quota'],5)
        with accounts.database() as db:self.assertEqual(db.execute("SELECT COUNT(*) FROM audit_logs WHERE action='adjust_quota'").fetchone()[0],1)

    def test_unknown_usage_resolution_audited_and_unlocks_retry(self):
        self.admin();ident=self.submit().json()['id'];saas.claim(ident,'dead')
        call=saas.start_call(ident,'model','provider')
        with accounts.database() as db:db.execute('UPDATE jobs SET lease_until=0 WHERE id=?',(ident,))
        saas.recover()
        response=self.client.post('/api/admin/calls/'+call+'/resolve',json={'input_tokens':100,'output_tokens':30,'verified_cost':.01,'reason':'已核对供应商账单费用'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.client.post('/api/essays/'+ident+'/retry').status_code,200)
        with accounts.database() as db:self.assertEqual(db.execute('SELECT estimated_cost FROM ai_calls WHERE id=?',(call,)).fetchone()[0],.01)

    def test_alipay_active_query_does_not_require_notification_only_fields(self):
        ident=self.order('alipay')
        with accounts.database() as db:order=db.execute('SELECT * FROM orders WHERE id=?',(ident,)).fetchone()
        response={'out_trade_no':ident,'trade_no':'alipay-query','trade_status':'TRADE_SUCCESS','total_amount':'29.00'}
        with patch('backend.payments.alipay_request',return_value=response):payments.query_order(order)
        self.assertEqual(self.client.get('/api/subscription').json()['plan'],'pro')

    def test_payment_precreate_timeout_keeps_order_for_reconciliation(self):
        os.environ['PRO_PRICE_FEN']='2900'
        with patch('backend.payments.configured',return_value=True),patch('backend.payments.precreate',side_effect=httpx.ReadTimeout('timeout')):
            response=self.client.post('/api/orders',json={'channel':'wechat'},headers={'Idempotency-Key':uuid.uuid4().hex})
        self.assertEqual(response.json()['status'],'creating')
        self.assertIsNone(response.json()['code_url'])

    def test_chunked_request_body_limit(self):
        response=self.client.post('/api/essays',content=iter([b'a'*(13*1024*1024)]),headers={'Content-Type':'multipart/form-data; boundary=test'})
        self.assertEqual(response.status_code,413)

    def test_wechat_refund_query_verifies_amount_and_final_state(self):
        self.admin();ident=self.order();payments.apply_trade('wechat',self.trade(ident),'paid','hash')
        with patch('backend.payments.process_refund'):
            refund=self.client.post('/api/admin/orders/'+ident+'/refund',json={'reason':'测试退款完成查询'}).json()
        response={'out_trade_no':ident,'out_refund_no':refund['id'],'amount':{'refund':2900},'status':'SUCCESS'}
        with patch('backend.payments.wechat_request',return_value=response):payments.query_refund(refund)
        with accounts.database() as db:self.assertEqual(db.execute('SELECT status FROM refunds').fetchone()[0],'succeeded')

    def test_legacy_completed_jobs_migrate_usage_once(self):
        ident=uuid.uuid4().hex
        folder=self.root/ident;folder.mkdir()
        (folder/'meta.json').write_text(json.dumps({'status':'succeeded','stage':'done'}),encoding='utf-8')
        with accounts.database() as db:
            db.execute('DELETE FROM schema_migrations')
            db.execute('INSERT INTO jobs(id,user_id,filename,created) VALUES(?,?,?,?)',(ident,self.user['id'],'legacy.docx',time.time()))
        accounts.initialize();accounts.initialize()
        self.assertEqual(self.client.get('/api/subscription').json()['used_quota'],1)
        with accounts.database() as db:self.assertEqual(db.execute("SELECT COUNT(*) FROM quota_ledger WHERE action='legacy_commit'").fetchone()[0],1)


if __name__=='__main__':unittest.main()
