"""SQLite accounts, hashed passwords, revocable sessions and personal activity."""
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
from typing import Literal
from pathlib import Path
from contextlib import contextmanager
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

DB = Path(os.getenv('ESSAY_DATA_DIR',str(Path(__file__).parent / 'data'))) / 'accounts.sqlite3'
COOKIE = 'essay_session'
router = APIRouter(prefix='/api')

@contextmanager
def database():
    DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB, timeout=15)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()

def initialize():
    with database() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('user','vip','admin')));
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER, expires REAL);
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, user_id INTEGER, filename TEXT, start TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, user_id INTEGER, action TEXT, detail TEXT, created REAL);
        CREATE INDEX IF NOT EXISTS personal_events ON events(user_id,id);
        CREATE TABLE IF NOT EXISTS attempts(key TEXT PRIMARY KEY, count INTEGER, reset REAL);
        ''')
        columns = {row['name'] for row in db.execute('PRAGMA table_info(users)').fetchall()}
        if 'role' not in columns:
            db.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('user','vip','admin'))")

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    return salt+':'+hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()

def audit(user_id, action, detail=''):
    with database() as db:
        db.execute('INSERT INTO events(user_id,action,detail,created) VALUES(?,?,?,?)', (user_id,action,detail,time.time()))

def current_user(request: Request):
    with database() as db:
        row = db.execute('SELECT users.id,username,role FROM users JOIN sessions ON users.id=sessions.user_id WHERE token=? AND expires>?',
                         (digest(request.cookies.get(COOKIE,'')), time.time())).fetchone()
    if not row:
        raise HTTPException(401,'请先登录')
    return dict(row)

def owned_job(job_id, user):
    if not re.fullmatch('[a-f0-9]{32}',job_id):
        raise HTTPException(404,'任务不存在')
    with database() as db:
        row = db.execute('SELECT * FROM jobs WHERE id=? AND user_id=?',(job_id,user['id'])).fetchone()
    if not row:
        raise HTTPException(404,'任务不存在')
    return dict(row)

def new_session(response, request, user):
    token = secrets.token_urlsafe(32)
    with database() as db:
        db.execute('DELETE FROM sessions WHERE expires<=? OR token=?',(time.time(),digest(request.cookies.get(COOKIE,''))))
        db.execute('INSERT INTO sessions VALUES(?,?,?)',(digest(token),user['id'],time.time()+604800))
    response.set_cookie(COOKIE,token,httponly=True,samesite='strict',secure=request.url.scheme=='https',max_age=604800,path='/')

class Credentials(BaseModel):
    username: str = Field(min_length=3,max_length=32)
    password: str = Field(min_length=8,max_length=128)

class RoleUpdate(BaseModel):
    role: Literal['user', 'vip', 'admin']

def administrator(user=Depends(current_user)):
    if user['role'] != 'admin':
        raise HTTPException(403, 'Administrator permission required')
    return user

@router.get('/admin/users')
def list_users(user=Depends(administrator)):
    with database() as db:
        return [dict(row) for row in db.execute('SELECT id,username,role FROM users ORDER BY id')]

@router.patch('/admin/users/{user_id}/role')
def update_role(user_id: int, data: RoleUpdate, user=Depends(administrator)):
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT id,username,role FROM users WHERE id=?', (user_id,)).fetchone()
        if not row:
            raise HTTPException(404, 'User not found')
        if row['role'] == 'admin' and data.role != 'admin':
            count = db.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0]
            if count <= 1:
                raise HTTPException(409, 'Cannot demote the last administrator')
        db.execute('UPDATE users SET role=? WHERE id=?', (data.role, user_id))
        db.execute('INSERT INTO events(user_id,action,detail,created) VALUES(?,?,?,?)',
                   (user['id'], 'role_changed', f'{row["username"]}: {data.role}', time.time()))
    return {'id': row['id'], 'username': row['username'], 'role': data.role}

def normalize(value):
    name=value.strip().lower()
    if not re.fullmatch('[a-z0-9_]{3,32}',name):
        raise HTTPException(400,'用户名需为 3–32 位英文字母、数字或下划线')
    return name

def throttle(request):
    key=request.client.host if request.client else 'unknown'
    now=time.time()
    with database() as db:
        row=db.execute('SELECT * FROM attempts WHERE key=?',(key,)).fetchone()
        if row and row['reset']>now and row['count']>=30:
            raise HTTPException(429,'操作过于频繁，请在 15 分钟后重试')
        count=row['count']+1 if row and row['reset']>now else 1
        reset=row['reset'] if row and row['reset']>now else now+900
        db.execute('INSERT OR REPLACE INTO attempts VALUES(?,?,?)',(key,count,reset))

@router.post('/auth/register',status_code=201)
def register(data: Credentials, request: Request, response: Response):
    throttle(request)
    name=normalize(data.username)
    hashed=password_hash(data.password)
    try:
        with database() as db:
            cursor=db.execute('INSERT INTO users(username,password) VALUES(?,?)',(name,hashed))
            user={'id':cursor.lastrowid,'username':name,'role':'user'}
    except sqlite3.IntegrityError:
        raise HTTPException(409,'该用户名已注册')
    audit(user['id'],'register','注册账号')
    new_session(response,request,user)
    return user

@router.post('/auth/login')
def login(data: Credentials, request: Request, response: Response):
    throttle(request)
    name=normalize(data.username)
    with database() as db:
        row=db.execute('SELECT * FROM users WHERE username=?',(name,)).fetchone()
    stored=row['password'] if row else password_hash('dummy-password','00'*16)
    valid=hmac.compare_digest(password_hash(data.password,stored.split(':')[0]),stored)
    if not row or not valid:
        raise HTTPException(401,'用户名或密码错误')
    user={'id':row['id'],'username':row['username'],'role':row['role']}
    new_session(response,request,user)
    audit(user['id'],'login','登录工作台')
    return user

@router.get('/auth/me')
def me(user=Depends(current_user)):
    return user

@router.post('/auth/logout')
def logout(request: Request,response: Response,user=Depends(current_user)):
    with database() as db:
        db.execute('DELETE FROM sessions WHERE token=?',(digest(request.cookies.get(COOKIE,'')),))
    response.delete_cookie(COOKIE,path='/')
    audit(user['id'],'logout','退出登录')
    return {'ok':True}

@router.get('/activity')
def activity(before: int=0,user=Depends(current_user)):
    with database() as db:
        rows=db.execute('SELECT id,action,detail,created FROM events WHERE user_id=? AND (?=0 OR id<?) ORDER BY id DESC LIMIT 51',
                        (user['id'],before,before)).fetchall()
    return {'items':[dict(r) for r in rows[:50]],'next':rows[49]['id'] if len(rows)>50 else None}
