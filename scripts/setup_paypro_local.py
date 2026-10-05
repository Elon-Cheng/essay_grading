"""Create an isolated local Paypro bundle without changing the supplied source."""
import argparse
import hashlib
from pathlib import Path
import secrets
import shutil

from prepare_paypro import prepare


ROOT = Path(__file__).resolve().parents[1]


def setup(source, target):
    required = ('pom.xml', 'settings.xml', 'Dockerfile', 'src/main/resources/pay.sql')
    for name in required:
        if not (source / name).is_file():
            raise ValueError(f'Missing source file: {name}')
    if target.exists():
        raise ValueError('Target already exists; keep its settings or choose a new --output directory')
    target.mkdir(parents=True)
    app = target / 'source'
    app.mkdir()
    for name in ('pom.xml', 'settings.xml', 'Dockerfile'):
        shutil.copy2(source / name, app / name)
    shutil.copytree(source / 'src', app / 'src')
    prepare(app)
    schema = app / 'src/main/resources/pay.sql'
    schema_text = schema.read_text(encoding='utf-8')
    schema_text = schema_text.replace('`del` int(11)', '`download_url` TEXT NULL,\n                              `del` int(11)', 1)
    admin_password = secrets.token_urlsafe(24)
    schema_text = schema_text.replace('0192023a7bbd73250516f069df18b500', hashlib.md5(admin_password.encode()).hexdigest())
    (target / 'admin-access.txt').write_text(
        'URL: http://localhost:8889/admin/login.html\nUsername: admin\nPassword: ' + admin_password + '\n', encoding='utf-8')
    if '`expire_time`' not in schema_text:
        schema_text += '\nALTER TABLE `t_order` ADD COLUMN `expire_time` DATETIME NULL;\n'
    schema.write_text(schema_text, encoding='utf-8')
    # Use the JAR directly, avoiding the bundled tracing/JMX startup script.
    dockerfile = (app / 'Dockerfile').read_text(encoding='utf-8')
    dockerfile = dockerfile[:dockerfile.index('ENTRYPOINT')]
    dockerfile += 'ENTRYPOINT ["sh", "-c", "exec java -Xms128m -Xmx512m -jar /app/appsystems/*.jar --spring.profiles.active=prod"]\n'
    (app / 'Dockerfile').write_text(dockerfile, encoding='utf-8')
    config = target / 'config'
    config.mkdir()
    (target / 'qr' / 'wechat' / '19.90').mkdir(parents=True)
    template = (ROOT / 'deploy/paypro/application-prod.yml.example').read_text(encoding='utf-8')
    template = template.replace('spring:\n', '''spring:
  datasource:
    url: jdbc:mysql://mysql:3306/pay?useSSL=false&characterEncoding=utf-8&serverTimezone=GMT%2B8
    username: paypro
    password: ${MYSQL_PASSWORD}
  redis:
    host: redis
    port: 6379
    password: ${REDIS_PASSWORD}
    database: 1
''', 1)
    template = template.replace('  mail:\n', '  mail:\n    protocol: smtp\n', 1)
    template = template.replace('          ssl:\n            trust: ${MAIL_HOST}', '          ssl:\n            enable: false\n            trust: ${MAIL_HOST}')
    (config / 'application-prod.yml').write_text(template + "\nGameUrl: ''\n", encoding='utf-8')
    shared = secrets.token_hex(32)
    values = {
        'MYSQL_ROOT_PASSWORD': secrets.token_hex(24),
        'MYSQL_PASSWORD': secrets.token_hex(24),
        'REDIS_PASSWORD': secrets.token_hex(24),
        'PAYPRO_SECRET': shared,
        'PAYPRO_ADMIN_TOKEN_SECRET': secrets.token_hex(32),
        'PAYPRO_PUBLIC_URL': 'http://localhost:8889',
        'PAYPRO_RECEIVER_NAME': '墨评',
        'PAYPRO_REVIEW_EMAIL': '', 'PAYPRO_SUPPORT_EMAIL': '',
        'MAIL_HOST': 'localhost', 'MAIL_PORT': '587',
        'MAIL_USERNAME': '', 'MAIL_PASSWORD': '',
    }
    (target / '.env').write_text(''.join(f'{k}={v}\n' for k, v in values.items()), encoding='utf-8')
    (target / 'essay.env').write_text(
        '# Merge into the essay .env after HTTPS deployment and settlement verification.\n'
        'PAYMENTS_MODE=paypro\nPAYPRO_BASE_URL=http://localhost:8889\n'
        f'PAYPRO_SECRET={shared}\n'
        'PAYPRO_WECHAT_ENABLED=0\nPAYPRO_ALIPAY_ENABLED=0\n'
        'PAYPRO_SETTLEMENT_VERIFIED=0\nPRO_PRICE_FEN=1990\n', encoding='utf-8')
    shutil.copy2(ROOT / 'deploy/paypro/compose.local.yaml', target / 'compose.yaml')
    shutil.copy2(ROOT / 'deploy/paypro/LOCAL_SETUP.md', target / 'README.md')
    print(f'Local bundle created: {target}')
    print('Secrets saved locally; payment channels remain disabled.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', type=Path, default=ROOT / 'output/paypro-local')
    args = parser.parse_args()
    setup(args.source.resolve(), args.output.resolve())
