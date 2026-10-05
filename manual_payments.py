"""Personal collection codes with explicit, audited administrator settlement."""
import io
import os
import time
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

import accounts
import saas

router = APIRouter(prefix='/api')
CHANNELS = ('wechat', 'alipay')


def asset_path(name):
    import re
    if not re.fullmatch(r'[a-f0-9]{32}\.png', name or ''):
        raise HTTPException(404, '图片不存在')
    return Path(os.getenv('ESSAY_DATA_DIR', str(accounts.DB.parent))) / 'payment-images' / name


async def save_image(file):
    raw = await file.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise HTTPException(413, '图片不能超过 2 MB')
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in ('PNG', 'JPEG', 'WEBP') or image.width * image.height > 8_000_000:
                raise ValueError('Invalid image')
            image.load()
            output = io.BytesIO()
            image.convert('RGB').save(output, format='PNG')
        if output.tell() > 2 * 1024 * 1024:
            raise HTTPException(413, '图片过大，请压缩后上传')
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(400, '请上传有效的 PNG、JPEG 或 WebP 图片') from None
    name = uuid.uuid4().hex + '.png'
    path = asset_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(output.getvalue())
    return name


def options():
    with accounts.database() as db:
        prices = {r['id']:r['price_fen'] for r in db.execute("SELECT id,price_fen FROM plans WHERE id IN ('pro','teacher')")}
        rows = {r['channel']: dict(r) for r in db.execute('SELECT * FROM manual_payment_settings')}
    channels = {c: bool(c in rows and rows[c]['receiver'].strip() and rows[c]['qr_file'] and asset_path(rows[c]['qr_file']).is_file()) for c in CHANNELS}
    return {'payment_mode': 'manual', 'price_fen': prices['pro'], 'prices':prices, 'channels': channels}


def create(data, key, user):
    from payments import public_order
    now = time.time()
    with accounts.database() as db:
        prior = db.execute('SELECT * FROM orders WHERE user_id=? AND request_key=?', (user['id'], key)).fetchone()
        if prior:
            if prior['channel'] != data.channel or prior['plan'] != data.plan:
                raise HTTPException(409, '同一提交键不能用于不同订单')
            return public_order(prior)
        plan = db.execute('SELECT * FROM plans WHERE id=?', (data.plan,)).fetchone()
        price = plan['price_fen'] if plan else None
        setting = db.execute('SELECT * FROM manual_payment_settings WHERE channel=?', (data.channel,)).fetchone()
        if not plan or not plan['enabled'] or not price or price <= 0:
            raise HTTPException(503, '该套餐暂未开放购买')
        if not setting or not setting['receiver'].strip() or not setting['qr_file'] or not asset_path(setting['qr_file']).is_file():
            raise HTTPException(503, '该渠道收款码尚未配置')
        waiting = db.execute("SELECT COUNT(*) AS n FROM orders WHERE user_id=? AND payment_mode='manual' AND (status='review_pending' OR (status IN ('pending','rejected') AND expires>?))", (user['id'],now)).fetchone()['n']
        if waiting >= 3:
            raise HTTPException(429, '已有待处理订单，请先到订单记录查看或提交凭证')
        ident = uuid.uuid4().hex
        db.execute('INSERT INTO orders(id,user_id,plan,quota,amount_fen,currency,channel,status,request_key,created,expires,payment_mode,payment_receiver,code_url) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (ident,user['id'],plan['id'],plan['quota'],price,'CNY',data.channel,'pending',key,now,now+1800,'manual',setting['receiver'],setting['qr_file']))
        return public_order(db.execute('SELECT * FROM orders WHERE id=?', (ident,)).fetchone())


def qr_response(order):
    if order['status'] not in ('pending', 'rejected') or order['expires'] < time.time():
        raise HTTPException(409, '订单已超时或已提交审核，请勿再次付款')
    path = asset_path(order['code_url'])
    if not path.is_file():
        raise HTTPException(404, '收款码不存在，请联系管理员')
    return FileResponse(path, media_type='image/png', headers={'Cache-Control': 'private, no-store'})


class SettingsInput(BaseModel):
    price_fen: int | None = Field(default=None, ge=1, le=1_000_000)
    teacher_price_fen: int | None = Field(default=None, ge=1, le=1_000_000)
    teacher_enabled: bool | None = None
    wechat_receiver: str = Field(default='', max_length=80)
    alipay_receiver: str = Field(default='', max_length=80)


@router.get('/admin/payments/manual')
def settings(user=Depends(accounts.administrator)):
    with accounts.database() as db:
        rows = {r['channel']: dict(r) for r in db.execute('SELECT * FROM manual_payment_settings')}
        teacher = db.execute("SELECT enabled FROM plans WHERE id='teacher'").fetchone()['enabled']
    return {**options(), 'active': os.getenv('PAYMENTS_MODE', 'merchant') == 'manual',
            'teacher_enabled':bool(teacher),
            'qr_uploaded': {c: bool(rows.get(c, {}).get('qr_file') and asset_path(rows[c]['qr_file']).is_file()) for c in CHANNELS},
            'receivers': {c: rows.get(c, {}).get('receiver', '') for c in CHANNELS}}


@router.put('/admin/payments/manual')
def update_settings(data: SettingsInput, user=Depends(accounts.administrator)):
    with accounts.database() as db:
        if 'price_fen' in data.model_fields_set:
            db.execute("UPDATE plans SET price_fen=? WHERE id='pro'", (data.price_fen,))
        if 'teacher_price_fen' in data.model_fields_set:
            db.execute("UPDATE plans SET price_fen=? WHERE id='teacher'", (data.teacher_price_fen,))
        if data.teacher_enabled is not None:
            db.execute("UPDATE plans SET enabled=? WHERE id='teacher'", (int(data.teacher_enabled),))
        for c in CHANNELS:
            db.execute('INSERT INTO manual_payment_settings(channel,receiver,updated) VALUES(?,?,?) ON CONFLICT(channel) DO UPDATE SET receiver=excluded.receiver,updated=excluded.updated', (c,getattr(data,c+'_receiver').strip(),time.time()))
        saas.audit(db,user['id'],'manual_payment_settings','plans','更新套餐售价、购买状态及收款人；留空售价关闭对应套餐新购买')
    return settings(user)


@router.post('/admin/payments/manual/{channel}/qr')
async def upload_qr(channel: Literal['wechat', 'alipay'], request: Request, file: UploadFile = File(...), user=Depends(accounts.administrator)):
    saas.rate_limit(request,user['id'],'upload_collection_code',10)
    name = await save_image(file)
    try:
        with accounts.database() as db:
            db.execute("INSERT INTO manual_payment_settings(channel,qr_file,updated) VALUES(?,?,?) ON CONFLICT(channel) DO UPDATE SET qr_file=excluded.qr_file,updated=excluded.updated", (channel,name,time.time()))
            saas.audit(db,user['id'],'manual_collection_code',channel,'更新个人收款码，旧订单仍保留原收款码')
    except Exception:
        asset_path(name).unlink(missing_ok=True)
        raise
    return {'ok': True}


@router.get('/admin/payments/manual/{channel}/qr')
def collection_qr(channel: Literal['wechat', 'alipay'], user=Depends(accounts.administrator)):
    with accounts.database() as db:
        row = db.execute('SELECT qr_file FROM manual_payment_settings WHERE channel=?', (channel,)).fetchone()
    if not row or not row['qr_file'] or not asset_path(row['qr_file']).is_file():
        raise HTTPException(404, '尚未上传收款码')
    return FileResponse(asset_path(row['qr_file']), media_type='image/png', headers={'Cache-Control':'private, no-store'})


@router.post('/orders/{ident}/proof')
async def submit_proof(ident: str, request: Request, payer: str = Form(..., min_length=1, max_length=80), reference: str = Form(..., min_length=6, max_length=128), file: UploadFile = File(...), user=Depends(accounts.current_user)):
    from payments import owned_order, public_order
    saas.rate_limit(request,user['id'],'payment_proof',10)
    order = owned_order(ident,user)
    if order['payment_mode'] != 'manual' or order['status'] not in ('pending','rejected'):
        raise HTTPException(409, '该订单不可提交付款凭证')
    # A transfer already made can be reported after checkout expiry; an administrator
    # must check the actual receipt. Expiry never silently discards transferred funds.
    if not payer.strip() or len(reference.strip()) < 6:
        raise HTTPException(400, '请填写付款人和交易单号')
    name = await save_image(file)
    try:
        with accounts.database() as db:
            current = db.execute('SELECT status FROM orders WHERE id=?', (ident,)).fetchone()
            if current['status'] not in ('pending','rejected'):
                raise HTTPException(409, '订单状态已更新，请刷新')
            db.execute('INSERT INTO manual_payment_proofs(order_id,payer,reference,image_file,submitted) VALUES(?,?,?,?,?) ON CONFLICT(order_id) DO UPDATE SET payer=excluded.payer,reference=excluded.reference,image_file=excluded.image_file,submitted=excluded.submitted,reviewed=NULL,reviewer_id=NULL,review_note=NULL', (ident,payer.strip(),reference.strip(),name,time.time()))
            db.execute("UPDATE orders SET status='review_pending',error=NULL WHERE id=?", (ident,))
            saas.audit(db,user['id'],'manual_proof_submitted',ident,'用户提交付款凭证，未确认到账')
            return public_order(db.execute('SELECT * FROM orders WHERE id=?',(ident,)).fetchone())
    except Exception:
        asset_path(name).unlink(missing_ok=True)
        raise


def accessible_proof(ident, user):
    with accounts.database() as db:
        row = db.execute('SELECT p.*,o.user_id FROM manual_payment_proofs p JOIN orders o ON o.id=p.order_id WHERE p.order_id=?', (ident,)).fetchone()
    if not row or (row['user_id'] != user['id'] and user['role'] != 'admin'):
        raise HTTPException(404, '付款凭证不存在')
    return row


@router.get('/orders/{ident}/proof')
def proof_detail(ident: str, user=Depends(accounts.current_user)):
    row = dict(accessible_proof(ident,user))
    row.pop('image_file')
    row['image_url'] = '/api/orders/'+ident+'/proof/image'
    return row


@router.get('/orders/{ident}/proof/image')
def proof_image(ident: str, user=Depends(accounts.current_user)):
    row = accessible_proof(ident,user)
    path = asset_path(row['image_file'])
    if not path.is_file():
        raise HTTPException(404, '付款凭证不存在')
    return FileResponse(path,media_type='image/png',headers={'Cache-Control':'private, no-store'})


class ReviewInput(BaseModel):
    decision: Literal['approve', 'reject']
    reason: str = Field(min_length=5,max_length=500)
    transaction_id: str = Field(default='',max_length=128)
    amount_fen: int | None = Field(default=None,ge=1)
    confirmed_received: bool = False


@router.post('/admin/orders/{ident}/review')
def review(ident: str, data: ReviewInput, user=Depends(accounts.administrator)):
    from payments import public_order
    with accounts.database() as db:
        order = db.execute('SELECT * FROM orders WHERE id=?',(ident,)).fetchone()
        if not order or order['payment_mode'] != 'manual':
            raise HTTPException(404,'人工收款订单不存在')
        if order['status'] == 'paid' and data.decision == 'approve' and order['transaction_id'] == data.transaction_id.strip() and data.confirmed_received and data.amount_fen == order['amount_fen']:
            return public_order(order)
        if order['status'] != 'review_pending':
            raise HTTPException(409,'仅可审核待确认的付款凭证')
        proof = db.execute('SELECT order_id FROM manual_payment_proofs WHERE order_id=?',(ident,)).fetchone()
        if not proof:
            raise HTTPException(409,'用户尚未提交付款凭证')
        if data.decision == 'approve':
            transaction = data.transaction_id.strip()
            if not data.confirmed_received or len(transaction) < 6 or data.amount_fen != order['amount_fen']:
                raise HTTPException(400,'请核实实际到账，填写实际交易号及与订单一致的金额')
            if db.execute('SELECT id FROM orders WHERE channel=? AND transaction_id=? AND id<>?',(order['channel'],transaction,ident)).fetchone():
                raise HTTPException(409,'该交易号已用于其他订单')
            start = max(time.time(),db.execute("SELECT MAX(expire_at) AS end FROM subscriptions WHERE user_id=? AND status='active'",(order['user_id'],)).fetchone()['end'] or 0)
            db.execute('INSERT INTO subscriptions VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(source_order_id) DO NOTHING',(uuid.uuid4().hex,order['user_id'],order['plan'],'active',start,saas.add_month(start),order['quota'],ident,time.time()))
            db.execute("UPDATE orders SET status='paid',paid_at=?,transaction_id=?,error=NULL WHERE id=?",(time.time(),transaction,ident))
        else:
            db.execute("UPDATE orders SET status='rejected',error=? WHERE id=?",(data.reason,ident))
        db.execute('UPDATE manual_payment_proofs SET reviewed=?,reviewer_id=?,review_note=? WHERE order_id=?',(time.time(),user['id'],data.reason,ident))
        saas.audit(db,user['id'],'manual_payment_'+data.decision,ident,data.reason)
        return public_order(db.execute('SELECT * FROM orders WHERE id=?',(ident,)).fetchone())


class ManualRefundInput(BaseModel):
    reason: str = Field(min_length=5,max_length=200)
    transaction_id: str = Field(min_length=6,max_length=128)
    amount_fen: int = Field(ge=1)
    confirmed_refunded: Literal[True]


@router.post('/admin/orders/{ident}/manual-refund')
def manual_refund(ident: str, data: ManualRefundInput, user=Depends(accounts.administrator)):
    with accounts.database() as db:
        order = db.execute('SELECT * FROM orders WHERE id=?',(ident,)).fetchone()
        if not order or order['payment_mode'] != 'manual' or data.amount_fen != order['amount_fen']:
            raise HTTPException(409,'人工收款订单或退款金额不匹配')
        refund = db.execute('SELECT * FROM refunds WHERE order_id=?',(ident,)).fetchone()
        if refund and order['status'] == 'refunded' and refund['provider_id'] == data.transaction_id:
            return dict(refund)
        if order['status'] != 'paid' or refund:
            raise HTTPException(409,'该订单不可登记退款')
        if db.execute('SELECT r.id FROM refunds r JOIN orders o ON o.id=r.order_id WHERE o.channel=? AND r.provider_id=?', (order['channel'],data.transaction_id)).fetchone():
            raise HTTPException(409,'该退款交易号已用于其他订单')
        db.execute('INSERT INTO refunds VALUES(?,?,?,?,?,?,?,?,?)',(uuid.uuid4().hex,ident,data.amount_fen,'succeeded',data.transaction_id,data.reason,time.time(),time.time(),None))
        db.execute("UPDATE orders SET status='refunded' WHERE id=?",(ident,))
        db.execute("UPDATE subscriptions SET status='revoked' WHERE source_order_id=?",(ident,))
        saas.audit(db,user['id'],'manual_refund_confirmed',ident,data.reason+'；实际退款交易号：'+data.transaction_id)
        return dict(db.execute('SELECT * FROM refunds WHERE order_id=?',(ident,)).fetchone())
