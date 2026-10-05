"""PayPro one-time essay credits; settlement is independent of subscriptions."""
import hashlib
import hmac
import json
import os
import time
import uuid
from decimal import Decimal
from datetime import datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from backend import accounts
from backend import paypro_payments as provider

router = APIRouter()


def migrate(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY,name TEXT NOT NULL,price_fen INTEGER NOT NULL CHECK(price_fen>0),essay_credits INTEGER NOT NULL CHECK(essay_credits>0),enabled INTEGER NOT NULL DEFAULT 1,created_at REAL NOT NULL,updated_at REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS payment_orders(order_no TEXT PRIMARY KEY,user_id INTEGER NOT NULL,product_id INTEGER NOT NULL,product_name TEXT NOT NULL,essay_credits INTEGER NOT NULL,original_amount INTEGER NOT NULL,actual_amount INTEGER NOT NULL,payment_method TEXT NOT NULL,provider_order_id TEXT,pay_num TEXT,qr_code_url TEXT,payment_url TEXT,status TEXT NOT NULL CHECK(status IN ('PENDING','PAID','EXPIRED','FAILED')),request_key TEXT NOT NULL,created_at REAL NOT NULL,paid_at REAL,expired_at REAL NOT NULL,error TEXT,UNIQUE(user_id,request_key));
    CREATE INDEX IF NOT EXISTS credit_order_user ON payment_orders(user_id,created_at);
    ''')
    if 'payment_code' not in db.columns('payment_orders'):
        db.execute('ALTER TABLE payment_orders ADD COLUMN payment_code TEXT')
    for ident, name, price, credits in ((1,'单次批改',290,1),(2,'基础套餐',990,5),(3,'进阶套餐',1990,15)):
        db.execute('INSERT INTO products VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING', (ident,name,price,credits,1,time.time(),time.time()))


class Purchase(BaseModel):
    model_config = ConfigDict(extra='forbid')
    productId: int = Field(gt=0)
    paymentMethod: str = Field(pattern='^(wechat|alipay)$')


def public(row):
    return {'orderNo':row['order_no'], 'productId':row['product_id'], 'productName':row['product_name'],
            'essayCredits':row['essay_credits'], 'amount':float(Decimal(row['actual_amount'])/100),
            'amountFen':row['actual_amount'], 'paymentMethod':row['payment_method'],
            'qrCodeUrl':row['qr_code_url'], 'paymentUrl':row['payment_url'], 'payNum':row['pay_num'], 'status':row['status'],
            'createdAt':row['created_at'], 'expiresAt':row['expired_at'], 'paidAt':row['paid_at'], 'error':row['error']}


def owned(order_no, user):
    with accounts.database() as db:
        db.execute("UPDATE payment_orders SET status='EXPIRED' WHERE order_no=? AND status='PENDING' AND expired_at<=?", (order_no,time.time()))
        row = db.execute('SELECT * FROM payment_orders WHERE order_no=? AND user_id=?', (order_no,user['id'])).fetchone()
    if not row:
        raise HTTPException(404,'订单不存在')
    return public(row)


@router.get('/api/payment/products')
def products():
    with accounts.database() as db:
        rows = [dict(row) for row in db.execute('SELECT id,name,price_fen,essay_credits FROM products WHERE enabled=1 ORDER BY id')]
    return {'products':rows, 'channels':{c:provider.configured(c) for c in ('wechat','alipay')}}


@router.post('/api/payment/create')
def create(data: Purchase, request: Request, user=Depends(accounts.current_user)):
    from backend import saas
    saas.rate_limit(request,user['id'],'credit_orders',10)
    if not provider.configured(data.paymentMethod):
        raise HTTPException(503,'PayPro 收款渠道尚未完成配置和到账验证')
    key = request.headers.get('Idempotency-Key','')
    if not 8 <= len(key) <= 128:
        raise HTTPException(400,'请提供 Idempotency-Key 防止重复下单')
    now = time.time()
    ident = 'ESSAY' + datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d') + uuid.uuid4().hex[:18].upper()
    with accounts.database() as db:
        prior = db.execute('SELECT * FROM payment_orders WHERE user_id=? AND request_key=?',(user['id'],key)).fetchone()
        if prior:
            if prior['product_id'] != data.productId or prior['payment_method'] != data.paymentMethod:
                raise HTTPException(409,'同一请求标识不能用于不同商品或渠道')
            return public(prior)
        product = db.execute('SELECT * FROM products WHERE id=? AND enabled=1',(data.productId,)).fetchone()
        if not product:
            raise HTTPException(404,'商品不存在或已下架')
        db.execute('INSERT INTO payment_orders(order_no,user_id,product_id,product_name,essay_credits,original_amount,actual_amount,payment_method,status,request_key,created_at,expired_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                   (ident,user['id'],product['id'],product['name'],product['essay_credits'],product['price_fen'],product['price_fen'],data.paymentMethod,'PENDING',key,now,now+900))
    params = {'orderNo':ident,'amount':format(Decimal(product['price_fen'])/100,'.2f'),
              'payType':'wechat' if data.paymentMethod == 'wechat' else 'alipay_dmf',
              'description':product['name'],'userId':str(user['id']),
              'notifyUrl':os.environ['PUBLIC_BASE_URL'].rstrip('/')+'/api/payment/callback',
              'timestamp':int(now*1000),'expireSeconds':900}
    # PayPro productId refers to its own digital-goods catalog, not our local product.
    params['sign'] = provider.signature(params)
    try:
        response = httpx.post(os.environ['PAYPRO_BASE_URL'].rstrip('/')+'/api/openapi/add',json=params,timeout=20)
        response.raise_for_status()
        envelope = response.json()
        result = envelope['data']
        if envelope['code'] != 200 or result['orderNo'] != ident or result['payType'] != params['payType'] or provider.fen(result['amount']) != product['price_fen']:
            raise ValueError('Provider order mismatch')
        # Current callback sends original amount; decrement mode cannot prove actual settlement.
        if provider.fen(result.get('actualAmount',result['amount'])) != product['price_fen'] or result.get('matchMode','REMARK') != 'REMARK' or result.get('fallbackToRemark'):
            raise ValueError('Decrement mode unsupported')
        base = urlsplit(os.environ['PAYPRO_BASE_URL'])
        for field in ('returnUrl',) if data.paymentMethod == 'alipay' else ('returnUrl','qrCodeUrl'):
            target = urlsplit(result[field])
            if target.scheme != 'https' or target.netloc != base.netloc or target.username:
                raise ValueError('Untrusted payment URL')
        payment_code = result.get('qrCode') if data.paymentMethod == 'alipay' else None
        if data.paymentMethod == 'alipay':
            code_url = urlsplit(payment_code or '')
            if code_url.scheme != 'https' or code_url.hostname != 'qr.alipay.com' or code_url.username:
                raise ValueError('Missing native Alipay QR code')
        qr_url = '/api/payment/'+ident+'/qr' if payment_code else result['qrCodeUrl']
        if not result.get('payNum'):
            raise ValueError('Missing payment remark')
        with accounts.database() as db:
            db.execute('UPDATE payment_orders SET provider_order_id=?,pay_num=?,qr_code_url=?,payment_url=?,payment_code=?,error=NULL WHERE order_no=?',
                       (str(result.get('orderId') or ident),str(result['payNum']),qr_url,result['returnUrl'],payment_code,ident))
    except Exception:
        # A timeout can leave a real provider order: keep the same key, never silently recreate.
        with accounts.database() as db:
            db.execute('UPDATE payment_orders SET error=? WHERE order_no=?',('支付下单结果待核查，请勿重复创建订单',ident))
    return owned(ident,user)


@router.get('/api/payment/orders')
def orders(user=Depends(accounts.current_user)):
    with accounts.database() as db:
        db.execute("UPDATE payment_orders SET status='EXPIRED' WHERE user_id=? AND status='PENDING' AND expired_at<=?",(user['id'],time.time()))
        return [public(row) for row in db.execute('SELECT * FROM payment_orders WHERE user_id=? ORDER BY created_at DESC LIMIT 100',(user['id'],))]


@router.get('/api/payment/{order_no}/status')
@router.get('/api/payment/{order_no}')
def detail(order_no: str, user=Depends(accounts.current_user)):
    return owned(order_no,user)


@router.get('/api/payment/{order_no}/qr')
def qr(order_no: str,user=Depends(accounts.current_user)):
    import io
    import qrcode
    from fastapi.responses import Response
    order = owned(order_no,user)
    if order['status'] != 'PENDING':
        raise HTTPException(409,'订单暂不可支付')
    with accounts.database() as db:
        code = db.execute('SELECT payment_code FROM payment_orders WHERE order_no=?',(order_no,)).fetchone()['payment_code']
    if not code:
        raise HTTPException(409,'二维码尚未就绪')
    image = io.BytesIO()
    qrcode.make(code).save(image,format='PNG')
    return Response(image.getvalue(),media_type='image/png',headers={'Cache-Control':'no-store'})


@router.post('/api/payment/callback')
async def callback(request: Request):
    raw = await request.body()
    if len(raw) > 64000:
        raise HTTPException(413,'通知过大')
    try:
        def unique(pairs):
            value = dict(pairs)
            if len(value) != len(pairs):
                raise ValueError('Duplicate keys')
            return value
        params = json.loads(raw,parse_float=Decimal,object_pairs_hook=unique)
        if set(params) != {'orderNo','amount','payNum','sign'} or not hmac.compare_digest(provider.signature(params),str(params['sign'])):
            raise ValueError('Invalid receipt')
        rejected = False
        with accounts.database() as db:
            row = db.execute('SELECT * FROM payment_orders WHERE order_no=?',(params['orderNo'],)).fetchone()
            if not row or not provider.configured(row['payment_method']) or not row['payment_url'] or str(params['payNum']) != row['pay_num'] or provider.fen(params['amount']) != row['actual_amount']:
                raise ValueError('Order mismatch')
            if row['status'] == 'PAID':
                return PlainTextResponse('success')
            if row['status'] != 'PENDING' or row['expired_at'] <= time.time():
                if row['status'] == 'PENDING':
                    db.execute("UPDATE payment_orders SET status='EXPIRED' WHERE order_no=?",(row['order_no'],))
                rejected = True
            else:
                user_id, credits, now = row['user_id'],row['essay_credits'],time.time()
                db.execute('UPDATE users SET essay_credits=essay_credits+? WHERE id=?',(credits,user_id))
                db.execute("INSERT INTO quota_periods(id,user_id,plan,start_at,end_at,quota) VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET quota=quota_periods.quota+excluded.quota",
                           (f'credits-{user_id}',user_id,'credits',now,253402300799,credits))
                db.execute('INSERT INTO quota_ledger VALUES(?,?,?,?,?,?,?)',(uuid.uuid4().hex,user_id,None,f'credits-{user_id}','purchase:'+row['order_no'],credits,now))
                db.execute("UPDATE payment_orders SET status='PAID',paid_at=?,error=NULL WHERE order_no=?",(now,row['order_no']))
                from backend import saas
                saas.audit(db,None,'credit_payment_settled',row['order_no'],f'支付入账，增加 {credits} 次批改额度')
        if rejected:
            raise ValueError('Expired or failed order')
    except Exception:
        from backend import payments
        payments.record_rejection('paypro_credits',raw)
        raise HTTPException(400,'支付通知校验失败或订单已过期') from None
    return PlainTextResponse('success')


@router.get('/api/admin/payments')
def admin_orders(user=Depends(accounts.administrator)):
    with accounts.database() as db:
        return [dict(row) for row in db.execute('SELECT * FROM payment_orders ORDER BY created_at DESC LIMIT 200')]


@router.get('/payment/{order_no}',response_class=HTMLResponse)
def payment_page(order_no: str,user=Depends(accounts.current_user)):
    owned(order_no,user)
    from pathlib import Path
    return (Path(__file__).resolve().parents[1]/'frontend/credit-payment.html').read_text(encoding='utf-8')
