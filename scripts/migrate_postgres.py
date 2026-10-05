"""Copy a SQLite database into an EMPTY PostgreSQL database, preserving ids.

Usage: DATABASE_URL=postgresql://... python scripts/migrate_postgres.py --source data/accounts.sqlite3
The source is copied before schema upgrades; the original SQLite file is not modified.
"""
import argparse
import os
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv()
from backend import accounts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    args = parser.parse_args()
    url = os.getenv('DATABASE_URL', '')
    if not url.startswith(('postgres://', 'postgresql://')):
        parser.error('DATABASE_URL must point to PostgreSQL')
    source = args.source.resolve(strict=True)
    original_db = accounts.DB
    with tempfile.TemporaryDirectory() as directory:
        clone = Path(directory) / 'accounts.sqlite3'
        with closing(sqlite3.connect(source)) as incoming, closing(sqlite3.connect(clone)) as outgoing:
            incoming.backup(outgoing)
        os.environ['DATABASE_URL'] = ''
        previous_data = os.environ.get('ESSAY_DATA_DIR')
        os.environ['ESSAY_DATA_DIR'] = str(source.parent)
        accounts.DB = clone
        accounts.initialize()
        with accounts.database() as db:
            tables = [r['name'] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            snapshot = {table: [dict(row) for row in db.execute(f'SELECT * FROM {table}')] for table in tables}
        accounts.DB = original_db
        os.environ['DATABASE_URL'] = url
        if previous_data is None:
            os.environ.pop('ESSAY_DATA_DIR', None)
        else:
            os.environ['ESSAY_DATA_DIR'] = previous_data
        accounts.initialize()
        with accounts.database() as db:
            for table in tables:
                if table not in ('plans', 'schema_migrations') and db.execute(f'SELECT COUNT(*) AS n FROM {table}').fetchone()['n']:
                    raise RuntimeError('Target database must be empty; found rows in ' + table)
            for table, rows in snapshot.items():
                if table in ('plans', 'schema_migrations'):
                    continue
                for row in rows:
                    columns = list(row)
                    db.execute(f'INSERT INTO {table}({",".join(columns)}) VALUES({",".join("?" for _ in columns)})', tuple(row[c] for c in columns))
                if db.execute(f'SELECT COUNT(*) AS n FROM {table}').fetchone()['n'] != len(rows):
                    raise RuntimeError('Row count mismatch: ' + table)
            for table in ('users', 'events'):
                db.execute(f"SELECT setval(pg_get_serial_sequence('{table}','id'),COALESCE(MAX(id),1),MAX(id) IS NOT NULL) FROM {table}")
        print('Migration complete. Row counts verified; existing file paths and user/job ids preserved.')


if __name__ == '__main__':
    main()
