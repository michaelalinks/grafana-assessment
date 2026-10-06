#!/usr/bin/env python3
"""Live integration checks; uses current kubectl context, no administrator credentials."""
import ipaddress
import json
import os
import subprocess
import time
import unittest
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


class Integration(unittest.TestCase):
    def test_reconciliation(self):
        for kind in ('kustomizations.kustomize.toolkit.fluxcd.io',
                     'helmreleases.helm.toolkit.fluxcd.io'):
            items = json.loads(command('kubectl', 'get', kind, '-A', '-o', 'json'))['items']
            self.assertTrue(items, f'No {kind} found')
            for item in items:
                command('kubectl', '-n', item['metadata']['namespace'], 'wait',
                        '--for=condition=Ready', kind + '/' + item['metadata']['name'],
                        f'--timeout={TIMEOUT}s')
        for namespace, name in [('grafana', 'grafana'), ('monitoring', 'prometheus')]:
            command('kubectl', '-n', namespace, 'rollout', 'status', 'deployment/' + name,
                    f'--timeout={TIMEOUT}s')

    def test_dns(self):
        def check():
            gateway = resource('gateway', 'public', 'envoy-gateway-system')
            expected = {a['value'] for a in gateway.get('status', {}).get('addresses', [])
                        if a.get('type', 'IPAddress') == 'IPAddress'}
            self.assertTrue(expected, 'Gateway has no assigned IP')
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
                self.assertEqual(addresses(resolver), expected, resolver)
            # Recursive lookup validates the parent delegation, not just zone existence.
            nameservers = command('dig', '@8.8.8.8', ZONE, 'NS', '+short',
                                  '+time=3', '+tries=1').splitlines()
            self.assertTrue(nameservers, 'No delegated nameservers')
            self.assertTrue(all(n.endswith('.googledomains.com.') for n in nameservers))
            for server in nameservers:
                self.assertEqual(addresses(server), expected, server)
        eventually(check)

    def test_health(self):
        eventually(lambda: self.assertEqual(request('/api/health')['database'], 'ok'))

    def test_dashboard_and_datasource(self):
        dashboard = request('/api/dashboards/uid/assessment-overview')
        self.assertTrue(dashboard['meta']['provisioned'])
        self.assertFalse(dashboard['meta']['canEdit'])
        panels = dashboard['dashboard']['panels']
        self.assertEqual(len(panels), 7)
        def query(expression):
            result = request('/api/datasources/proxy/uid/prometheus/api/v1/query?' +
                             urllib.parse.urlencode({'query': expression}))
            self.assertEqual(result['status'], 'success')
            self.assertTrue(result['data']['result'], expression)
            return result['data']['result']
        targets = query('up')
        for job in ('grafana', 'prometheus'):
            matching = [t for t in targets if t['metric'].get('job') == job]
            self.assertTrue(matching, f'Missing scrape target {job}')
            self.assertTrue(all(float(t['value'][1]) == 1 for t in matching), job)
        for panel in panels:
            expressions = [t['expr'] for t in panel.get('targets', []) if 'expr' in t]
            self.assertTrue(expressions, panel['title'])
            for expression in expressions:
                with self.subTest(panel=panel['title']):
                    query(expression)

    def test_admin_denied(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            request('/api/admin/settings')
        self.assertEqual(caught.exception.code, 403)
        caught.exception.close()

    def test_http_redirect(self):
        output = command('curl', '--silent', '--show-error', '--max-time', '30',
                         '--output', '/dev/null', '--write-out', '%{http_code}\n%{redirect_url}',
                         'http://' + HOST + '/')
        self.assertEqual(output.splitlines(), ['301', 'https://' + HOST + '/'])

    def test_network_isolation(self):
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
            # IPs avoid mistaking a DNS failure for network isolation.
            for namespace, service, port in [('grafana', 'grafana', 3000),
                                              ('monitoring', 'prometheus', 9090)]:
                ip = resource('service', service, namespace)['spec']['clusterIP']
                result = subprocess.run(['kubectl', '-n', 'default', 'exec', name, '--',
                                         'curl', '--silent', '--show-error', '--max-time', '3',
                                         f'http://{ip}:{port}/'], capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 28, result.stderr)
        finally:
            subprocess.run(['kubectl', '-n', 'default', 'delete', 'pod', name,
                            '--ignore-not-found', '--wait=false'], check=True, timeout=30)

    def test_external_egress_blocked(self):
        result = subprocess.run(['kubectl', '-n', 'grafana', 'exec', 'deployment/grafana', '--',
                                 'curl', '--silent', '--show-error', '--max-time', '3',
                                 'http://1.1.1.1/'], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 28, result.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
