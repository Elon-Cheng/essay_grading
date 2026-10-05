"""Four identical essays through the live queue, using disabled test accounts."""
import sys,os,time,json,uuid,hashlib,re,secrets
from pathlib import Path
from collections import Counter
root=Path('C:/essay-grading');sys.path.insert(0,str(root))
from dotenv import load_dotenv
load_dotenv(root/'.env')
import app,accounts,saas
from review_annotations import report_sections
from skill_prompt import prompt_files
output=Path(sys.argv[1]);source=output/'original.docx'
original=source.read_bytes();digest=hashlib.sha256(original).hexdigest()
assert digest=='c3dd1dfde38503a45910f758768639aabe472549adbb2956b33109304589e8ef'
with accounts.database() as db:
    prior=db.execute('SELECT start FROM jobs WHERE id=?',('d4c5fa2c1b194011852fa3980554e3dc',)).fetchone()
    assert prior is not None,'Original essay start metadata missing'
    start=prior['start']
    assert db.execute("SELECT COUNT(*) AS n FROM jobs WHERE status IN ('running','queued')").fetchone()['n']==0,'Existing grading jobs active; do not add test load'
app.write_source_md(source,output/'source.md',start)
hashes={name:hashlib.sha256((root/'references'/name).read_bytes()).hexdigest() for name in set(prompt_files('annotations')+prompt_files('report'))}
result={'source_sha256':digest,'model':os.getenv('OPENAI_MODEL'),'reasoning':os.getenv('AI_REASONING_EFFORT'),'worker_concurrency':os.getenv('WORKER_CONCURRENCY'),'prompt_hashes':hashes,'runs':[],'observations':[]}
prepared=[]
for label in 'ABCD':
    ident=uuid.uuid4().hex;folder=app.DATA/ident;folder.mkdir()
    (folder/'source.docx').write_bytes(original)
    prepared.append((label,ident,folder))
with accounts.database() as db:
    for label,ident,folder in prepared:
        username='_parallel4_'+ident[:18]
        user_id=db.execute('INSERT INTO users(username,password,role,disabled) VALUES(?,?,?,?)',(username,accounts.password_hash(secrets.token_hex(32)),'user',1)).lastrowid
        period=saas.reserve(db,user_id,ident)
        now=time.time();filename='parallel-'+label+'.docx'
        content_hash=hashlib.sha256(original+b'\x00'+(start or '').encode()).hexdigest()
        db.execute('INSERT INTO jobs(id,user_id,filename,start,created,updated,request_key,content_hash,quota_period_id,quota_state) VALUES(?,?,?,?,?,?,?,?,?,?)',(ident,user_id,filename,start,now,now,uuid.uuid4().hex,content_hash,period,'reserved'))
        app.write_meta(folder/'meta.json',{'id':ident,'filename':filename,'status':'queued','stage':'queued','user_id':user_id,'created':now})
        saas.audit(db,None,'parallel_grading_test',ident,'同一作文四次并发实测；禁用测试账号，不占用真实用户额度')
        result['runs'].append({'label':label,'id':ident,'user_id':user_id,'created':now})
def save():
    (output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
save();print('Four identical essays committed to the LIVE worker queue.',flush=True)
peak=0;last='';deadline=time.monotonic()+2700
while True:
    with accounts.database() as db:
        rows={row['id']:dict(row) for row in db.execute('SELECT id,status,stage,error,updated,quota_state FROM jobs WHERE id IN (?,?,?,?)',tuple(r['id'] for r in result['runs']))}
    running=sum(row['status']=='running' for row in rows.values());peak=max(peak,running)
    summary=[{'run':r['label'],'status':rows[r['id']]['status'],'stage':rows[r['id']]['stage']} for r in result['runs']]
    msg=json.dumps(summary,ensure_ascii=False)
    if msg!=last:
        print(msg,flush=True);last=msg
        result['observations'].append({'time':time.time(),'running':running,'runs':summary})
    if all(row['status'] in ('failed','succeeded') for row in rows.values()) or time.monotonic()>deadline:break
    time.sleep(3)
result['observed_peak_running']=peak
for run in result['runs']:
    ident=run['id'];folder=app.DATA/ident;row=rows[ident]
    meta=app.read_meta(folder/'meta.json');run.update(row);run['channels']=meta.get('channels',{})
    run['seconds']=round(row['updated']-run['created'],2)
    run['source_sha256']=hashlib.sha256((folder/'source.docx').read_bytes()).hexdigest()
    run['annotations']=app.read_meta(folder/'annotations.json') if (folder/'annotations.json').exists() else []
    if (folder/'grading.md').exists():run['review']=report_sections((folder/'grading.md').read_text(encoding='utf-8'))
    run['word_ready']=(folder/'graded.docx').is_file()
    with accounts.database() as db:
        run['calls']=[dict(r) for r in db.execute('SELECT model,returned_model,started,latency_ms,status,error_code,input_tokens,output_tokens,currency,estimated_cost FROM ai_calls WHERE job_id=? ORDER BY started',(ident,))]
    print(json.dumps({k:v for k,v in run.items() if k not in ('annotations','review','calls')},ensure_ascii=False),flush=True)
result['prompt_unchanged']=all(hashlib.sha256((root/'references'/name).read_bytes()).hexdigest()==value for name,value in hashes.items())
result['complete']=all(r['status'] in ('failed','succeeded') for r in result['runs'])
save()
(output/'done.json').write_text(json.dumps({'complete':result['complete']}),encoding='utf-8')
print('Four-run test report saved. Peak running='+str(peak),flush=True)
