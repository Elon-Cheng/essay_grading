"""Recover validated annotations from saved provider output, without calling AI."""
import argparse
import hashlib
import json
import logging
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from review_annotations import parse_annotations
from scripts.render_grading_docx import source_paragraphs


def recover(root, job_id, apply=False):
    if not re.fullmatch(r'[a-f0-9]{32}', job_id):
        raise ValueError('Invalid job ID')
    folder = root / 'data' / job_id
    meta_path = folder / 'meta.json'
    meta = json.loads(meta_path.read_text(encoding='utf-8'))
    if meta.get('status') != 'succeeded' or meta.get('channels', {}).get('report') != 'ready':
        raise ValueError('Recovery requires a completed report')
    annotation_path = folder / 'annotations.json'
    if annotation_path.exists():
        raise ValueError('Saved annotations already exist; refusing to overwrite')
    if meta.get('channels', {}).get('annotations') != 'failed':
        raise ValueError('Annotation channel is not failed')
    paragraphs = source_paragraphs((folder / 'source.md').read_text(encoding='utf-8'))
    candidates = []
    for path in (folder / 'ai-rejected').glob('*.md'):
        raw = path.read_text(encoding='utf-8')
        try:
            items = parse_annotations(raw, paragraphs)
            raw_count = len(json.loads(raw))
        except ValueError:
            continue
        if items:
            candidates.append((len(items), path.stem, raw_count, items))
    if not candidates:
        raise ValueError('No recoverable annotation response found')
    kept, call_id, total, items = max(candidates, key=lambda candidate: candidate[0])
    for item in items:
        assert paragraphs[item['paragraph'] - 1][item['start']:item['end']] == item['quote']
    result = {'job_id':job_id, 'kept':kept, 'discarded':total-kept, 'saved_response':call_id, 'applied':apply}
    if not apply:
        return result
    protected = {name:hashlib.sha256((folder / name).read_bytes()).hexdigest()
                 for name in ('source.docx','source.md','grading.md','graded.docx')}
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = root / 'backups' / ('annotation-recovery-' + job_id + '-' + stamp)
    backup.mkdir(parents=True)
    shutil.copy2(meta_path, backup / 'meta.json')
    # Publish the verified data before marking its channel ready.
    temporary = annotation_path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(items, ensure_ascii=False), encoding='utf-8')
    temporary.replace(annotation_path)
    meta['channels']['annotations'] = 'ready'
    meta['annotation_recovery'] = {**result, 'timestamp_utc':stamp}
    temporary_meta = meta_path.with_suffix('.json.tmp')
    temporary_meta.write_text(json.dumps(meta, ensure_ascii=False), encoding='utf-8')
    temporary_meta.replace(meta_path)
    for name, digest in protected.items():
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest
    result['backup'] = str(backup)
    result['original_and_report_unchanged'] = True
    return result


if __name__ == '__main__':
    logging.basicConfig(stream=sys.stdout, level=logging.WARNING)
    parser = argparse.ArgumentParser()
    parser.add_argument('job_id')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()
    print(json.dumps(recover(args.root, args.job_id, args.apply), ensure_ascii=False))
