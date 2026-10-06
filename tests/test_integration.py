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



@pytest.fixture(scope='session', autouse=True)
def deployed_revision():
    expected = os.environ.get('EXPECTED_REVISION')
    if not expected:
        return

    def check():
        items = json.loads(command('kubectl', 'get',
                                   'kustomizations.kustomize.toolkit.fluxcd.io',
                                   '-A', '-o', 'json'))['items']
        assert items, 'No Flux Kustomizations found'
        for item in items:
            status = item.get('status', {})
            assert status.get('lastAppliedRevision', '').endswith(':' + expected), item['metadata']['name']
            assert any(c['type'] == 'Ready' and c['status'] == 'True'
                       and c.get('observedGeneration') == item['metadata']['generation']
                       for c in status.get('conditions', [])), item['metadata']['name']
    eventually(check)


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
