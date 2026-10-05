"""Password-authenticated maintenance session; credentials stay in process memory."""
import getpass
import json
import sys
from pathlib import Path

import paramiko

from sync_server_skill import powershell


def main():
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    password = getpass.getpass('Server password: ')
    try:
        client.connect('123.57.106.87', username='Administrator', password=password,
                       look_for_keys=False, allow_agent=False, timeout=15,
                       auth_timeout=15, banner_timeout=15)
        password = None
        print('SSH authenticated. Awaiting maintenance actions.', flush=True)
        for line in sys.stdin:
            try:
                action = json.loads(line)
                if action['action'] == 'close':
                    break
                if action['action'] == 'upload':
                    local = Path(action['local']).resolve()
                    root = Path(__file__).resolve().parents[1]
                    if not local.is_relative_to(root):
                        raise ValueError('Upload must come from the project workspace')
                    remote = action['remote'].replace('\\', '/')
                    if not remote.startswith('C:/essay-grading/') or '/..' in remote:
                        raise ValueError('Unexpected remote upload path')
                    with client.open_sftp() as sftp:
                        sftp.put(str(local), remote)
                    print('Upload completed.', flush=True)
                elif action['action'] == 'exec':
                    powershell(client, action['command'], timeout=action.get('timeout', 120))
                elif action['action'] == 'download':
                    local = Path(action['local']).resolve()
                    root = Path(__file__).resolve().parents[1]
                    if not local.is_relative_to(root):
                        raise ValueError('Download must stay in the project workspace')
                    remote = action['remote'].replace('\\', '/')
                    if not remote.startswith('C:/essay-grading/') or '/..' in remote:
                        raise ValueError('Unexpected remote download path')
                    local.parent.mkdir(parents=True, exist_ok=True)
                    with client.open_sftp() as sftp:
                        sftp.get(remote, str(local))
                    print('Download completed.', flush=True)
                else:
                    raise ValueError('Unknown action')
                print('ACTION_COMPLETE', flush=True)
            except Exception as exc:
                print('ACTION_FAILED: ' + str(exc), flush=True)
    finally:
        password = None
        client.close()


if __name__ == '__main__':
    main()
