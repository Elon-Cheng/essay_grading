"""Paypro OpenAPI adapter. Signed receipts identify Paypro orders, not bank trades."""
import hashlib
import hmac
import json
import os
import time
import uuid
from decimal import Decimal
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException
from fastapi.responses import PlainTextResponse
from backend import accounts
from backend import saas


def configured(channel):
    base = urlsplit(os.getenv('PAYPRO_BASE_URL', ''))
    public = urlsplit(os.getenv('PUBLIC_BASE_URL', ''))
    return bool(base.scheme == 'https' and base.netloc and not base.username
                and not base.query and not base.fragment and public.scheme == 'https'
                and public.netloc and len(os.getenv('PAYPRO_SECRET', '')) >= 32
                and os.getenv('PAYPRO_SETTLEMENT_VERIFIED') == '1'
                and os.getenv('PAYPRO_' + channel.upper() + '_ENABLED') == '1')


def signature(params):
    values = []
    for key in sorted(params):
        value = params[key]
        if key == 'sign' or value is None or value == '':
            continue
        if key == 'amount':
            value = format(Decimal(str(value)), '.2f')
        values.append(f'{key}={value}')
    canonical = '&'.join(values) + '&key=' + os.environ['PAYPRO_SECRET']
    return hashlib.md5(canonical.encode('utf-8')).hexdigest().upper()


def fen(value):
    amount = Decimal(str(value)) * 100
    if not amount.is_finite() or amount <= 0 or amount != amount.to_integral_value():
        raise ValueError('Invalid payment amount')
    return int(amount)


def create(data, key, user):
    from backend import payments
    price = payments.checkout_options()['prices'][data.plan]
    if not configured(data.channel) or price is None:
        raise HTTPException(503, 'Paypro 渠道尚未完成配置和到账验证')
    now, ident = time.time(), uuid.uuid4().hex
    with accounts.database() as db:
        plan = db.execute('SELECT * FROM plans WHERE id=?', (data.plan,)).fetchone()
        if not plan or not plan['enabled']:
            raise HTTPException(503, '该套餐暂未开放购买')
        prior = db.execute('SELECT * FROM orders WHERE user_id=? AND request_key=?', (user['id'], key)).fetchone()
        if prior:
            if prior['channel'] != data.channel or prior['plan'] != data.plan:
                raise HTTPException(409, '同一幂等键不能用于不同订单')
            return payments.public_order(prior)
        db.execute('INSERT INTO orders(id,user_id,plan,quota,amount_fen,currency,channel,status,request_key,created,expires,payment_mode) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                   (ident, user['id'], data.plan, plan['quota'], price, 'CNY', data.channel, 'creating', key, now, now + 1800, 'paypro'))
    pay_type = 'wechat' if data.channel == 'wechat' else 'alipay_dmf'
    params = {'orderNo': ident, 'amount': format(Decimal(price) / 100, '.2f'),
              'payType': pay_type, 'description': '墨评月度会员', 'userId': str(user['id']),
              'notifyUrl': os.environ['PUBLIC_BASE_URL'].rstrip('/') + '/api/payments/paypro/notify',
              'timestamp': int(now * 1000), 'expireSeconds': 1800}
    params['sign'] = signature(params)
    try:
        response = httpx.post(os.environ['PAYPRO_BASE_URL'].rstrip('/') + '/api/openapi/add', json=params, timeout=20)
        response.raise_for_status()
        envelope = response.json()
        result = envelope['data']
        if envelope['code'] != 200 or result['orderNo'] != ident or result['payType'] != pay_type or fen(result['amount']) != price:
            raise ValueError('Paypro order mismatch')
        if fen(result.get('actualAmount', result['amount'])) != price or result.get('matchMode', 'REMARK') != 'REMARK' or result.get('fallbackToRemark'):
            raise ValueError('Disable Paypro decrement pricing')
        url = result['returnUrl']
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.netloc != urlsplit(os.environ['PAYPRO_BASE_URL']).netloc or parsed.username:
            raise ValueError('Invalid Paypro checkout URL')
        with accounts.database() as db:
            db.execute("UPDATE orders SET code_url=?,payment_receiver=?,status=CASE WHEN status='creating' THEN 'pending' ELSE status END WHERE id=?",
                       (url, result.get('payNum') or '', ident))
    except Exception:
        with accounts.database() as db:
            db.execute('UPDATE orders SET error=? WHERE id=? AND status<>?', ('Paypro 下单结果待确认，请联系管理员核查', ident, 'paid'))
    with accounts.database() as db:
        return payments.public_order(db.execute('SELECT * FROM orders WHERE id=?', (ident,)).fetchone())


async def notify(request):
    from backend import payments
    raw = await request.body()
    if len(raw) > 64000:
        raise HTTPException(413, '通知过大')
    try:
        def unique(pairs):
            result = dict(pairs)
            if len(result) != len(pairs):
                raise ValueError('Duplicate fields')
            return result
        params = json.loads(raw, parse_float=Decimal, object_pairs_hook=unique)
        if set(params) != {'orderNo', 'amount', 'payNum', 'sign'}:
            raise ValueError('Unexpected receipt fields')
        if not hmac.compare_digest(signature(params), str(params['sign'])):
            raise ValueError('Invalid signature')
        with accounts.database() as db:
            order = db.execute('SELECT * FROM orders WHERE id=?', (params['orderNo'],)).fetchone()
        if not order or order['payment_mode'] != 'paypro' or not configured(order['channel']):
            raise ValueError('Unknown Paypro order')
        if not order['code_url'] or params['payNum'] != order['payment_receiver']:
            raise ValueError('Receipt remark mismatch')
        if fen(params['amount']) != order['amount_fen']:
            raise ValueError('Receipt amount mismatch')
        trade = {'order_id': order['id'], 'transaction_id': 'paypro:' + order['id'],
                 'success': True, 'amount': fen(params['amount']), 'currency': 'CNY'}
        payments.apply_trade(order['channel'], trade, 'paypro:' + order['id'],
                             hashlib.sha256(signature(params).encode()).hexdigest(), payment_mode='paypro')
    except HTTPException:
        raise
    except Exception:
        payments.record_rejection('paypro', raw)
        raise HTTPException(400, 'Paypro 通知签名或订单校验失败') from None
    return PlainTextResponse('success')
