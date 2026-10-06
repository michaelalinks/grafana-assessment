"""Bootstrap the portable demo using the selected kubectl context."""
import argparse
import hashlib
import io
import json
import pathlib
import platform
import re
import secrets
import shutil
import subprocess
import tarfile
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
FLUX_VERSION = '2.9.6'
OWNER = 'grafana-assessment-portable'


def run(*args, input=None):
    return subprocess.run(args, input=input, text=True, check=True,
                          capture_output=True, timeout=700).stdout


def get(kind, name, namespace):
    output = run('kubectl', '-n', namespace, 'get', kind, name,
                 '--ignore-not-found', '-o', 'json')
    return json.loads(output) if output else None


def flux_binary():
    system = platform.system().lower()
    machine = {'arm64': 'arm64', 'aarch64': 'arm64',
               'x86_64': 'amd64', 'amd64': 'amd64'}.get(platform.machine().lower())
    if system not in ('linux', 'darwin') or not machine:
        raise RuntimeError('Automatic Flux installation supports Linux/macOS amd64/arm64.')
    binary = ROOT / '.bin' / f'flux-{FLUX_VERSION}-{system}-{machine}'
    if binary.exists():
        return str(binary)
    asset = f'flux_{FLUX_VERSION}_{system}_{machine}.tar.gz'
    url = f'https://github.com/fluxcd/flux2/releases/download/v{FLUX_VERSION}/'
    with urllib.request.urlopen(url + f'flux_{FLUX_VERSION}_checksums.txt', timeout=60) as response:
        checksums = response.read().decode()
    expected = next(line.split()[0] for line in checksums.splitlines()
                    if line.split()[-1] == asset)
    with urllib.request.urlopen(url + asset, timeout=60) as response:
        archive = response.read()
    if hashlib.sha256(archive).hexdigest() != expected:
        raise RuntimeError('Flux download checksum did not match.')
    binary.parent.mkdir(exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as bundle:
        binary.write_bytes(bundle.extractfile('flux').read())
    binary.chmod(0o755)
    return str(binary)


def deploy(git_url, ref):
    for tool in ('kubectl',):
        if not shutil.which(tool):
            raise RuntimeError(f'{tool} must be installed and authenticated first.')
    parsed = urllib.parse.urlparse(git_url)
    if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.query or parsed.fragment:
        raise RuntimeError('Use a public HTTPS Git URL without embedded credentials.')
    if not re.fullmatch(r'[A-Za-z0-9._/-]+', ref):
        raise RuntimeError('Supply a Git branch name, for example main.')
    context = run('kubectl', 'config', 'current-context').strip()
    print(f'Deploying portable demo to kubectl context: {context}', flush=True)
    existing_flux = get('deployment', 'source-controller', 'flux-system')
    existing_root = get('kustomization.kustomize.toolkit.fluxcd.io',
                        'assessment-portable', 'flux-system') if existing_flux else None
    if existing_flux and not existing_root:
        raise RuntimeError('This cluster already has another Flux installation. Use a fresh cluster.')
    namespace = get('namespace', 'monitoring', 'default')
    if namespace and namespace['metadata'].get('labels', {}).get('app.kubernetes.io/part-of') != OWNER:
        raise RuntimeError('Namespace monitoring belongs to another setup. Use a fresh cluster.')
    if not existing_flux:
        manifests = run(flux_binary(), 'install', '--export', '--version=v' + FLUX_VERSION,
                        '--components=source-controller,kustomize-controller', '--network-policy=false')
        print(run('kubectl', 'apply', '--server-side', '-f', '-', input=manifests), end='')
    run('kubectl', 'wait', '--for=condition=Established',
        'crd/gitrepositories.source.toolkit.fluxcd.io',
        'crd/kustomizations.kustomize.toolkit.fluxcd.io', '--timeout=60s')
    print(run('kubectl', 'apply', '--server-side', '-f', str(ROOT / 'namespace.yaml')), end='')
    if not run('kubectl', '-n', 'monitoring', 'get', 'secret', 'grafana-admin',
               '--ignore-not-found', '-o', 'name'):
        # Generate the password in memory and send it over stdin; never write it to Git or a file.
        secret = {'apiVersion': 'v1', 'kind': 'Secret',
                  'metadata': {'name': 'grafana-admin', 'namespace': 'monitoring'},
                  'stringData': {'admin-password': secrets.token_urlsafe(32)}}
        print(run('kubectl', 'create', '-f', '-', input=json.dumps(secret)), end='')
    bootstrap = (ROOT / 'bootstrap.yaml').read_text()
    bootstrap = bootstrap.replace('${GIT_URL}', git_url).replace('${GIT_REF}', ref)
    print(run('kubectl', 'apply', '--server-side', '-f', '-', input=bootstrap), end='')
    for kind in ('gitrepository', 'kustomization'):
        print(run('kubectl', '-n', 'flux-system', 'wait', '--for=condition=Ready',
                  kind + '/assessment-portable', '--timeout=600s'), end='')
    print('Ready. Run make forward, then open http://localhost:3000. Run make test for integration checks.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--git-url', required=True)
    parser.add_argument('--ref', default='main')
    arguments = parser.parse_args()
    try:
        deploy(arguments.git_url, arguments.ref)
    except (RuntimeError, subprocess.SubprocessError, urllib.error.URLError) as error:
        if isinstance(error, subprocess.CalledProcessError):
            parser.exit(1, error.stderr)
        parser.exit(1, str(error) + '\n')
