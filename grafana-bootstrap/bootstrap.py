"""Deploy or remove the local portable demo using the selected kubectl context."""
import argparse
import json
import pathlib
import secrets
import shutil
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent
OWNER = 'grafana-assessment-portable'


def run(*args, input=None):
    return subprocess.run(args, input=input, text=True, check=True,
                          capture_output=True, timeout=700).stdout


def namespace():
    output = run('kubectl', 'get', 'namespace', 'monitoring',
                 '--ignore-not-found', '-o', 'json')
    resource = json.loads(output) if output else None
    if resource and resource['metadata'].get('labels', {}).get('app.kubernetes.io/part-of') != OWNER:
        raise RuntimeError('Namespace monitoring belongs to another setup. Use a fresh cluster.')
    return resource


def deploy():
    namespace()
    print(run('kubectl', 'apply', '--server-side', '-f', str(ROOT / 'namespace.yaml')), end='')
    if not run('kubectl', '-n', 'monitoring', 'get', 'secret', 'grafana-admin',
               '--ignore-not-found', '-o', 'name'):
        # Generate the password in memory and send it over stdin; never write it to a file.
        secret = {'apiVersion': 'v1', 'kind': 'Secret',
                  'metadata': {'name': 'grafana-admin', 'namespace': 'monitoring'},
                  'stringData': {'admin-password': secrets.token_urlsafe(32)}}
        print(run('kubectl', 'create', '-f', '-', input=json.dumps(secret)), end='')
    print(run('kubectl', 'apply', '--server-side', '-k', str(ROOT)), end='')
    print('Waiting for application pods. Initial image downloads can take several minutes.', flush=True)
    subprocess.run(['kubectl', '-n', 'monitoring', 'get', 'pods'], check=True, timeout=30)
    for app in ('grafana', 'prometheus', 'loki', 'alloy'):
        print(f'Waiting for {app} to become ready...', flush=True)
        subprocess.run(['kubectl', '-n', 'monitoring', 'rollout', 'status',
                        'deployment/' + app, '--timeout=600s'], check=True, timeout=700)
    print('Ready. Run make forward, then open http://localhost:3000. Run make test for integration checks.')


def clean():
    if namespace():
        print(run('kubectl', 'delete', 'namespace', 'monitoring', '--wait=true'), end='')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('deploy', 'clean'), nargs='?', default='deploy')
    arguments = parser.parse_args()
    try:
        if not shutil.which('kubectl'):
            raise RuntimeError('kubectl must be installed and authenticated first.')
        print('Selected kubectl context: ' + run('kubectl', 'config', 'current-context').strip(), flush=True)
        {'deploy': deploy, 'clean': clean}[arguments.action]()
    except (RuntimeError, subprocess.SubprocessError) as error:
        if isinstance(error, subprocess.CalledProcessError):
            parser.exit(1, error.stderr or str(error) + '\n')
        parser.exit(1, str(error) + '\n')
