"""Upload the reviewed skill package over SSH; ask for the password interactively."""
import argparse
import base64
import getpass
from concurrent.futures import ThreadPoolExecutor
from xml.etree import ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import paramiko


def powershell(client, command, timeout=90):
    command = "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); $ErrorActionPreference = 'Stop'; $ProgressPreference = 'SilentlyContinue'; " + command
    encoded = base64.b64encode(command.encode('utf-16-le')).decode('ascii')
    _, stdout, stderr = client.exec_command(
        'powershell.exe -NoProfile -NonInteractive -EncodedCommand ' + encoded,
        timeout=timeout,
    )
    # Drain both SSH streams together: PowerShell's CLIXML progress/error stream
    # can otherwise fill its buffer while the caller waits for stdout EOF.
    with ThreadPoolExecutor(max_workers=2) as readers:
        output_read = readers.submit(stdout.read)
        errors_read = readers.submit(stderr.read)
        output = output_read.result().decode('utf-8', errors='replace')
        errors = errors_read.result().decode('utf-8', errors='replace')
    status = stdout.channel.recv_exit_status()
    if output:
        print(output.strip(), flush=True)
    if status:
        if '#< CLIXML' in errors:
            try:
                tree = ET.fromstring(errors.split('#< CLIXML', 1)[1].strip())
                messages = [node.text or '' for node in tree.iter()
                            if node.tag.endswith('}S') and node.get('S') == 'Error']
                errors = '\n'.join(messages).replace('_x000D_', '').replace('_x000A_', '\n') or errors
            except ET.ParseError:
                pass
        raise RuntimeError(f'Remote operation failed ({status}): {errors[-4000:]}')
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='123.57.106.87')
    parser.add_argument('--user', default='Administrator')
    parser.add_argument('--package', type=Path)
    parser.add_argument('--deployment-script', default='sync-annotation-skill.ps1')
    args = parser.parse_args()
    package = args.package or Path(__file__).resolve().parent.parent / 'output/server-annotation-skill-20261004.zip'
    if not package.is_file():
        raise RuntimeError('Validated skill package missing')
    password = getpass.getpass('Server password: ')
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(args.host, username=args.user, password=password,
                       look_for_keys=False, allow_agent=False,
                       timeout=15, auth_timeout=15, banner_timeout=15)
        password = None
        print('SSH authenticated.', flush=True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        remote_root = 'C:/essay-grading/backups/upload-annotation-skill-' + stamp
        powershell(client, "New-Item -ItemType Directory -Path '" + remote_root + "' | Out-Null")
        with client.open_sftp() as sftp:
            sftp.put(str(package), remote_root + '/package.zip')
        print('Package uploaded.', flush=True)
        powershell(client,
                   "Expand-Archive -LiteralPath '" + remote_root + "/package.zip' -DestinationPath '" + remote_root + "/package'; "
                   "& '" + remote_root + "/package/" + args.deployment_script + "' -PackageDirectory '" + remote_root + "/package'")
        print('Server sync verified.', flush=True)
    finally:
        password = None
        client.close()


if __name__ == '__main__':
    main()
