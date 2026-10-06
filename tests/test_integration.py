#!/usr/bin/env python3
"""Live integration checks; uses current kubectl context, no administrator credentials."""
import ipaddress
import json
import os
import subprocess
import time
import pytest
import urllib.error
import urllib.parse
import urllib.request
import uuid

HOST = os.environ.get('GRAFANA_HOST', 'grafana.healthtech.michaelalinks.com')
ZONE = os.environ.get('DNS_ZONE', 'healthtech.michaelalinks.com')
TIMEOUT = int(os.environ.get('TEST_TIMEOUT', '300'))


def command(*args):
    return subprocess.check_output(args, text=True, timeout=TIMEOUT).strip()


def resource(kind, name, namespace):
    return json.loads(command('kubectl', '-n', namespace, 'get', kind, name, '-o', 'json'))


def request(path):
    with urllib.request.urlopen('https://' + HOST + path, timeout=30) as response:
        return json.load(response)


def eventually(check):
    deadline = time.monotonic() + TIMEOUT
    while True:
        try:
            return check()
        except (AssertionError, urllib.error.URLError, subprocess.SubprocessError) as error:
            if time.monotonic() >= deadline:
                raise AssertionError(f'Timed out waiting: {error}') from error
            time.sleep(5)



def test_reconciliation():
    for kind in ('kustomizations.kustomize.toolkit.fluxcd.io',
                 'helmreleases.helm.toolkit.fluxcd.io'):
        items = json.loads(command('kubectl', 'get', kind, '-A', '-o', 'json'))['items']
        assert items, f'No {kind} found'
        for item in items:
            command('kubectl', '-n', item['metadata']['namespace'], 'wait',
                    '--for=condition=Ready', kind + '/' + item['metadata']['name'],
                    f'--timeout={TIMEOUT}s')
    for namespace, name in [('grafana', 'grafana'), ('monitoring', 'prometheus')]:
        command('kubectl', '-n', namespace, 'rollout', 'status', 'deployment/' + name,
                f'--timeout={TIMEOUT}s')


def test_dns():
    def check():
        gateway = resource('gateway', 'public', 'envoy-gateway-system')
        expected = {a['value'] for a in gateway.get('status', {}).get('addresses', [])
                    if a.get('type', 'IPAddress') == 'IPAddress'}
        assert expected, 'Gateway has no assigned IP'
        def addresses(server):
            lines = command('dig', '@' + server, HOST, 'A', '+short',
                            '+time=3', '+tries=1').splitlines()
            found = set()
            for line in lines:
                try:
                    found.add(str(ipaddress.IPv4Address(line)))
                except ValueError:
                    pass
            return found
        for resolver in ('1.1.1.1', '8.8.8.8'):
            assert addresses(resolver) == expected, resolver
        # Recursive lookup validates the parent delegation, not just zone existence.
        nameservers = command('dig', '@8.8.8.8', ZONE, 'NS', '+short',
                              '+time=3', '+tries=1').splitlines()
        assert nameservers, 'No delegated nameservers'
        assert all((n.endswith('.googledomains.com.') for n in nameservers))
        for server in nameservers:
            assert addresses(server) == expected, server
    eventually(check)


def test_health():
    def check():
        assert request('/api/health')['database'] == 'ok'
    eventually(check)


def test_dashboard_and_datasource():
    dashboard = request('/api/dashboards/uid/assessment-overview')
    assert dashboard['meta']['provisioned']
    assert not dashboard['meta']['canEdit']
    panels = dashboard['dashboard']['panels']
    assert len(panels) == 7
    def query(expression):
        result = request('/api/datasources/proxy/uid/prometheus/api/v1/query?' +
                         urllib.parse.urlencode({'query': expression}))
        assert result['status'] == 'success'
        assert result['data']['result'], expression
        return result['data']['result']
    targets = query('up')
    for job in ('grafana', 'prometheus'):
        matching = [t for t in targets if t['metric'].get('job') == job]
        assert matching, f'Missing scrape target {job}'
        assert all(float(t['value'][1]) == 1 for t in matching), job
    for panel in panels:
        expressions = [t['expr'] for t in panel.get('targets', []) if 'expr' in t]
        assert expressions, panel['title']
        for expression in expressions:
            query(expression)


def test_admin_denied():
    with pytest.raises(urllib.error.HTTPError) as caught:
        request('/api/admin/settings')
    try:
        assert caught.value.code == 403
    finally:
        caught.value.close()


def test_http_redirect():
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(NoRedirect)
    with pytest.raises(urllib.error.HTTPError) as caught:
        opener.open('http://' + HOST + '/', timeout=30)
    try:
        assert caught.value.code == 301
        assert caught.value.headers['Location'] == 'https://' + HOST + '/'
    finally:
        caught.value.close()



@pytest.fixture
def probe_pod():
    # Create a temporary probe pod and delete it after the test, even if it fails.
    # Its active deadline also stops it if the test runner is interrupted.
    name = 'assessment-test-' + uuid.uuid4().hex[:10]
    image = resource('deployment', 'grafana', 'grafana')['spec']['template']['spec']['containers'][0]['image']
    pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name, 'namespace': 'default'},
           'spec': {'automountServiceAccountToken': False, 'restartPolicy': 'Never',
                    'activeDeadlineSeconds': TIMEOUT + 120,
                    'containers': [{'name': 'probe', 'image': image, 'command': ['sleep', str(TIMEOUT + 120)],
                                    'resources': {'requests': {'cpu': '1m', 'memory': '32Mi'},
                                                  'limits': {'memory': '64Mi'}}}]}}
    try:
        subprocess.run(['kubectl', 'create', '-f', '-'], input=json.dumps(pod),
                       text=True, check=True, timeout=30)
        command('kubectl', '-n', 'default', 'wait', '--for=condition=Ready', 'pod/' + name,
                f'--timeout={TIMEOUT}s')
        yield name
    finally:
        subprocess.run(['kubectl', '-n', 'default', 'delete', 'pod', name,
                        '--ignore-not-found', '--wait=false'], check=True, timeout=30)


def test_network_isolation(probe_pod):
    # IPs avoid mistaking a DNS failure for network isolation.
    for namespace, service, port in [('grafana', 'grafana', 3000),
                                     ('monitoring', 'prometheus', 9090)]:
        ip = resource('service', service, namespace)['spec']['clusterIP']
        result = subprocess.run(['kubectl', '-n', 'default', 'exec', probe_pod, '--',
                                 'curl', '--silent', '--show-error', '--max-time', '3',
                                 f'http://{ip}:{port}/'], capture_output=True, text=True, timeout=15)
        assert result.returncode == 28, result.stderr



def test_external_egress_blocked():
    result = subprocess.run(['kubectl', '-n', 'grafana', 'exec', 'deployment/grafana', '--',
                             'curl', '--silent', '--show-error', '--max-time', '3',
                             'http://1.1.1.1/'], capture_output=True, text=True, timeout=15)
    assert result.returncode == 28, result.stderr
