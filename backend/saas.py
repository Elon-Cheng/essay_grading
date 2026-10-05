"""Subscription, quota ledger, persistent jobs, usage and operational APIs."""
import calendar
import hashlib
import json
import logging
import os
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from backend import accounts

router = APIRouter(prefix='/api')
TZ = ZoneInfo('Asia/Shanghai')
logger = logging.getLogger(__name__)
JOB_COLUMNS = {
    'status': "TEXT NOT NULL DEFAULT 'queued'", 'stage': "TEXT NOT NULL DEFAULT 'queued'",
    'error': 'TEXT', 'updated': 'REAL', 'request_key': 'TEXT', 'content_hash': 'TEXT',
    'quota_period_id': 'TEXT', 'quota_state': "TEXT NOT NULL DEFAULT 'legacy'",
    'attempts': 'INTEGER NOT NULL DEFAULT 0', 'lease_owner': 'TEXT', 'lease_until': 'REAL',
    'is_demo': 'INTEGER NOT NULL DEFAULT 0', 'ai_uncertain': 'INTEGER NOT NULL DEFAULT 0',
}


def migrate(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS plans(id TEXT PRIMARY KEY, name TEXT NOT NULL, quota INTEGER NOT NULL, price_fen INTEGER, enabled INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS subscriptions(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,plan TEXT NOT NULL,status TEXT NOT NULL,start_at REAL NOT NULL,expire_at REAL NOT NULL,quota INTEGER NOT NULL,source_order_id TEXT UNIQUE,created REAL NOT NULL);
    CREATE INDEX IF NOT EXISTS subscription_user ON subscriptions(user_id,start_at,expire_at);
    CREATE TABLE IF NOT EXISTS quota_periods(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,plan TEXT NOT NULL,start_at REAL NOT NULL,end_at REAL NOT NULL,quota INTEGER NOT NULL,used INTEGER NOT NULL DEFAULT 0,reserved INTEGER NOT NULL DEFAULT 0,CHECK(used>=0 AND reserved>=0));
    CREATE TABLE IF NOT EXISTS quota_ledger(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,job_id TEXT,period_id TEXT NOT NULL,action TEXT NOT NULL,amount INTEGER NOT NULL,created REAL NOT NULL,UNIQUE(job_id,action));
    CREATE TABLE IF NOT EXISTS ai_calls(id TEXT PRIMARY KEY,job_id TEXT,user_id INTEGER,provider TEXT NOT NULL,model TEXT NOT NULL,returned_model TEXT,request_id TEXT,input_tokens INTEGER,cached_tokens INTEGER,output_tokens INTEGER,estimated_cost REAL,currency TEXT NOT NULL,price_snapshot TEXT NOT NULL,started REAL NOT NULL,latency_ms INTEGER,status TEXT NOT NULL,error_code TEXT,budget_reserved REAL NOT NULL DEFAULT 0);
    CREATE INDEX IF NOT EXISTS ai_calls_started ON ai_calls(started);
    CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,plan TEXT NOT NULL,quota INTEGER NOT NULL,amount_fen INTEGER NOT NULL,currency TEXT NOT NULL,channel TEXT NOT NULL,status TEXT NOT NULL,request_key TEXT NOT NULL,transaction_id TEXT,code_url TEXT,created REAL NOT NULL,expires REAL NOT NULL,paid_at REAL,last_checked REAL,error TEXT,UNIQUE(user_id,request_key),UNIQUE(channel,transaction_id));
    CREATE TABLE IF NOT EXISTS payment_events(id TEXT PRIMARY KEY,channel TEXT NOT NULL,event_key TEXT NOT NULL,order_id TEXT,payload_hash TEXT NOT NULL,status TEXT NOT NULL,created REAL NOT NULL,error TEXT,UNIQUE(channel,event_key));
    CREATE TABLE IF NOT EXISTS refunds(id TEXT PRIMARY KEY,order_id TEXT NOT NULL UNIQUE,amount_fen INTEGER NOT NULL,status TEXT NOT NULL,provider_id TEXT,reason TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL,error TEXT);
    CREATE TABLE IF NOT EXISTS audit_logs(id TEXT PRIMARY KEY,actor_id INTEGER,action TEXT NOT NULL,target TEXT,reason TEXT NOT NULL,created REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS rate_limits(key TEXT PRIMARY KEY,count INTEGER NOT NULL,reset REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS product_events(id TEXT PRIMARY KEY,user_id INTEGER,visitor_id TEXT,kind TEXT NOT NULL,created REAL NOT NULL);
    CREATE INDEX IF NOT EXISTS product_events_created ON product_events(created);
    CREATE TABLE IF NOT EXISTS manual_payment_settings(channel TEXT PRIMARY KEY,receiver TEXT NOT NULL DEFAULT '',qr_file TEXT,updated REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS manual_payment_proofs(order_id TEXT PRIMARY KEY,payer TEXT NOT NULL,reference TEXT NOT NULL,image_file TEXT NOT NULL,submitted REAL NOT NULL,reviewed REAL,reviewer_id INTEGER,review_note TEXT);
    ''')
    if 'payment_mode' not in db.columns('orders'):
        db.execute("ALTER TABLE orders ADD COLUMN payment_mode TEXT NOT NULL DEFAULT 'merchant'")
    if 'payment_receiver' not in db.columns('orders'):
        db.execute("ALTER TABLE orders ADD COLUMN payment_receiver TEXT NOT NULL DEFAULT ''")
    columns = db.columns('users')
    if 'essay_credits' not in columns:
        db.execute('ALTER TABLE users ADD COLUMN essay_credits INTEGER NOT NULL DEFAULT 0 CHECK(essay_credits>=0)')
    from backend.credit_payments import migrate as migrate_credits
    migrate_credits(db)
    if 'created' not in columns:
        db.execute('ALTER TABLE users ADD COLUMN created REAL')
        db.execute("UPDATE users SET created=(SELECT MIN(created) FROM events WHERE events.user_id=users.id AND action='register')")
    if 'disabled' not in columns:
        db.execute('ALTER TABLE users ADD COLUMN disabled INTEGER NOT NULL DEFAULT 0')
    columns = db.columns('jobs')
    for name, definition in JOB_COLUMNS.items():
        if name not in columns:
            db.execute(f'ALTER TABLE jobs ADD COLUMN {name} {definition}')
    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS job_request_key ON jobs(user_id,request_key)')
    db.execute('CREATE INDEX IF NOT EXISTS job_queue ON jobs(status,created)')
    for ident, name, quota, enabled in [('free', '免费版', 3, 1), ('pro', 'Pro', 100, 1), ('teacher', '教师版', 100, 0)]:
        db.execute('INSERT INTO plans(id,name,quota,enabled) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET quota=excluded.quota', (ident, name, quota, enabled))
    if not db.execute('SELECT version FROM schema_migrations WHERE version=1').fetchone():
        root = Path(os.getenv('ESSAY_DATA_DIR', str(accounts.DB.parent)))
        for job in db.execute('SELECT * FROM jobs'):
            file = root / job['id'] / 'meta.json'
            if file.exists():
                try:
                    data = json.loads(file.read_text(encoding='utf-8'))
                    status = data.get('status', 'failed')
                    # Old in-process work is interrupted, not silently rerun and billed.
                    if status in ('queued', 'running'):
                        status = 'failed'
                    db.execute('UPDATE jobs SET status=?,stage=?,error=?,updated=? WHERE id=?',
                               (status, 'done' if status == 'succeeded' else 'error', data.get('error'), time.time(), job['id']))
                except (OSError, ValueError):
                    db.execute("UPDATE jobs SET status='failed',stage='error',error='历史任务信息损坏' WHERE id=?", (job['id'],))
        current = datetime.now(TZ).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        for job in db.execute("SELECT * FROM jobs WHERE status='succeeded' AND quota_state='legacy' AND created>=?", (current.timestamp(),)):
            period_id = f'free-{job["user_id"]}-{current:%Y%m}'
            db.execute('INSERT INTO quota_periods(id,user_id,plan,start_at,end_at,quota) VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING', (period_id,job['user_id'],'free',current.timestamp(),add_month(current.timestamp()),3))
            db.execute('UPDATE quota_periods SET used=used+1 WHERE id=?', (period_id,))
            db.execute("UPDATE jobs SET quota_period_id=?,quota_state='committed' WHERE id=?", (period_id,job['id']))
            db.execute('INSERT INTO quota_ledger VALUES(?,?,?,?,?,?,?)', (uuid.uuid4().hex,job['user_id'],job['id'],period_id,'legacy_commit',1,job['created']))
        db.execute('INSERT INTO schema_migrations(version,applied) VALUES(1,?)', (time.time(),))


def add_month(stamp):
    value = datetime.fromtimestamp(stamp, TZ)
    year, month = (value.year + 1, 1) if value.month == 12 else (value.year, value.month + 1)
    return value.replace(year=year, month=month, day=min(value.day, calendar.monthrange(year, month)[1])).timestamp()


def audit(db, actor, action, target, reason):
    db.execute('INSERT INTO audit_logs VALUES(?,?,?,?,?,?)', (uuid.uuid4().hex, actor, action, str(target), reason, time.time()))


def entitlement(db, user_id, now=None):
    now = time.time() if now is None else now
    db.execute("UPDATE subscriptions SET status='expired' WHERE status='active' AND expire_at<=?", (now,))
    sub = db.execute("SELECT * FROM subscriptions WHERE user_id=? AND status='active' AND start_at<=? AND expire_at>? ORDER BY start_at DESC LIMIT 1", (user_id, now, now)).fetchone()
    if sub:
        plan, quota, start, end, ident = sub['plan'], sub['quota'], sub['start_at'], sub['expire_at'], sub['id']
    else:
        current = datetime.fromtimestamp(now, TZ).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        start, end = current.timestamp(), add_month(current.timestamp())
        plan, quota, ident = 'free', 3, f'free-{user_id}-{current:%Y%m}'
    db.execute('INSERT INTO quota_periods(id,user_id,plan,start_at,end_at,quota) VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING', (ident, user_id, plan, start, end, quota))
    period = db.execute('SELECT * FROM quota_periods WHERE id=?', (ident,)).fetchone()
    renewal = db.execute("SELECT MAX(expire_at) AS expires FROM subscriptions WHERE user_id=? AND status='active' AND expire_at>?", (user_id, now)).fetchone()['expires']
    unlimited = db.execute('SELECT role FROM users WHERE id=?', (user_id,)).fetchone()['role'] == 'admin'
    wallet = db.execute('SELECT essay_credits FROM users WHERE id=?', (user_id,)).fetchone()['essay_credits']
    credit_period = db.execute('SELECT reserved FROM quota_periods WHERE id=?', (f'credits-{user_id}',)).fetchone()
    credit_reserved = credit_period['reserved'] if credit_period else 0
    period_remaining = max(0, period['quota'] - period['used'] - period['reserved'])
    return {'unlimited': unlimited, 'plan': plan, 'status': 'active', 'start_at': start, 'expire_at': renewal if sub else None,
            'period_end': end, 'quota': period['quota'], 'used_quota': period['used'], 'reserved_quota': period['reserved'],
            'essay_credits': wallet, 'reserved_credits': credit_reserved, 'available_credits': max(0,wallet-credit_reserved),
            'period_remaining_quota': period_remaining,
            'remaining_quota': None if unlimited else period_remaining + max(0,wallet-credit_reserved), 'period_id': ident}


def reserve(db, user_id, job_id, attempt=1):
    state = entitlement(db, user_id)
    use_credits = not state['unlimited'] and state['period_remaining_quota'] <= 0
    if not state['unlimited'] and state['remaining_quota'] <= 0:
        raise HTTPException(429, '本周期批改额度已用完，请升级套餐或等待额度重置')
    # The previous one-per-day free rule remains, configurable independently from monthly quota.
    daily = int(os.getenv('FREE_DAILY_QUOTA', '1'))
    if not state['unlimited'] and state['plan'] == 'free' and daily:
        midnight = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        count = db.execute("SELECT COUNT(*) AS n FROM jobs j JOIN quota_periods q ON j.quota_period_id=q.id WHERE j.user_id=? AND j.created>=? AND q.plan='free' AND j.quota_state IN ('reserved','committed')", (user_id, midnight)).fetchone()['n']
        if count >= daily:
            if state['available_credits'] <= 0:
                raise HTTPException(429, '今日免费额度已用完，请购买批改次数或明天再试')
            use_credits = True
    pending = db.execute("SELECT COUNT(*) AS n FROM jobs WHERE user_id=? AND status IN ('queued','running')", (user_id,)).fetchone()['n']
    if pending >= int(os.getenv('USER_MAX_PENDING', '2')):
        raise HTTPException(429, '已有作文正在处理，请等待完成后再提交')
    if use_credits:
        state['period_id'] = f'credits-{user_id}'
    db.execute('UPDATE quota_periods SET reserved=reserved+1 WHERE id=?', (state['period_id'],))
    db.execute('INSERT INTO quota_ledger VALUES(?,?,?,?,?,?,?)', (uuid.uuid4().hex, user_id, job_id, state['period_id'], f'reserve:{attempt}', 1, time.time()))
    return state['period_id']


def settle(db, job_id, success):
    job = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
    if not job or job['quota_state'] != 'reserved':
        return
    db.execute('UPDATE quota_periods SET reserved=reserved-1,used=used+? WHERE id=?', (int(success), job['quota_period_id']))
    if success and job['quota_period_id'] == f'credits-{job["user_id"]}':
        db.execute('UPDATE users SET essay_credits=essay_credits-1 WHERE id=?', (job['user_id'],))
    db.execute('UPDATE jobs SET quota_state=? WHERE id=?', ('committed' if success else 'released', job_id))
    db.execute('INSERT INTO quota_ledger VALUES(?,?,?,?,?,?,?)', (uuid.uuid4().hex, job['user_id'], job_id, job['quota_period_id'], ('commit:' if success else 'release:') + str(job['attempts'] or 1), 1, time.time()))


def rate_limit(request, user_id, category, limit=20, window=60):
    ip = request.client.host if request.client else 'unknown'
    now = time.time()
    with accounts.database() as db:
        for key, maximum in [(f'{category}:user:{user_id}', limit), (f'{category}:ip:{ip}', limit * 5)]:
            row = db.execute('SELECT * FROM rate_limits WHERE key=?', (key,)).fetchone()
            if row and row['reset'] > now and row['count'] >= maximum:
                raise HTTPException(429, '操作过于频繁，请稍后再试', headers={'Retry-After': str(max(1, int(row['reset'] - now)))})
            count, reset = (row['count'] + 1, row['reset']) if row and row['reset'] > now else (1, now + window)
            db.execute('INSERT INTO rate_limits VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET count=excluded.count,reset=excluded.reset', (key, count, reset))


def public_job(row):
    result = {key: row[key] for key in ('id', 'filename', 'status', 'stage', 'error', 'created', 'updated', 'is_demo')}
    result['retryable'] = (row['status'] == 'failed' and not row['ai_uncertain']
                           and row['attempts'] < 3 and row['quota_state'] != 'committed')
    return result


def claim(job_id, owner):
    now = time.time()
    with accounts.database() as db:
        row = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if not row or row['status'] != 'queued':
            return False
        db.execute("UPDATE jobs SET status='running',attempts=attempts+1,lease_owner=?,lease_until=?,updated=? WHERE id=?", (owner, now + 180, now, job_id))
    return True


def heartbeat(job_id, owner):
    with accounts.database() as db:
        return db.execute("UPDATE jobs SET lease_until=? WHERE id=? AND lease_owner=? AND status='running'", (time.time() + 180, job_id, owner)).rowcount > 0


def recover():
    with accounts.database() as db:
        for job in db.execute("SELECT * FROM jobs WHERE status='running' AND lease_until<?", (time.time(),)):
            uncertain = db.execute("SELECT COUNT(*) AS n FROM ai_calls WHERE job_id=? AND status IN ('started','unknown')", (job['id'],)).fetchone()['n']
            db.execute("UPDATE ai_calls SET status='unknown',error_code='worker_interrupted',budget_reserved=0 WHERE job_id=? AND status='started'", (job['id'],))
            if uncertain:
                db.execute("UPDATE jobs SET status='failed',stage='error',error='调用结果待核查，请联系管理员',ai_uncertain=1,lease_owner=NULL,lease_until=NULL WHERE id=?", (job['id'],))
                settle(db, job['id'], False)
            else:
                db.execute("UPDATE jobs SET status='queued',lease_owner=NULL,lease_until=NULL WHERE id=?", (job['id'],))
        entitlement_users = db.execute("SELECT DISTINCT user_id FROM subscriptions WHERE status='active' AND expire_at<=?", (time.time(),)).fetchall()
        for row in entitlement_users:
            entitlement(db, row['user_id'])


def start_call(job_id, model, provider, input_token_bound=0, output_token_bound=0):
    ident, now = uuid.uuid4().hex, time.time()
    prices = {'input': os.getenv('AI_INPUT_PRICE_PER_MILLION') or None, 'cached': os.getenv('AI_CACHED_PRICE_PER_MILLION') or None, 'output': os.getenv('AI_OUTPUT_PRICE_PER_MILLION') or None, 'version': os.getenv('AI_PRICE_VERSION') or 'unconfigured'}
    with accounts.database() as db:
        job = db.execute('SELECT user_id FROM jobs WHERE id=?', (job_id,)).fetchone() if job_id else None
        budget = os.getenv('AI_DAILY_BUDGET')
        estimate = float(os.getenv('AI_CALL_BUDGET_RESERVATION', '1'))
        if budget:
            if not all(prices.get(k) is not None for k in ('input', 'cached', 'output')):
                raise RuntimeError('AI 成本单价未配置，预算控制无法启用')
            midnight = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            # Byte length is a conservative token bound for the configured text payload.
            upper = (input_token_bound * max(float(prices['input']), float(prices['cached'])) + output_token_bound * float(prices['output'])) / 1_000_000
            estimate = max(estimate, upper)
            rows = db.execute('SELECT estimated_cost,budget_reserved,status,currency FROM ai_calls WHERE started>=?', (midnight,)).fetchall()
            if any(r['currency'] != os.getenv('AI_PRICE_CURRENCY', 'CNY') for r in rows):
                raise RuntimeError('今日成本币种不一致，请核对预算配置')
            spent = sum((r['estimated_cost'] or 0) + r['budget_reserved'] for r in rows)
            if any(r['estimated_cost'] is None and r['status'] not in ('started', 'http_error') for r in rows):
                raise RuntimeError('存在未核实 AI 用量，已暂停新调用')
            if spent + estimate > float(budget):
                logger.warning('AI daily budget exhausted; refusing new call')
                raise RuntimeError('今日 AI 预算已达上限，请稍后再试')
        db.execute('INSERT INTO ai_calls(id,job_id,user_id,provider,model,currency,price_snapshot,started,status,budget_reserved) VALUES(?,?,?,?,?,?,?,?,?,?)',
                   (ident, job_id, job['user_id'] if job else None, provider, model, os.getenv('AI_PRICE_CURRENCY', 'CNY'), json.dumps(prices), now, 'started', estimate if budget else 0))
    return ident


def finish_call(ident, data=None, response=None, error=None):
    data = data or {}
    usage = data.get('usage') or {}
    if not isinstance(usage, dict):
        usage = {}
    input_tokens, output_tokens = usage.get('input_tokens'), usage.get('output_tokens')
    details = usage.get('input_tokens_details') or {}
    cached = details.get('cached_tokens', 0) if input_tokens is not None and isinstance(details, dict) else None
    if not all(isinstance(value,int) and not isinstance(value,bool) and value>=0 for value in (input_tokens,output_tokens,cached)) or cached>input_tokens:
        input_tokens, output_tokens, cached = None, None, None
    with accounts.database() as db:
        call = db.execute('SELECT * FROM ai_calls WHERE id=?', (ident,)).fetchone()
        prices = json.loads(call['price_snapshot'])
        cost = None
        if input_tokens is not None and output_tokens is not None and all(prices.get(k) is not None for k in ('input', 'cached', 'output')):
            cost = ((input_tokens - cached) * float(prices['input']) + cached * float(prices['cached']) + output_tokens * float(prices['output'])) / 1_000_000
        status = 'http_error' if response is not None and response.status_code >= 400 else 'unknown' if error or input_tokens is None or output_tokens is None else 'succeeded'
        db.execute('UPDATE ai_calls SET returned_model=?,request_id=?,input_tokens=?,cached_tokens=?,output_tokens=?,estimated_cost=?,latency_ms=?,status=?,error_code=?,budget_reserved=0 WHERE id=?',
                   (data.get('model'), response.headers.get('x-request-id') if response is not None else None, input_tokens, cached, output_tokens, cost, int((time.time() - call['started']) * 1000), status, error, ident))


@router.get('/subscription')
def subscription(user=Depends(accounts.current_user)):
    with accounts.database() as db:
        return entitlement(db, user['id'])


@router.get('/plans')
def plans():
    from backend.payments import checkout_options
    with accounts.database() as db:
        rows = [dict(r) for r in db.execute('SELECT * FROM plans')]
    checkout = checkout_options()
    for row in rows:
        row['price_fen'] = checkout['prices'].get(row['id'])
        row['purchasable'] = row['id'] in ('pro','teacher') and bool(row['enabled']) and row['price_fen'] is not None and any(checkout['channels'].values())
    return {'plans': rows, **checkout, 'free_daily_quota': int(os.getenv('FREE_DAILY_QUOTA', '1'))}


class Grant(BaseModel):
    plan: str = Field(pattern='^(pro|teacher)$')
    months: int = Field(default=1, ge=1, le=12)
    reason: str = Field(min_length=5, max_length=500)


@router.post('/admin/users/{user_id}/subscription')
def grant(user_id: int, data: Grant, user=Depends(accounts.administrator)):
    with accounts.database() as db:
        if not db.execute('SELECT id FROM users WHERE id=?', (user_id,)).fetchone():
            raise HTTPException(404, '用户不存在')
        start = max(time.time(), db.execute("SELECT MAX(expire_at) AS end FROM subscriptions WHERE user_id=? AND status='active'", (user_id,)).fetchone()['end'] or 0)
        for _ in range(data.months):
            end = add_month(start)
            db.execute('INSERT INTO subscriptions VALUES(?,?,?,?,?,?,?,?,?)', (uuid.uuid4().hex, user_id, data.plan, 'active', start, end, 100, None, time.time()))
            start = end
        audit(db, user['id'], 'grant_subscription', user_id, data.reason)
        return entitlement(db, user_id)


class AccountState(BaseModel):
    disabled: bool
    reason: str = Field(min_length=5, max_length=500)


@router.patch('/admin/users/{user_id}/state')
def account_state(user_id: int, data: AccountState, user=Depends(accounts.administrator)):
    with accounts.database() as db:
        target = db.execute('SELECT role FROM users WHERE id=?', (user_id,)).fetchone()
        if not target:
            raise HTTPException(404, '用户不存在')
        if target['role'] == 'admin':
            raise HTTPException(409, '请先调整管理员权限再禁用账号')
        db.execute('UPDATE users SET disabled=? WHERE id=?', (int(data.disabled), user_id))
        if data.disabled:
            db.execute('DELETE FROM sessions WHERE user_id=?', (user_id,))
        audit(db, user['id'], 'account_state', user_id, data.reason)
    return {'ok': True}


@router.get('/admin/overview')
def overview(user=Depends(accounts.administrator)):
    today = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    with accounts.database() as db:
        def scalar(sql, params=()):
            return db.execute(sql, params).fetchone()[0] or 0
        calls = [dict(r) for r in db.execute('SELECT * FROM ai_calls WHERE started>=?', (today,))]
        jobs = [dict(r) for r in db.execute('SELECT * FROM jobs WHERE created>=?', (today,))]
        currencies = {}
        for call in calls:
            currency = call['currency']
            currencies[currency] = currencies.get(currency, 0) + (call['estimated_cost'] or 0)
        real = [j for j in jobs if not j['is_demo']]
        finished = [j for j in real if j['status'] in ('succeeded', 'failed')]
        successes = len([j for j in finished if j['status'] == 'succeeded'])
        cohort_end = time.time() - 30 * 86400
        cohort = scalar('SELECT COUNT(*) FROM users WHERE created<=?', (cohort_end,))
        converted = scalar("SELECT COUNT(DISTINCT u.id) FROM users u JOIN orders o ON u.id=o.user_id WHERE u.created<=? AND o.paid_at>=u.created AND o.paid_at<=u.created+?", (cohort_end, 30 * 86400))
        funnel_start = time.time() - 30 * 86400
        visitors = scalar("SELECT COUNT(DISTINCT visitor_id) FROM product_events WHERE kind='visit' AND created>=?", (funnel_start,))
        registrations = scalar("SELECT COUNT(DISTINCT visitor_id) FROM product_events WHERE kind='registered' AND created>=? AND visitor_id IN (SELECT visitor_id FROM product_events WHERE kind='visit' AND created>=?)", (funnel_start, funnel_start))
        return {'users': scalar('SELECT COUNT(*) FROM users'), 'dau': scalar("SELECT COUNT(DISTINCT user_id) FROM product_events WHERE created>=? AND kind='active'", (today,)),
                'registrations_today': scalar("SELECT COUNT(*) FROM events WHERE action='register' AND created>=?", (today,)),
                'jobs_today': len(jobs), 'real_jobs_today': len(real), 'succeeded_today': successes,
                'failed_today': len(finished) - successes, 'task_error_rate': (len(finished) - successes) / len(finished) if finished else None,
                'api_calls_today': len(calls), 'api_error_rate': len([c for c in calls if c['error_code']]) / len(calls) if calls else None,
                'input_tokens': sum(c['input_tokens'] or 0 for c in calls), 'output_tokens': sum(c['output_tokens'] or 0 for c in calls),
                'unknown_usage_calls': len([c for c in calls if c['input_tokens'] is None]), 'unpriced_calls': len([c for c in calls if c['estimated_cost'] is None]),
                'estimated_cost_by_currency': currencies, 'average_delivery_cost_by_currency': {k: v / successes if successes else None for k, v in currencies.items()},
                'paid_fen': scalar("SELECT SUM(amount_fen) FROM orders WHERE paid_at>=?", (today,)),
                'refunded_fen': scalar("SELECT SUM(amount_fen) FROM refunds WHERE status='succeeded' AND updated>=?", (today,)),
                'paid_conversion_30d': converted / cohort if cohort else None, 'conversion_cohort_users': cohort,
                'registration_conversion': registrations / visitors if visitors else None, 'registration_conversion_note': '近30天有首页访问记录的访客到注册转化，非自然人去重',
                'pending_jobs': scalar("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')"),
                'rejected_payment_events': scalar("SELECT COUNT(*) FROM payment_events WHERE status='rejected' AND created>=?", (today,))}


@router.get('/admin/records/{kind}')
def admin_records(kind: str, user=Depends(accounts.administrator), limit: int = 100):
    tables = {'jobs': 'jobs', 'calls': 'ai_calls', 'orders': 'orders', 'audit': 'audit_logs', 'refunds': 'refunds', 'payments': 'payment_events'}
    if kind not in tables:
        raise HTTPException(404, '记录类型不存在')
    with accounts.database() as db:
        time_column = 'started' if kind == 'calls' else 'created'
        rows = [dict(r) for r in db.execute(f'SELECT * FROM {tables[kind]} ORDER BY {time_column} DESC LIMIT ?', (max(1, min(limit, 200)),))]
        if kind == 'jobs':
            for row in rows:
                calls = db.execute('SELECT currency,estimated_cost,input_tokens FROM ai_calls WHERE job_id=?', (row['id'],)).fetchall()
                row['ai_costs'] = {}
                row['unknown_cost_calls'] = sum(c['estimated_cost'] is None for c in calls)
                for call in calls:
                    row['ai_costs'][call['currency']] = row['ai_costs'].get(call['currency'], 0) + (call['estimated_cost'] or 0)
    for row in rows:
        for field in ('content_hash', 'request_key', 'lease_owner'):
            row.pop(field, None)
    return rows


@router.get('/admin/accounts')
def admin_accounts(user=Depends(accounts.administrator)):
    with accounts.database() as db:
        return [{**dict(r), **entitlement(db, r['id'])} for r in db.execute('SELECT id,username,role,disabled,created FROM users ORDER BY id DESC LIMIT 200')]


@router.post('/activity/active')
def active(request: Request, user=Depends(accounts.current_user)):
    rate_limit(request, user['id'], 'active', 10)
    with accounts.database() as db:
        recent = db.execute("SELECT id FROM product_events WHERE user_id=? AND kind='active' AND created>? LIMIT 1", (user['id'], time.time() - 300)).fetchone()
        if not recent:
            db.execute('INSERT INTO product_events VALUES(?,?,?,?,?)', (uuid.uuid4().hex, user['id'], None, 'active', time.time()))
    return {'ok': True}


@router.post('/product/visit')
def visit(request: Request, response: Response):
    import secrets
    saas_id = request.cookies.get('essay_visitor') or secrets.token_urlsafe(24)
    ident = accounts.digest(saas_id)
    rate_limit(request, ident, 'visit', 30)
    with accounts.database() as db:
        if not db.execute("SELECT id FROM product_events WHERE visitor_id=? AND kind='visit' AND created>? LIMIT 1", (ident, time.time() - 86400)).fetchone():
            db.execute('INSERT INTO product_events VALUES(?,?,?,?,?)', (uuid.uuid4().hex, None, ident, 'visit', time.time()))
    response.set_cookie('essay_visitor', saas_id, httponly=True, secure=request.url.scheme == 'https', samesite='lax', max_age=30 * 86400)
    return {'ok': True}


class QuotaAdjustment(BaseModel):
    delta: int = Field(ge=-1000, le=1000)
    reason: str = Field(min_length=5, max_length=500)


@router.post('/admin/users/{user_id}/quota')
def adjust_quota(user_id: int, data: QuotaAdjustment, user=Depends(accounts.administrator)):
    with accounts.database() as db:
        if not db.execute('SELECT id FROM users WHERE id=?', (user_id,)).fetchone():
            raise HTTPException(404, '用户不存在')
        state = entitlement(db, user_id)
        if state['quota'] + data.delta < state['used_quota'] + state['reserved_quota']:
            raise HTTPException(409, '调整后总额度不能小于已使用和已占用次数')
        db.execute('UPDATE quota_periods SET quota=quota+? WHERE id=?', (data.delta, state['period_id']))
        db.execute('INSERT INTO quota_ledger VALUES(?,?,?,?,?,?,?)', (uuid.uuid4().hex, user_id, None, state['period_id'], 'adjust', data.delta, time.time()))
        audit(db, user['id'], 'adjust_quota', user_id, f'{data.delta:+d}: {data.reason}')
        return entitlement(db, user_id)


class UsageResolution(BaseModel):
    input_tokens: int = Field(ge=0, le=10_000_000)
    cached_tokens: int = Field(default=0, ge=0, le=10_000_000)
    output_tokens: int = Field(ge=0, le=10_000_000)
    verified_cost: float | None = Field(default=None, ge=0, le=10000, allow_inf_nan=False)
    reason: str = Field(min_length=5, max_length=500)


@router.post('/admin/calls/{ident}/resolve')
def resolve_usage(ident: str, data: UsageResolution, user=Depends(accounts.administrator)):
    if data.cached_tokens > data.input_tokens:
        raise HTTPException(400, '缓存输入不能超过总输入')
    with accounts.database() as db:
        call = db.execute('SELECT * FROM ai_calls WHERE id=?', (ident,)).fetchone()
        if not call or call['status'] == 'started':
            raise HTTPException(409, '仅可核查已结束的调用')
        prices = json.loads(call['price_snapshot'])
        cost = data.verified_cost
        if cost is None and all(prices.get(k) is not None for k in ('input','cached','output')):
            cost = ((data.input_tokens-data.cached_tokens)*float(prices['input'])+data.cached_tokens*float(prices['cached'])+data.output_tokens*float(prices['output']))/1_000_000
        db.execute("UPDATE ai_calls SET input_tokens=?,cached_tokens=?,output_tokens=?,estimated_cost=?,status='reconciled',budget_reserved=0 WHERE id=?", (data.input_tokens,data.cached_tokens,data.output_tokens,cost,ident))
        if call['job_id'] and not db.execute("SELECT id FROM ai_calls WHERE job_id=? AND status IN ('unknown','started') LIMIT 1", (call['job_id'],)).fetchone():
            db.execute('UPDATE jobs SET ai_uncertain=0 WHERE id=?', (call['job_id'],))
        audit(db, user['id'], 'resolve_ai_usage', ident, json.dumps(data.model_dump(),ensure_ascii=False))
    return {'ok': True}
