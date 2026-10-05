"""Bounded paid generation probe, using the deployed transport and cost ledger."""
import argparse,json,os,sys,threading,time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
from urllib.parse import urlsplit

def main():
    print('Real AI benchmark starting',flush=True)
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    sys.path.insert(0,str(args.root))
    from dotenv import load_dotenv
    load_dotenv(args.root/'.env')
    import saas,accounts
    from ai_transport import request_response
    base=os.environ['OPENAI_BASE_URL'].rstrip('/')
    parsed=urlsplit(base)
    assert parsed.scheme=='https' and parsed.hostname=='www.su8.codes' and parsed.path=='/v1','Unexpected production endpoint'
    model=os.environ['OPENAI_MODEL'];key=os.environ['OPENAI_API_KEY']
    print('Configured model: '+model,flush=True)
    state={'model':model,'reasoning':os.getenv('AI_REASONING_EFFORT','provider_default'),'stream':os.getenv('AI_STREAM')=='1','scope':'Short real AI requests, not full essay grading','waves':[],'complete':False}
    lock=threading.Lock();active=0;peak=0
    def save():
        temp=args.output.with_suffix('.tmp')
        temp.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
        for attempt in range(30):
            try:
                temp.replace(args.output)
                return
            except PermissionError:
                if attempt==29:raise
                time.sleep(0.1)
    def probe(index,gate):
        nonlocal active,peak
        result={'sample':index,'success':False}
        ident=None;response=None;started=time.monotonic();data={}
        try:
            gate.wait(timeout=20)
            body={'model':model,'store':False,'max_output_tokens':2048,
                  'input':[{'role':'user','content':"Correct this sentence and reply with only the corrected sentence: She go to school every day."}]}
            ident=saas.start_call(None,model,parsed.netloc,len(json.dumps(body).encode()),2048)
            result['call_id']=ident
            with lock:
                active+=1;peak=max(peak,active)
            started=time.monotonic()
            try:
                response=request_response(base+'/responses',key,body)
            finally:
                with lock:active-=1
            result['http']=response.status_code
            data=response.json()
            output=data.get('output_text') or ''.join(c.get('text','') for item in data.get('output',[]) for c in item.get('content',[]) if c.get('type') in ('output_text','text'))
            result.update(returned_model=data.get('model'),usage=data.get('usage'),text=output[:160])
            result['success']=response.status_code==200 and data.get('status','completed')=='completed' and 'goes' in output.lower()
            error=None if result['success'] else 'http_'+str(response.status_code) if response.status_code>=400 else 'probe_output_invalid'
            saas.finish_call(ident,data,response,error=error)
            if error:result['error']=error
        except Exception as exc:
            result['error']=getattr(exc,'reason',type(exc).__name__)
            result['http']=getattr(getattr(exc,'response',None),'status_code',None)
            if ident:
                saas.finish_call(ident,getattr(exc,'data',data),getattr(exc,'response',response),error=result['error'])
        result['seconds']=round(time.monotonic()-started,3)
        return result
    try:
        for count in (2,4,8):
            with accounts.database() as db:
                jobs=db.execute("SELECT COUNT(*) AS n FROM jobs WHERE status IN ('queued','running')").fetchone()['n']
            if jobs:
                state['stop_reason']='Production grading jobs arrived; stopped before next wave'
                break
            peak=0;gate=threading.Barrier(count);start=time.monotonic()
            wave={'concurrency':count,'samples':[]};state['waves'].append(wave);save()
            with ThreadPoolExecutor(max_workers=count) as pool:
                futures=[pool.submit(probe,i+1,gate) for i in range(count)]
                for future in as_completed(futures):
                    wave['samples'].append(future.result());save()
            wave.update(success=sum(s['success'] for s in wave['samples']),requests=count,peak_requests=peak,wall_seconds=round(time.monotonic()-start,3))
            print(json.dumps({k:v for k,v in wave.items() if k!='samples'}),flush=True);save()
            if wave['success']!=count:
                state['stop_reason']='Failures observed; no higher load attempted'
                break
        ids=[s['call_id'] for w in state['waves'] for s in w['samples'] if s.get('call_id')]
        if ids:
            with accounts.database() as db:
                rows=[dict(row) for row in db.execute('SELECT currency,estimated_cost,input_tokens,output_tokens,status FROM ai_calls WHERE id IN ('+','.join('?' for _ in ids)+')',tuple(ids))]
            state['ledger']={'calls':len(rows),'input_tokens':sum(r['input_tokens'] or 0 for r in rows),'output_tokens':sum(r['output_tokens'] or 0 for r in rows),'unknown_cost_calls':sum(r['estimated_cost'] is None for r in rows),'known_cost_by_currency':{c:sum(r['estimated_cost'] or 0 for r in rows if r['currency']==c) for c in {r['currency'] for r in rows}}}
    except Exception as exc:
        state['stop_reason']='Benchmark stopped: '+type(exc).__name__
    finally:
        state['complete']=True;save()
        args.output.with_suffix('.done').write_text('done',encoding='ascii')
    print('Benchmark complete',flush=True)

if __name__=='__main__':main()
