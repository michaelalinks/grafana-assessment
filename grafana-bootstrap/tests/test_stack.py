"""Integration tests for the portable installation; no administrator password needed."""
import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest

TIMEOUT = int(os.environ.get('TEST_TIMEOUT', '300'))


def command(*args):
    return subprocess.check_output(args, text=True, timeout=TIMEOUT + 30).strip()


def eventually(check, timeout=TIMEOUT):
    deadline = time.monotonic() + timeout
    while True:
        try:
            return check()
        except (AssertionError, urllib.error.URLError) as error:
            if time.monotonic() >= deadline:
                raise AssertionError(f'Timed out waiting: {error}') from error
            time.sleep(3)


@pytest.fixture(scope='session')
def grafana():
    # Open a loopback-only port-forward for the tests and close it even if a test fails.
    for app in ('grafana', 'prometheus', 'loki', 'alloy'):
        command('kubectl', '-n', 'monitoring', 'rollout', 'status',
                'deployment/' + app, f'--timeout={TIMEOUT}s')
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    process = subprocess.Popen(['kubectl', '-n', 'monitoring', 'port-forward',
                                '--address=127.0.0.1', 'service/grafana', f'{port}:3000'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    def request(path):
        assert process.poll() is None, 'kubectl port-forward exited unexpectedly'
        with urllib.request.urlopen(f'http://127.0.0.1:{port}' + path, timeout=15) as response:
            return json.load(response)
    try:
        eventually(lambda: request('/api/health'), timeout=30)
        yield request
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def test_health(grafana):
    assert grafana('/api/health')['database'] == 'ok'


def test_dashboard_and_metrics(grafana):
    dashboard = grafana('/api/dashboards/uid/assessment-overview')
    assert dashboard['meta']['provisioned']
    assert not dashboard['meta']['canEdit']
    panels = dashboard['dashboard']['panels']
    assert len(panels) == 8
    def query(expression):
        result = grafana('/api/datasources/proxy/uid/prometheus/api/v1/query?' +
                         urllib.parse.urlencode({'query': expression}))
        assert result['status'] == 'success'
        assert result['data']['result'], expression
        return result['data']['result']
    def check():
        targets = query('up')
        for app in ('grafana', 'prometheus'):
            matching = [t for t in targets if t['metric'].get('job') == app]
            assert matching and all(float(t['value'][1]) == 1 for t in matching), app
        for panel in panels:
            if panel['datasource']['uid'] == 'prometheus':
                for target in panel['targets']:
                    query(target['expr'])
    eventually(check)


def test_collected_logs(grafana):
    def check():
        for app in ('grafana', 'prometheus'):
            query = urllib.parse.urlencode({'query': '{app="' + app + '"}', 'limit': 1})
            result = grafana('/api/datasources/proxy/uid/loki/loki/api/v1/query_range?' + query)
            assert result['status'] == 'success'
            assert any(stream['values'] for stream in result['data']['result']), app
    eventually(check)


def test_anonymous_admin_denied(grafana):
    with pytest.raises(urllib.error.HTTPError) as caught:
        grafana('/api/admin/settings')
    try:
        assert caught.value.code == 403
    finally:
        caught.value.close()


def test_services_are_internal(grafana):
    for app in ('grafana', 'prometheus', 'loki'):
        service = json.loads(command('kubectl', '-n', 'monitoring', 'get', 'service', app, '-o', 'json'))
        assert service['spec']['type'] == 'ClusterIP', app
        assert not service['spec'].get('externalIPs'), app
