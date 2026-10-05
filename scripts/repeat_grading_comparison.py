"""Run two independent full grading pipelines on identical source bytes."""
import argparse
import hashlib
import json
import logging
import os
import shutil
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
from dotenv import load_dotenv
load_dotenv(root / '.env')
import app
import accounts
from review_annotations import report_sections
from skill_prompt import prompt_files


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-job', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source_folder = app.DATA / args.source_job
    source = source_folder / 'source.docx'
    original = source.read_bytes()
    with accounts.database() as db:
        source_job = db.execute('SELECT start FROM jobs WHERE id=?', (args.source_job,)).fetchone()
    start = source_job['start'] if source_job else None
    args.output.mkdir(parents=True, exist_ok=False)
    shutil.copy2(source, args.output / 'original.docx')
    prompt_hashes = {name:hashlib.sha256((root / 'references' / name).read_bytes()).hexdigest()
                     for name in dict.fromkeys(prompt_files('annotations') + prompt_files('report'))}
    results = {'source_job':args.source_job, 'source_sha256':hashlib.sha256(original).hexdigest(),
               'model':os.getenv('OPENAI_MODEL'), 'provider':os.getenv('OPENAI_BASE_URL'),
               'prompt_hashes':prompt_hashes, 'runs':[]}
    # A separate process-local data directory keeps this comparison out of users' queues.
    app.DATA = args.output
    for label in ('A','B'):
        ident = uuid.uuid4().hex
        folder = args.output / ident
        folder.mkdir()
        (folder / 'source.docx').write_bytes(original)
        app.write_meta(folder / 'meta.json', {'id':ident,'filename':'repeat-'+label+'.docx',
                       'status':'queued','stage':'queued','created':time.time()})
        begun = time.monotonic()
        print('Starting independent run ' + label, flush=True)
        app.run_job(ident, start)
        meta = app.read_meta(folder / 'meta.json')
        run = {'label':label,'id':ident,'status':meta['status'],'channels':meta.get('channels',{}),
               'error':meta.get('error'),'seconds':round(time.monotonic()-begun,2),
               'source_sha256':hashlib.sha256((folder/'source.docx').read_bytes()).hexdigest()}
        if (folder/'annotations.json').exists():
            run['annotations'] = app.read_meta(folder/'annotations.json')
        if (folder/'grading.md').exists():
            run['review'] = report_sections((folder/'grading.md').read_text(encoding='utf-8'))
        with accounts.database() as db:
            run['calls'] = [dict(row) for row in db.execute(
                'SELECT status,error_code,model,returned_model,latency_ms,input_tokens,output_tokens FROM ai_calls WHERE job_id=? ORDER BY started', (ident,)).fetchall()]
        results['runs'].append(run)
        (args.output/'results.json').write_text(json.dumps(results,ensure_ascii=False),encoding='utf-8')
        print(json.dumps({k:v for k,v in run.items() if k not in ('annotations','review')},ensure_ascii=False),flush=True)
    for name,digest in prompt_hashes.items():
        assert hashlib.sha256((root/'references'/name).read_bytes()).hexdigest() == digest, 'Prompt changed during comparison'
    assert all(run['source_sha256']==results['source_sha256'] for run in results['runs'])
    (args.output/'done.json').write_text(json.dumps({'complete':True}),encoding='utf-8')
    print('Comparison finished.',flush=True)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    main()
