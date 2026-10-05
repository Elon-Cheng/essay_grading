import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
import accounts
import app

class AccountTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.patches=[patch.object(accounts,'DB',self.root/'accounts.sqlite3'),patch.object(app,'DATA',self.root)]
        for p in self.patches:p.start()
        accounts.initialize()
        self.a=TestClient(app.app);self.b=TestClient(app.app)
        self.credentials={'username':'teacher_a','password':'test-password-123'}

    def tearDown(self):
        self.a.close();self.b.close()
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()

    def test_sessions(self):
        self.assertEqual(self.a.get('/api/essays').status_code,401)
        self.assertEqual(self.a.get('/').status_code,200)
        self.assertEqual(self.a.get('/workspace').status_code,401)
        r=self.a.post('/api/auth/register',json=self.credentials)
        self.assertEqual(r.status_code,201)
        self.assertIn('HttpOnly',r.headers['set-cookie'])
        self.assertIn('SameSite=strict',r.headers['set-cookie'])
        self.assertEqual(self.b.post('/api/auth/register',json=self.credentials).status_code,409)
        self.assertEqual(self.b.post('/api/auth/login',json={**self.credentials,'password':'incorrect-password'}).status_code,401)
        old=self.a.cookies.get(accounts.COOKIE)
        self.assertEqual(self.a.post('/api/auth/logout').status_code,200)
        self.a.cookies.set(accounts.COOKIE,old)
        self.assertEqual(self.a.get('/api/auth/me').status_code,401)
        self.a.cookies.clear()
        self.assertEqual(self.a.post('/api/auth/login',json=self.credentials).status_code,200)
        actions=[r['action'] for r in self.a.get('/api/activity').json()['items']]
        self.assertEqual(actions,['login','logout','register'])
        with accounts.database() as db:
            row=db.execute('SELECT password FROM users').fetchone()
            self.assertNotIn(self.credentials['password'],row['password'])
            db.execute('UPDATE sessions SET expires=0')
        self.assertEqual(self.a.get('/api/auth/me').status_code,401)

    def test_ownership_and_history(self):
        self.a.post('/api/auth/register',json=self.credentials)
        self.b.post('/api/auth/register',json={'username':'teacher_b','password':'another-password'})
        fixture=next((app.ROOT/'tests'/'cases').glob('*.docx'))
        with patch.object(app,'run_job'):
            r=self.a.post('/api/essays',files={'file':(fixture.name,fixture.read_bytes())},data={'start':app.paragraphs_from_docx(fixture)[0]})
        self.assertEqual(r.status_code,200)
        job=r.json()['id']
        self.assertEqual(len(self.a.get('/api/essays').json()),1)
        self.assertEqual(self.b.get('/api/essays').json(),[])
        for suffix in ('','/preview','/download'):
            self.assertEqual(self.b.get('/api/essays/'+job+suffix).status_code,404)
        self.assertEqual(self.b.post('/api/essays/'+job+'/retry').status_code,404)
        self.assertEqual(self.a.post('/api/essays/'+job+'/retry').status_code,409)
        folder=self.root/job
        with patch.object(app, 'call_openai', return_value=''):
            app.run_job(job, None)
        self.assertEqual(app.read_meta(folder/'meta.json')['status'], 'succeeded')
        self.assertEqual(self.a.get('/api/essays/'+job+'/download').status_code,200)
        self.assertEqual(self.a.get('/api/essays/'+job+'/preview').status_code,200)
        meta=json.loads((folder/'meta.json').read_text(encoding='utf-8'));meta['status']='failed'
        (folder/'meta.json').write_text(json.dumps(meta),encoding='utf-8')
        # A completed, charged job cannot be retried just by changing a JSON file.
        with patch.object(app,'run_job') as run:
            self.assertEqual(self.a.post('/api/essays/'+job+'/retry').status_code,409)
            run.assert_not_called()
        actions=[r['action'] for r in self.a.get('/api/activity').json()['items']]
        self.assertEqual(actions,['preview','download','succeeded','upload','register'])
        self.assertEqual([r['action'] for r in self.b.get('/api/activity').json()['items']],['register'])
        with accounts.database() as db:
            for n in range(55):db.execute('INSERT INTO events(user_id,action,detail,created) VALUES(1,?,?,?)',('preview',str(n),time.time()))
        page=self.a.get('/api/activity').json()
        self.assertEqual(len(page['items']),50)
        page2=self.a.get('/api/activity?before='+str(page['next'])).json()
        self.assertFalse(set(x['id'] for x in page['items']) & set(x['id'] for x in page2['items']))

    def test_validation_and_csrf(self):
        self.assertEqual(self.a.post('/api/auth/register',json={**self.credentials,'password':'short'}).status_code,422)
        self.assertEqual(self.a.post('/api/auth/register',json={**self.credentials,'username':'../bad'}).status_code,400)
        self.assertEqual(self.a.post('/api/auth/register',json=self.credentials,headers={'Origin':'https://other.invalid'}).status_code,403)
        self.assertEqual(self.a.post('/api/auth/register',json=self.credentials,headers={'Sec-Fetch-Site':'cross-site'}).status_code,403)
        with accounts.database() as db:
            db.execute('INSERT OR REPLACE INTO attempts VALUES(?,?,?)',('testclient',30,time.time()+900))
        self.assertEqual(self.a.post('/api/auth/login',json=self.credentials).status_code,429)

    def test_roles_and_admin_permissions(self):
        r=self.a.post('/api/auth/register',json={**self.credentials,'role':'admin'})
        self.assertEqual(r.json()['role'],'user')
        first=r.json()['id']
        self.assertEqual(self.a.get('/api/admin/users').status_code,403)
        self.assertEqual(self.b.get('/api/admin/users').status_code,401)
        with accounts.database() as db:
            db.execute("UPDATE users SET role='admin' WHERE id=?",(first,))
        self.assertEqual(self.a.get('/api/auth/me').json()['role'],'admin')
        second=self.b.post('/api/auth/register',json={'username':'teacher_b','password':'another-password'}).json()['id']
        endpoint=f'/api/admin/users/{second}/role'
        self.assertEqual(self.b.patch(endpoint,json={'role':'admin'}).status_code,403)
        self.assertEqual(self.a.patch(endpoint,json={'role':'invalid'}).status_code,422)
        self.assertEqual(self.a.patch(endpoint,json={'role':'vip'}).json()['role'],'vip')
        self.assertEqual(self.b.get('/api/auth/me').json()['role'],'vip')
        self.assertEqual(self.b.get('/api/admin/users').status_code,403)
        self.assertEqual(self.a.patch(f'/api/admin/users/{first}/role',json={'role':'user'}).status_code,409)
        self.assertEqual(len(self.a.get('/api/admin/users').json()),2)
        self.assertEqual(self.a.patch('/api/admin/users/999/role',json={'role':'user'}).status_code,404)

    def test_regular_user_daily_grading_limit(self):
        self.a.post('/api/auth/register',json=self.credentials)
        fixture=next((app.ROOT/'tests'/'cases').glob('*.docx'))
        with patch.object(app,'run_job'):
            payload={'file':(fixture.name,fixture.read_bytes())}
            self.assertEqual(self.a.post('/api/essays',files=payload).status_code,200)
            self.assertEqual(self.a.post('/api/essays',files=payload).status_code,429)
        with accounts.database() as db:
            db.execute("UPDATE users SET role='vip' WHERE username=?",(self.credentials['username'],))
        with patch.object(app,'run_job'):
            self.assertEqual(self.a.post('/api/essays',files=payload).status_code,429)
        # Legacy role flags do not constitute a paid subscription.
        with accounts.database() as db:
            db.execute('INSERT INTO subscriptions VALUES(?,?,?,?,?,?,?,?,?)', ('pro-test',1,'pro','active',time.time()-10,time.time()+86400,100,None,time.time()))
        with patch.object(app,'run_job'):
            self.assertEqual(self.a.post('/api/essays',files=payload).status_code,200)

    def test_legacy_role_migration(self):
        with accounts.database() as db:
            db.execute('DROP TABLE users')
            db.execute('CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL)')
            db.execute('INSERT INTO users VALUES(7,?,?)',('old_teacher',accounts.password_hash('old-password')))
        accounts.initialize()
        accounts.initialize()
        r=self.a.post('/api/auth/login',json={'username':'old_teacher','password':'old-password'})
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.json()['id'],7)
        self.assertEqual(r.json()['role'],'user')

if __name__=='__main__':unittest.main()
