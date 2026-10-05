"""Create or update a local account, intended for server-side administration.

Usage: python scripts/manage_user.py cyl admin
"""
import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import accounts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('username')
    parser.add_argument('role', choices=('user', 'vip', 'admin'))
    parser.add_argument('--password-stdin', action='store_true')
    args = parser.parse_args()
    name = accounts.normalize(args.username)
    password = sys.stdin.readline().rstrip('\r\n') if args.password_stdin else getpass.getpass('Password: ')
    if not 8 <= len(password) <= 128:
        parser.error('Password must contain 8-128 characters')
    accounts.initialize()
    with accounts.database() as db:
        row = db.execute('SELECT id FROM users WHERE username=?', (name,)).fetchone()
        if row:
            db.execute('UPDATE users SET password=?, role=? WHERE id=?',
                       (accounts.password_hash(password), args.role, row['id']))
            db.execute('DELETE FROM sessions WHERE user_id=?', (row['id'],))
            user_id = row['id']
            action = 'account_updated'
        else:
            cursor = db.execute('INSERT INTO users(username,password,role) VALUES(?,?,?)',
                                (name, accounts.password_hash(password), args.role))
            user_id = cursor.lastrowid
            action = 'account_created'
    accounts.audit(user_id, action, args.role)
    print(f'{name}: {args.role}')


if __name__ == '__main__':
    main()
