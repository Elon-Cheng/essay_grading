"""Backup DB and essay files; verify/restore to an empty directory.

PostgreSQL backups require pg_dump. For PostgreSQL restore, unpack first,
then restore database.dump with pg_restore into an empty database.
"""
import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit, unquote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv()
import accounts


def backup(target):
    root = Path(os.getenv('ESSAY_DATA_DIR', str(accounts.DB.parent))).resolve()
    target = target.resolve()
    if target.is_relative_to(root):
        raise ValueError('Backup archive must be outside the data directory')
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise ValueError('Backup output already exists')
    url = os.getenv('DATABASE_URL', '')
    with tempfile.TemporaryDirectory() as directory:
        temp = Path(directory)
        postgres = url.startswith(('postgres://', 'postgresql://'))
        db_file = temp / ('database.dump' if postgres else 'accounts.sqlite3')
        if postgres:
            parsed = urlsplit(url)
            env = {**os.environ, 'PGHOST': parsed.hostname, 'PGPORT': str(parsed.port or 5432), 'PGUSER': unquote(parsed.username or ''), 'PGPASSWORD': unquote(parsed.password or ''), 'PGDATABASE': parsed.path.lstrip('/')}
            subprocess.run(['pg_dump', '--format=custom', '--file', str(db_file)], env=env, check=True)
        else:
            with closing(sqlite3.connect(accounts.DB)) as source, closing(sqlite3.connect(db_file)) as destination:
                source.backup(destination)
        manifest = {'database': db_file.name, 'files': {}}
        try:
            with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
                files = [('data/' + db_file.name, db_file)] + [('data/' + f.relative_to(root).as_posix(), f) for f in root.rglob('*') if f.is_file() and f.name not in ('accounts.sqlite3', 'accounts.sqlite3-wal', 'accounts.sqlite3-shm')]
                for name, file in files:
                    data = file.read_bytes()
                    manifest['files'][name] = hashlib.sha256(data).hexdigest()
                    archive.writestr(name, data)
                archive.writestr('manifest.json', json.dumps(manifest))
        except BaseException:
            target.unlink(missing_ok=True)
            raise
    verify(target)
    print('Backup complete; archive checksums verified.')


def verify(archive_path, restore=None):
    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        if set(archive.namelist()) != set(manifest['files']) | {'manifest.json'}:
            raise ValueError('Unexpected archive contents')
        for name, expected in manifest['files'].items():
            if '\\' in name or name.startswith('/') or '..' in Path(name).parts:
                raise ValueError('Unsafe archive path')
            data = archive.read(name)
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError('Checksum mismatch: ' + name)
        if restore:
            target = restore.resolve()
            if target.exists() and any(target.iterdir()):
                raise ValueError('Restore target must be empty')
            for name in manifest['files']:
                file = target / name
                if not file.resolve().is_relative_to(target):
                    raise ValueError('Unsafe restore target')
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(archive.read(name))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('backup', 'verify', 'restore'))
    parser.add_argument('archive', type=Path)
    parser.add_argument('--target', type=Path)
    args = parser.parse_args()
    if args.action == 'backup':
        backup(args.archive)
    else:
        if args.action == 'restore' and not args.target:
            parser.error('--target is required for restore')
        verify(args.archive, args.target if args.action == 'restore' else None)
        print('Verification/restore complete.')


if __name__ == '__main__':
    main()
