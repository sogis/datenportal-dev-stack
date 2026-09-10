#!/usr/bin/env python3
"""Exercise the portal's existing local bootRun contract against a temporary HTTP source."""
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import secrets
import signal
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
import urllib.error

PORTAL = Path(__file__).resolve().parents[2] / 'datenportal-sodata'
WORK = Path(tempfile.mkdtemp(prefix='datenportal-portal-manifest-'))
manifest = {'schemaVersion': 1, 'releaseId': 'integration',
            'datasheets': 'datasheets-integration.xtf', 'catalog': None}
reads = 0
catalog = (PORTAL / 'spec/fixtures/published_catalog_full_62_entries.xtf').read_bytes()

class Source(BaseHTTPRequestHandler):
    def do_GET(self):
        global reads
        if self.path == '/current.json':
            reads += 1
            body = json.dumps(manifest).encode()
        elif self.path == '/published-catalog-integration.xtf':
            body = catalog
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args): pass

source = ThreadingHTTPServer(('127.0.0.1', 0), Source)
threading.Thread(target=source.serve_forever, daemon=True).start()
with socket.socket() as sock:
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
token = secrets.token_hex(24)
env = dict(os.environ, SPRING_PROFILES_ACTIVE='local', DATENPORTAL_ADMIN_RELOAD_TOKEN=token)
arguments = [f'--server.port={port}', '--datenportal.catalog.source-type=manifest',
             f'--datenportal.catalog.http-url=http://127.0.0.1:{source.server_port}/current.json']
log = (WORK / 'portal.log').open('w')
process = subprocess.Popen(['./gradlew', 'bootRun', '--args=' + ' '.join(arguments)], cwd=PORTAL,
                           env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)

def request(path, method='GET', authorized=True):
    headers = {'X-Reload-Token': token} if authorized else {}
    req = urllib.request.Request(f'http://127.0.0.1:{port}' + path, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=40) as response: return response.status, response.read()
    except urllib.error.HTTPError as error: return error.code, error.read()

try:
    print('Integration artifacts:', WORK, flush=True)
    for _ in range(180):
        if process.poll() is not None: raise AssertionError('Portal stopped; see ' + str(WORK / 'portal.log'))
        try:
            if request('/actuator/health')[0] == 200: break
        except OSError: pass
        time.sleep(1)
    else: raise AssertionError('Portal startup timeout')
    assert reads == 1
    assert json.loads(request('/admin/catalog/status')[1])['visibleEntries'] == 0
    assert request('/catalog/published-catalog.xtf')[0] == 404
    assert request('/')[0] == 200
    manifest['catalog'] = 'published-catalog-integration.xtf'
    assert json.loads(request('/admin/catalog/reload', 'POST')[1])['success'] is True
    assert reads == 2
    assert json.loads(request('/admin/catalog/status')[1])['visibleEntries'] > 0
    accepted = request('/catalog/published-catalog.xtf')
    assert accepted[0] == 200
    manifest = {'schemaVersion': 99}
    assert json.loads(request('/admin/catalog/reload', 'POST')[1])['success'] is False
    assert reads == 3 and request('/catalog/published-catalog.xtf') == accepted
    assert request('/admin/catalog/reload', 'POST', authorized=False)[0] == 401
    print('PASS: empty initial view, manifest reload, failed reload retains snapshot, protected endpoint', flush=True)
finally:
    os.killpg(process.pid, signal.SIGTERM)
    try: process.wait(timeout=20)
    except subprocess.TimeoutExpired: os.killpg(process.pid, signal.SIGKILL)
    source.shutdown()
    log.close()
