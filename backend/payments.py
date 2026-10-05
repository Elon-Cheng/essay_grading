"""WeChat API v3 Native and Alipay RSA2 QR payments; no simulated production checkout."""
import base64
import hashlib
import io
import json
import os
import secrets
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, PlainTextResponse
from pydantic import BaseModel, Field
from backend import accounts
from backend import saas

router = APIRouter(prefix='/api')


def checkout_options():
    from backend import paypro_payments
    mode = os.getenv('PAYMENTS_MODE', 'merchant')
    if mode == 'manual':
        from backend.manual_payments import options
        return options()
    price = os.getenv('PRO_PRICE_FEN', '')
    teacher_price = os.getenv('TEACHER_PRICE_FEN', '')
    return {'payment_mode': mode, 'price_fen': int(price) if price.isdigit() and int(price) > 0 else None,
            'prices': {'pro':int(price) if price.isdigit() and int(price)>0 else None,'teacher':int(teacher_price) if teacher_price.isdigit() and int(teacher_price)>0 else None},
            'channels': {c: (mode == 'merchant' and configured(c)) or (mode == 'paypro' and paypro_payments.configured(c)) for c in ('wechat', 'alipay')}}


def configured(channel):
    names = ['WECHAT_APP_ID', 'WECHAT_MCH_ID', 'WECHAT_SERIAL', 'WECHAT_PRIVATE_KEY_PATH', 'WECHAT_API_V3_KEY', 'WECHAT_PUBLIC_KEY_PATH', 'WECHAT_PUBLIC_KEY_ID'] if channel == 'wechat' else ['ALIPAY_APP_ID', 'ALIPAY_SELLER_ID', 'ALIPAY_PRIVATE_KEY_PATH', 'ALIPAY_PUBLIC_KEY_PATH']
    if not all(os.getenv(n) for n in names) or not os.getenv('PUBLIC_BASE_URL', '').startswith('https://'):
        return False
    try:
        private_key(channel)
        public_key(channel)
        return channel != 'wechat' or len(os.environ['WECHAT_API_V3_KEY'].encode()) == 32
    except (OSError, ValueError, TypeError):
        return False


def private_key(channel):
    return serialization.load_pem_private_key(Path(os.environ[channel.upper() + '_PRIVATE_KEY_PATH']).read_bytes(), password=None)


def public_key(channel):
    return serialization.load_pem_public_key(Path(os.environ[channel.upper() + '_PUBLIC_KEY_PATH']).read_bytes())


def sign(channel, message):
    return base64.b64encode(private_key(channel).sign(message.encode(), padding.PKCS1v15(), hashes.SHA256())).decode()


def verify(channel, signature, message):
    public_key(channel).verify(base64.b64decode(signature, validate=True), message, padding.PKCS1v15(), hashes.SHA256())


def wechat_verify(headers, body):
    stamp, nonce, signature, serial = (headers.get(n, '') for n in ('wechatpay-timestamp', 'wechatpay-nonce', 'wechatpay-signature', 'wechatpay-serial'))
    if serial != os.getenv('WECHAT_PUBLIC_KEY_ID') or abs(time.time() - int(stamp)) > 300:
        raise ValueError('微信签名标识或时间戳无效')
    verify('wechat', signature, stamp.encode() + b'\n' + nonce.encode() + b'\n' + body + b'\n')


def wechat_request(method, path, payload=None):
    body = json.dumps(payload, ensure_ascii=False, separators=(',', ':')) if payload is not None else ''
    stamp, nonce = str(int(time.time())), secrets.token_hex(16)
    signature = sign('wechat', f'{method}\n{path}\n{stamp}\n{nonce}\n{body}\n')
    authorization = f'WECHATPAY2-SHA256-RSA2048 mchid="{os.environ["WECHAT_MCH_ID"]}",nonce_str="{nonce}",timestamp="{stamp}",serial_no="{os.environ["WECHAT_SERIAL"]}",signature="{signature}"'
    response = httpx.request(method, 'https://api.mch.weixin.qq.com' + path, content=body.encode(), headers={'Authorization': authorization, 'Content-Type': 'application/json', 'Accept': 'application/json', 'Wechatpay-Serial': os.environ['WECHAT_PUBLIC_KEY_ID']}, timeout=20)
    wechat_verify(response.headers, response.content)
    response.raise_for_status()
    return response.json() if response.content else {}


def alipay_request(method, business):
    params = {'app_id': os.environ['ALIPAY_APP_ID'], 'method': method, 'format': 'JSON', 'charset': 'utf-8', 'sign_type': 'RSA2',
              'timestamp': datetime.now(saas.TZ).strftime('%Y-%m-%d %H:%M:%S'), 'version': '1.0',
              'biz_content': json.dumps(business, ensure_ascii=False, separators=(',', ':'))}
    if method == 'alipay.trade.precreate':
        params['notify_url'] = os.environ['PUBLIC_BASE_URL'].rstrip('/') + '/api/payments/alipay/notify'
    params['sign'] = sign('alipay', '&'.join(f'{k}={params[k]}' for k in sorted(params)))
    gateway = os.getenv('ALIPAY_GATEWAY', 'https://openapi.alipay.com/gateway.do')
    if gateway not in ('https://openapi.alipay.com/gateway.do', 'https://openapi-sandbox.dl.alipaydev.com/gateway.do'):
        raise ValueError('支付宝网关地址无效')
    response = httpx.post(gateway, data=params, timeout=20)
    response.raise_for_status()
    # Verify the original JSON response value bytes, without re-serialization.
    raw = response.text
    name = method.replace('.', '_') + '_response'
    marker = json.dumps(name) + ':'
    import re
    found = re.search(r'"' + re.escape(name) + r'"\s*:', raw)
    if not found:
        raise ValueError('支付宝响应缺少结果')
    start = found.end()
    while raw[start].isspace():
        start += 1
    data, consumed = json.JSONDecoder().raw_decode(raw[start:])
    envelope = json.loads(raw)
    verify('alipay', envelope['sign'], raw[start:start + consumed].encode('utf-8'))
    if data.get('code') != '10000':
        raise RuntimeError('支付渠道返回错误：' + str(data.get('sub_code', data.get('code'))))
    return data


def precreate(order):
    title = '墨评 '+('Teacher' if order['plan']=='teacher' else 'Pro')+' 月度会员'
    if order['channel'] == 'wechat':
        data = wechat_request('POST', '/v3/pay/transactions/native', {'appid': os.environ['WECHAT_APP_ID'], 'mchid': os.environ['WECHAT_MCH_ID'],
            'description': title, 'out_trade_no': order['id'], 'notify_url': os.environ['PUBLIC_BASE_URL'].rstrip('/') + '/api/payments/wechat/notify',
            'time_expire': datetime.fromtimestamp(order['expires'], timezone.utc).isoformat(), 'amount': {'total': order['amount_fen'], 'currency': 'CNY'}})
        return data['code_url']
    data = alipay_request('alipay.trade.precreate', {'out_trade_no': order['id'], 'total_amount': str(Decimal(order['amount_fen']) / 100), 'subject': title, 'timeout_express': '30m'})
    return data['qr_code']


def normalize_trade(channel, data, from_query=False):
    if channel == 'wechat':
        if data.get('appid') != os.getenv('WECHAT_APP_ID') or data.get('mchid') != os.getenv('WECHAT_MCH_ID'):
            raise ValueError('微信商户信息不匹配')
        return {'order_id': data['out_trade_no'], 'transaction_id': data.get('transaction_id'), 'success': data.get('trade_state') == 'SUCCESS',
                'amount': data['amount']['total'], 'currency': data['amount'].get('currency', 'CNY')}
    # Trade query is authenticated with this app's key and its signed response;
    # unlike async notifications, the official query response may omit seller_id.
    if not from_query and (data.get('app_id') != os.getenv('ALIPAY_APP_ID') or data.get('seller_id') != os.getenv('ALIPAY_SELLER_ID')):
        raise ValueError('支付宝商户信息不匹配')
    amount = Decimal(str(data['total_amount'])) * 100
    if amount != amount.to_integral_value():
        raise ValueError('支付宝金额格式错误')
    return {'order_id': data['out_trade_no'], 'transaction_id': data.get('trade_no'), 'success': data.get('trade_status') in ('TRADE_SUCCESS', 'TRADE_FINISHED'), 'amount': int(amount), 'currency': 'CNY'}


def apply_trade(channel, trade, event_key, payload_hash, payment_mode="merchant"):
    rejected = None
    with accounts.database() as db:
        existing = db.execute('SELECT * FROM payment_events WHERE channel=? AND event_key=?', (channel, event_key)).fetchone()
        if existing:
            if existing['payload_hash'] != payload_hash or existing['status'] != 'processed':
                raise HTTPException(400, '通知冲突或此前未通过校验')
            return
        order = db.execute('SELECT * FROM orders WHERE id=?', (trade['order_id'],)).fetchone()
        if not order or order['payment_mode'] != payment_mode or order['channel'] != channel or order['amount_fen'] != trade['amount'] or trade['currency'] != 'CNY':
            rejected = '订单、渠道或金额不匹配'
        elif trade['success'] and not trade['transaction_id']:
            rejected = '缺少支付交易号'
        elif trade['success']:
            clash = db.execute('SELECT id FROM orders WHERE channel=? AND transaction_id=? AND id<>?', (channel, trade['transaction_id'], order['id'])).fetchone()
            if clash or (order['transaction_id'] and order['transaction_id'] != trade['transaction_id']):
                rejected = '支付交易号冲突'
        db.execute('INSERT INTO payment_events VALUES(?,?,?,?,?,?,?,?)', (uuid.uuid4().hex, channel, event_key, trade['order_id'], payload_hash, 'rejected' if rejected else 'processed', time.time(), rejected))
        if not rejected and trade['success'] and order['status'] not in ('paid', 'refund_pending', 'refunded'):
            start = max(time.time(), db.execute("SELECT MAX(expire_at) AS end FROM subscriptions WHERE user_id=? AND status='active'", (order['user_id'],)).fetchone()['end'] or 0)
            db.execute('INSERT INTO subscriptions VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(source_order_id) DO NOTHING', (uuid.uuid4().hex, order['user_id'], order['plan'], 'active', start, saas.add_month(start), order['quota'], order['id'], time.time()))
            db.execute("UPDATE orders SET status='paid',paid_at=?,transaction_id=?,error=NULL WHERE id=?", (time.time(), trade['transaction_id'], order['id']))
            saas.audit(db, None, 'payment_settled', order['id'], '已核验渠道支付结果并发放权益')
    if rejected:
        raise HTTPException(400, rejected)


def query_order(order):
    if order['channel'] == 'wechat':
        data = wechat_request('GET', f'/v3/pay/transactions/out-trade-no/{order["id"]}?mchid={os.environ["WECHAT_MCH_ID"]}')
    else:
        data = alipay_request('alipay.trade.query', {'out_trade_no': order['id']})
    trade = normalize_trade(order['channel'], data, from_query=True)
    if trade['order_id'] != order['id']:
        raise ValueError('查单结果订单号不匹配')
    if trade['success']:
        canonical = json.dumps(trade, sort_keys=True)
        apply_trade(order['channel'], trade, 'query:' + str(trade['transaction_id']), hashlib.sha256(canonical.encode()).hexdigest())
    elif (data.get('trade_state') == 'CLOSED' or data.get('trade_status') == 'TRADE_CLOSED'):
        with accounts.database() as db:
            db.execute("UPDATE orders SET status='closed' WHERE id=? AND status IN ('pending','creating')", (order['id'],))
    with accounts.database() as db:
        db.execute('UPDATE orders SET last_checked=? WHERE id=?', (time.time(), order['id']))


def public_order(row):
    data = dict(row)
    data.pop('request_key', None)
    return data


def record_rejection(channel, raw):
    payload_hash = hashlib.sha256(raw).hexdigest()
    with accounts.database() as db:
        db.execute('INSERT INTO payment_events VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(channel,event_key) DO NOTHING', (uuid.uuid4().hex,channel,'invalid:'+payload_hash,None,payload_hash,'rejected',time.time(),'通知验签或商户校验失败'))


class OrderInput(BaseModel):
    plan: str = Field(default='pro', pattern='^(pro|teacher)$')
    channel: str = Field(pattern='^(wechat|alipay)$')


@router.post('/orders')
def create_order(data: OrderInput, request: Request, user=Depends(accounts.current_user)):
    saas.rate_limit(request, user['id'], 'orders', 10)
    key = request.headers.get('Idempotency-Key', '')
    if not 8 <= len(key) <= 128:
        raise HTTPException(400, '请提供有效的订单幂等键')
    with accounts.database() as db:
        prior = db.execute('SELECT * FROM orders WHERE user_id=? AND request_key=?', (user['id'], key)).fetchone()
    if prior:
        if prior['channel'] != data.channel or prior['plan'] != data.plan:
            raise HTTPException(409, '同一幂等键不能用于不同订单')
        return public_order(prior)
    if os.getenv('PAYMENTS_MODE', 'merchant') == 'manual':
        from backend.manual_payments import create
        return create(data, key, user)
    if os.getenv('PAYMENTS_MODE', 'merchant') == 'paypro':
        from backend.paypro_payments import create
        return create(data, key, user)
    if os.getenv('PAYMENTS_MODE', 'merchant') != 'merchant':
        raise HTTPException(503, '暂未开放购买')
    price = checkout_options()['prices'][data.plan]
    with accounts.database() as db:
        plan = db.execute('SELECT * FROM plans WHERE id=?', (data.plan,)).fetchone()
    if not plan or not plan['enabled'] or price is None:
        raise HTTPException(503, '该套餐暂未开放购买')
    if not configured(data.channel):
        raise HTTPException(503, '该支付渠道暂未开放')
    now, ident = time.time(), uuid.uuid4().hex
    with accounts.database() as db:
        prior = db.execute('SELECT * FROM orders WHERE user_id=? AND request_key=?', (user['id'], key)).fetchone()
        if prior:
            if prior['channel'] != data.channel or prior['plan'] != data.plan:
                raise HTTPException(409, '同一幂等键不能用于不同订单')
            return public_order(prior)
        db.execute('INSERT INTO orders(id,user_id,plan,quota,amount_fen,currency,channel,status,request_key,created,expires) VALUES(?,?,?,?,?,?,?,?,?,?,?)', (ident, user['id'], plan['id'], plan['quota'], price, 'CNY', data.channel, 'creating', key, now, now + 1800))
        order = dict(db.execute('SELECT * FROM orders WHERE id=?', (ident,)).fetchone())
    try:
        url = precreate(order)
        with accounts.database() as db:
            db.execute("UPDATE orders SET status=CASE WHEN status='creating' THEN 'pending' ELSE status END,code_url=? WHERE id=?", (url, ident))
    except Exception:
        with accounts.database() as db:
            db.execute('UPDATE orders SET error=? WHERE id=?', ('支付下单结果待确认，请稍后查询订单', ident))
        # Preserve creating state: a timed-out precreate may already exist at the provider.
    with accounts.database() as db:
        return public_order(db.execute('SELECT * FROM orders WHERE id=?', (ident,)).fetchone())


@router.get('/orders')
def orders(user=Depends(accounts.current_user)):
    with accounts.database() as db:
        return [public_order(r) for r in db.execute('SELECT * FROM orders WHERE user_id=? ORDER BY created DESC LIMIT 100', (user['id'],))]


def owned_order(ident, user):
    with accounts.database() as db:
        row = db.execute('SELECT * FROM orders WHERE id=? AND user_id=?', (ident, user['id'])).fetchone()
    if not row:
        raise HTTPException(404, '订单不存在')
    return row


@router.get('/orders/{ident}')
def order_detail(ident: str, user=Depends(accounts.current_user)):
    return public_order(owned_order(ident, user))


@router.post('/orders/{ident}/refresh')
def refresh_order(ident: str, request: Request, user=Depends(accounts.current_user)):
    saas.rate_limit(request, user['id'], 'query_order', 12)
    order = owned_order(ident, user)
    if order['payment_mode'] == 'merchant' and order['status'] in ('creating', 'pending') and configured(order['channel']):
        try:
            query_order(order)
        except Exception:
            raise HTTPException(502, '支付结果暂未确认，请稍后重试') from None
    return public_order(owned_order(ident, user))


@router.get('/orders/{ident}/qr')
def order_qr(ident: str, user=Depends(accounts.current_user)):
    order = owned_order(ident, user)
    if order['payment_mode'] == 'manual':
        from backend.manual_payments import qr_response
        return qr_response(order)
    if not order['code_url'] or order['status'] != 'pending' or order['expires'] < time.time():
        raise HTTPException(409, '订单暂不可支付，请刷新支付状态')
    import qrcode
    buffer = io.BytesIO()
    qrcode.make(order['code_url']).save(buffer, format='PNG')
    return Response(buffer.getvalue(), media_type='image/png')


@router.post('/payments/wechat/notify')
async def wechat_notify(request: Request):
    if not configured('wechat'):
        raise HTTPException(503, '支付未配置')
    raw = await request.body()
    if len(raw) > 256_000:
        raise HTTPException(413, '通知过大')
    try:
        wechat_verify(request.headers, raw)
        body = json.loads(raw)
        resource = body['resource']
        if resource['algorithm'] != 'AEAD_AES_256_GCM':
            raise ValueError('未知加密算法')
        decrypted = AESGCM(os.environ['WECHAT_API_V3_KEY'].encode()).decrypt(resource['nonce'].encode(), base64.b64decode(resource['ciphertext']), resource.get('associated_data', '').encode())
        trade = normalize_trade('wechat', json.loads(decrypted))
        if body['event_type'] != 'TRANSACTION.SUCCESS' or not trade['success']:
            raise ValueError('通知类型不匹配')
        apply_trade('wechat', trade, body['id'], hashlib.sha256(raw).hexdigest())
    except HTTPException:
        raise
    except Exception:
        record_rejection('wechat', raw)
        raise HTTPException(400, '支付通知验签或内容校验失败') from None
    return Response(status_code=204)


@router.post('/payments/alipay/notify')
async def alipay_notify(request: Request):
    if not configured('alipay'):
        raise HTTPException(503, '支付未配置')
    raw = await request.body()
    if len(raw) > 64_000:
        raise HTTPException(413, '通知过大')
    try:
        from urllib.parse import parse_qsl
        pairs = parse_qsl(raw.decode('utf-8'), keep_blank_values=True)
        if len({k for k, v in pairs}) != len(pairs):
            raise ValueError('重复参数')
        params = dict(pairs)
        if params.get('sign_type') != 'RSA2' or params.get('app_id') != os.environ['ALIPAY_APP_ID']:
            raise ValueError('应用或签名类型不匹配')
        canonical = '&'.join(f'{k}={params[k]}' for k in sorted(params) if k not in ('sign', 'sign_type') and params[k])
        verify('alipay', params['sign'], canonical.encode('utf-8'))
        trade = normalize_trade('alipay', params)
        apply_trade('alipay', trade, params['notify_id'], hashlib.sha256(canonical.encode()).hexdigest())
    except HTTPException:
        raise
    except Exception:
        record_rejection('alipay', raw)
        raise HTTPException(400, '支付通知验签或内容校验失败') from None
    return PlainTextResponse('success')


class RefundInput(BaseModel):
    reason: str = Field(min_length=5, max_length=200)


def process_refund(refund):
    with accounts.database() as db:
        order = db.execute('SELECT * FROM orders WHERE id=?', (refund['order_id'],)).fetchone()
    if order['channel'] == 'wechat':
        # Reusing the same out_refund_no is safe after an uncertain request.
        result = wechat_request('POST', '/v3/refund/domestic/refunds', {'out_trade_no': order['id'], 'out_refund_no': refund['id'], 'reason': refund['reason'], 'amount': {'refund': refund['amount_fen'], 'total': order['amount_fen'], 'currency': 'CNY'}})
        succeeded = result.get('status') == 'SUCCESS'
        provider_id = result.get('refund_id')
    else:
        result = alipay_request('alipay.trade.refund', {'out_trade_no': order['id'], 'refund_amount': str(Decimal(refund['amount_fen']) / 100), 'out_request_no': refund['id'], 'refund_reason': refund['reason']})
        succeeded, provider_id = True, result.get('trade_no')
    with accounts.database() as db:
        db.execute('UPDATE refunds SET status=?,provider_id=?,updated=?,error=NULL WHERE id=?', ('succeeded' if succeeded else 'processing', provider_id, time.time(), refund['id']))
        if succeeded:
            db.execute("UPDATE orders SET status='refunded' WHERE id=?", (order['id'],))
            db.execute("UPDATE subscriptions SET status='revoked' WHERE source_order_id=?", (order['id'],))
        saas.audit(db, None, 'refund_reconciled', order['id'], '渠道退款结果已核验')


def query_refund(refund):
    with accounts.database() as db:
        order = db.execute('SELECT * FROM orders WHERE id=?', (refund['order_id'],)).fetchone()
    if order['channel'] == 'wechat':
        result = wechat_request('GET', '/v3/refund/domestic/refunds/' + refund['id'])
        if result.get('out_trade_no') != order['id'] or result.get('out_refund_no') != refund['id'] or result.get('amount', {}).get('refund') != refund['amount_fen']:
            raise ValueError('退款查询结果不匹配')
        state = {'SUCCESS':'succeeded', 'PROCESSING':'processing', 'CLOSED':'failed', 'ABNORMAL':'failed'}.get(result.get('status'), 'processing')
    else:
        result = alipay_request('alipay.trade.fastpay.refund.query', {'out_trade_no': order['id'], 'out_request_no': refund['id']})
        if result.get('out_trade_no') != order['id'] or result.get('out_request_no') != refund['id'] or Decimal(str(result.get('refund_amount', '0'))) * 100 != refund['amount_fen']:
            raise ValueError('退款查询结果不匹配')
        state = 'succeeded' if result.get('refund_status') == 'REFUND_SUCCESS' else 'processing'
    with accounts.database() as db:
        db.execute('UPDATE refunds SET status=?,updated=?,error=? WHERE id=?', (state, time.time(), '请在商户后台核查异常退款' if state == 'failed' else None, refund['id']))
        if state == 'succeeded':
            db.execute("UPDATE orders SET status='refunded' WHERE id=?", (order['id'],))
            db.execute("UPDATE subscriptions SET status='revoked' WHERE source_order_id=?", (order['id'],))


@router.post('/admin/orders/{ident}/refund')
def refund_order(ident: str, data: RefundInput, user=Depends(accounts.administrator)):
    with accounts.database() as db:
        order = db.execute('SELECT * FROM orders WHERE id=?', (ident,)).fetchone()
        if not order or order['status'] not in ('paid', 'refund_pending', 'refunded'):
            raise HTTPException(409, '该订单不可退款')
        if order['payment_mode'] == 'paypro':
            raise HTTPException(409, 'Paypro 未提供退款接口，请先在收款账户退款并联系管理员登记')
        if order['payment_mode'] == 'manual':
            raise HTTPException(409, '个人收款订单请实际转账退款后，在人工审核中登记退款结果')
        refund = db.execute('SELECT * FROM refunds WHERE order_id=?', (ident,)).fetchone()
        if refund:
            return dict(refund)
        ident_refund = uuid.uuid4().hex
        db.execute('INSERT INTO refunds VALUES(?,?,?,?,?,?,?,?,?)', (ident_refund, ident, order['amount_fen'], 'pending', None, data.reason, time.time(), time.time(), None))
        db.execute("UPDATE orders SET status='refund_pending' WHERE id=?", (ident,))
        # Stop new use while refund is pending, including future segments from this order.
        db.execute("UPDATE subscriptions SET status='revoked' WHERE source_order_id=?", (ident,))
        saas.audit(db, user['id'], 'refund_requested', ident, data.reason)
        refund = dict(db.execute('SELECT * FROM refunds WHERE id=?', (ident_refund,)).fetchone())
    try:
        process_refund(refund)
    except Exception:
        with accounts.database() as db:
            db.execute('UPDATE refunds SET error=?,updated=? WHERE id=?', ('退款结果待确认，将继续查单', time.time(), ident_refund))
    with accounts.database() as db:
        return dict(db.execute('SELECT * FROM refunds WHERE id=?', (ident_refund,)).fetchone())


def reconcile():
    with accounts.database() as db:
        rows = [dict(r) for r in db.execute("SELECT * FROM orders WHERE payment_mode='merchant' AND status IN ('creating','pending') AND (last_checked IS NULL OR last_checked<?) ORDER BY created LIMIT 20", (time.time() - 60,))]
        refunds = [dict(r) for r in db.execute("SELECT * FROM refunds WHERE status IN ('pending','processing') AND updated<? LIMIT 20", (time.time() - 60,))]
    for order in rows:
        if configured(order['channel']):
            try:
                query_order(order)
            except Exception:
                with accounts.database() as db:
                    db.execute('UPDATE orders SET last_checked=?,error=? WHERE id=?', (time.time(), '渠道状态待核查', order['id']))
    for refund in refunds:
        try:
            if refund['status'] == 'processing':
                query_refund(refund)
            else:
                process_refund(refund)
        except Exception:
            with accounts.database() as db:
                db.execute('UPDATE refunds SET updated=?,error=? WHERE id=?', (time.time(), '退款结果待核查', refund['id']))


@router.post("/payments/paypro/notify")
async def paypro_notify(request: Request):
    from backend.paypro_payments import notify
    return await notify(request)
