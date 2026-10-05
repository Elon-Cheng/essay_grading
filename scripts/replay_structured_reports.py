"""Replay saved failed reports through the JSON contract without calling any AI.

Only explicit existing feedback, scores and band selections are transferred.
Missing grading decisions remain errors; this is not a new model success test.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app
from grading_contract import EVALUATION_FIELDS, parse_report, render_report
from report_normalization import normalize_report
from review_annotations import report_sections


def extract_data(text):
    text = normalize_report(text)
    review = report_sections(text)
    data = {'context': review['context'], 'paragraphs': [], 'evaluation': {}, 'score': {}}
    for number, part in enumerate(review['paragraphs'], 1):
        fields = {f['title']: f['text'] for f in part['feedback']}
        data['paragraphs'].append(dict(paragraph=number,
            kind='format' if '格式说明' in fields else 'content',
            analysis=fields.get('段落点评', ''), language=fields.get('语言提升', ''),
            suggestions=fields.get('问题建议', ''), format_note=fields.get('格式说明', '')))
    detail_keys = ('comprehensive_sections', 'task_sections', 'cohesion_sections',
                   'lexical_sections', 'grammar_sections')
    if review['evaluation']['version'] != 3:
        raise ValueError('Existing report does not contain all evaluation sections')
    for (key, labels, fields), block, detail in zip(EVALUATION_FIELDS, review['evaluation']['blocks'], detail_keys):
        entries = {entry['title']: entry['text'] for entry in block.get(detail, [])}
        data['evaluation'][key] = {field: entries[label] for label, field in zip(labels, fields)}
    score = re.search(r'本篇文章打分估计为[：:]\s*(\d+(?:\.\d+)?)(?:\s*[–—－~～-]\s*(\d+(?:\.\d+)?))?\s*分', review['overall'])
    if not score:
        raise ValueError('Missing explicit score')
    data['score'].update(low=float(score[1]), high=float(score[2] or score[1]))
    rows = [line.strip().strip('|').split('|') for line in review['overall'].splitlines()
            if re.match(r'^\|\s*[ABCDE]\s*\|', line)]
    for column, key in enumerate(('content_band', 'language_band', 'organization_band'), 1):
        selected = [row[0].strip() for row in rows if len(row) == 4 and '[[red]]' in row[column]]
        if len(selected) != 1:
            raise ValueError('Missing explicit ' + key + '; not inferred from the total score')
        data['score'][key] = selected[0]
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    source = app.source_paragraphs((args.input / 'source.md').read_text(encoding='utf-8'))
    results = []
    for path in sorted(args.input.glob('interim-*/*.md')):
        if path.name == 'source.md':
            continue
        result = {'candidate': str(path.relative_to(args.input))}
        try:
            data = extract_data(path.read_text(encoding='utf-8'))
            annotations = json.loads((args.input / path.parent.name.removeprefix('interim-') / 'annotations.json').read_text(encoding='utf-8'))
            report = parse_report(json.dumps(data), source)
            rendered = render_report(report, source, annotations)
            app.validate_report(rendered, source)
            target = args.output / path.stem
            target.mkdir()
            (target / 'report.json').write_text(report.model_dump_json(indent=2), encoding='utf-8')
            (target / 'grading.md').write_text(rendered, encoding='utf-8')
            review = report_sections(rendered)
            for number, part in enumerate(review['paragraphs'], 1):
                part['paragraph'] = number
                part['feedback'] = [f for f in part['feedback'] if f['title'] != '语言提升']
            preview = {'original': source, 'annotations': annotations, 'review': review,
                       'channels': {'annotations': 'ready', 'report': 'ready'},
                       'prompt': '', 'translations': {'en': {}, 'zh': {}}}
            (target / 'preview.json').write_text(json.dumps(preview, ensure_ascii=False), encoding='utf-8')
            subprocess.run([sys.executable, str(ROOT / 'scripts/render_grading_docx.py'),
                            '--source-docx', str(args.input / 'original.docx'),
                            '--source-md', str(args.input / 'source.md'),
                            '--grading-md', str(target / 'grading.md'),
                            '--output-docx', str(target / 'graded.docx')],
                           check=True, capture_output=True, encoding='utf-8', timeout=60)
            result.update(status='passed', word_ready=True)
        except (ValueError, KeyError, subprocess.CalledProcessError) as exc:
            result.update(status='rejected', error=str(exc))
        results.append(result)
    summary = {'mode': 'offline-replay-no-ai', 'candidates': results,
               'passed': sum(r['status'] == 'passed' for r in results),
               'total': len(results)}
    (args.output / 'results.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
