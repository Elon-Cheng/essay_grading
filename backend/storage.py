"""Small DB-API bridge: SQLite for local use, PostgreSQL for deployment."""
import os
import re
import sqlite3
from contextlib import contextmanager


class Row(dict):
    def __getitem__(self, key):
        return list(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


class Cursor:
    def __init__(self, cursor, lastrowid=None):
        self.cursor = cursor
        self.lastrowid = lastrowid
        self.rowcount = cursor.rowcount

    def fetchone(self):
        row = self.cursor.fetchone()
        return Row(row) if row is not None else None

    def fetchall(self):
        return [Row(row) for row in self.cursor.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())


class Connection:
    def __init__(self, raw, postgres=False):
        self.raw, self.postgres = raw, postgres

    def execute(self, sql, params=()):
        if sql.strip().upper() == 'BEGIN IMMEDIATE':
            return Cursor(self.raw.execute('SELECT 1'))
        if self.postgres:
            sql = sql.replace('?', '%s')
            sql = re.sub(r'\bREAL\b', 'DOUBLE PRECISION', sql)
            sql = sql.replace('INTEGER PRIMARY KEY', 'BIGSERIAL PRIMARY KEY')
            auto_id = re.match(r'\s*INSERT INTO (users|events)\b', sql, re.I) and 'RETURNING' not in sql.upper()
            if auto_id:
                cursor = self.raw.execute(sql + ' RETURNING id', params)
                return Cursor(cursor, cursor.fetchone()['id'])
        cursor = self.raw.execute(sql, params)
        return Cursor(cursor, getattr(cursor, 'lastrowid', None))

    def executescript(self, sql):
        for statement in sql.split(';'):
            if statement.strip():
                self.execute(statement)

    def columns(self, table):
        if self.postgres:
            return {r['column_name'] for r in self.execute(
                'SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=?', (table,))}
        return {r['name'] for r in self.execute(f'PRAGMA table_info({table})')}


@contextmanager
def connect(path):
    url = os.getenv('DATABASE_URL', '')
    postgres = url.startswith(('postgresql://', 'postgres://'))
    if postgres:
        import psycopg
        from psycopg.rows import dict_row
        raw = psycopg.connect(url, row_factory=dict_row, connect_timeout=10)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = sqlite3.connect(path, timeout=30)
        raw.row_factory = sqlite3.Row
        raw.execute('PRAGMA busy_timeout=30000')
    try:
        # Serialize short business transactions across workers, including quota and payments.
        if postgres:
            raw.execute('SELECT pg_advisory_xact_lock(73150915)')
        else:
            raw.execute('BEGIN IMMEDIATE')
        yield Connection(raw, postgres)
        raw.commit()
    except BaseException:
        raw.rollback()
        raise
    finally:
        raw.close()
