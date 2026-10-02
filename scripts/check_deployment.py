"""Exercise the deployed demo workflow with disposable accounts and a DOCX."""
import io
import secrets
import sys
import time
import zipfile

import httpx

base_url = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1'
suffix = secrets.token_hex(4)
names = ['deploy_a_' + suffix, 'deploy_b_' + suffix]
buffer = io.BytesIO()
with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
    archive.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
    archive.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
    archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Reading books helps students understand the world. For example, stories introduce different cultures and encourage careful thinking.</w:t></w:r></w:p><w:sectPr/></w:body></w:document>')

with httpx.Client(base_url=base_url, timeout=30, trust_env=False) as a, httpx.Client(base_url=base_url, timeout=30, trust_env=False) as b:
    for path in ('/', '/login', '/healthz', '/robots.txt', '/sitemap.xml', '/static/login.js', '/static/style.css'):
        response = a.get(path)
        assert response.status_code == 200, (path, response.status_code)
    assert a.get('/api/essays').status_code == 401
    for client, name in zip((a, b), names):
        response = client.post('/api/auth/register', json={'username': name, 'password': secrets.token_urlsafe(18)})
        assert response.status_code == 201, response.text
    print('Test accounts:', ', '.join(names), flush=True)
    assert a.get('/workspace').status_code == 200
    response = a.post('/api/essays', files={'file': ('deployment-check.docx', buffer.getvalue())})
    assert response.status_code == 200, response.text
    job = response.json()['id']
    print('Test document:', job, flush=True)
    for _ in range(60):
        response = a.get('/api/essays/' + job)
        assert response.status_code == 200, response.text
        result = response.json()
        if result['status'] in ('succeeded', 'failed'):
            break
        time.sleep(1)
    assert result['status'] == 'succeeded', result
    assert a.get('/api/essays/' + job + '/preview').json()['grading']
    response = a.get('/api/essays/' + job + '/download')
    assert response.status_code == 200 and response.content.startswith(b'PK')
    assert b.get('/api/essays').json() == []
    for tail in ('', '/preview', '/download'):
        assert b.get('/api/essays/' + job + tail).status_code == 404
    assert a.post('/api/auth/logout').status_code == 200
    assert a.get('/api/essays').status_code == 401
    print('PASS: pages, assets, registration, session, workspace, DOCX upload, grading, preview, download, account isolation, logout')
