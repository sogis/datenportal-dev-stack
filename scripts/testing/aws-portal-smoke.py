#!/usr/bin/env python3
"""Read-only checks of the active portal, gateway and public AWS publication."""
import json
from html.parser import HTMLParser
from pathlib import Path
import runpy
import subprocess
import sys
from urllib.error import HTTPError
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
validate = runpy.run_path(str(ROOT / 'scripts/testing/check-publication-manifest.py'))['validate']


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class Links(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.urls = []
        self.feed(html.decode())

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.urls.extend(value for key, value in attrs if key == 'href' and value)


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def request(url, status=200, method='GET', headers=None, limit=None):
    require(method in ('GET', 'HEAD'), 'Smoke checks must remain read-only')
    try:
        response = build_opener(NoRedirect).open(
            Request(url, method=method, headers=headers or {}), timeout=30)
    except HTTPError as error:
        response = error
    with response:
        require(response.status == status, f'{method} {urlsplit(url).path}: HTTP {response.status}, expected {status}')
        return response.headers, response.read() if limit is None else response.read(limit)


def check():
    configuration = subprocess.run(
        ['docker', 'compose', 'config', '--format', 'json'], cwd=ROOT,
        capture_output=True, check=True, text=True)
    services = json.loads(configuration.stdout)['services']
    require(set(services) == {'sodata', 'downloads'}, 'Expected only Sodata and APISIX')
    port = services['downloads']['ports'][0]['published']
    base = f'http://localhost:{port}'
    env = services['sodata']['environment']
    manifest_url = env['DATENPORTAL_CATALOG_HTTP_URL']
    download_base = env['DATENPORTAL_CATALOG_DOWNLOAD_URL'].rstrip('/')
    _, body = request(manifest_url)
    manifest = validate(json.loads(body))
    require(manifest['catalog'] is not None, 'AWS acceptance requires a published catalog')
    _, catalog = request(urljoin(manifest_url, manifest['catalog']))
    _, duckdb = request(urljoin(manifest_url, manifest['duckdb']))
    request(urljoin(manifest_url, manifest['datasheets']), method='HEAD')

    _, active_catalog = request(base + '/catalog/published-catalog.xtf')
    _, active_duckdb = request(base + '/catalog/catalog.duckdb')
    expected_catalog = catalog.decode().replace('${DOWNLOAD_URL}', download_base)
    require(active_catalog.decode() == expected_catalog, 'Portal XTF differs from AWS publication; restart/reload and retry')
    require(active_duckdb == duckdb, 'Portal DuckDB differs from AWS publication; restart/reload and retry')

    request(base + '/gateway-health')
    headers, home = request(base + '/')
    require(urlsplit(download_base).netloc in headers.get('Content-Security-Policy', ''),
            'AWS origin missing from Content-Security-Policy')
    links = Links(home).urls
    detail = next((p for p in links if p.startswith('/datasets/') and p.count('/') == 2), None)
    require(detail, 'No dataset detail link on portal start page')
    request(base + detail)
    _, search = request(base + '/datasets?' + urlencode({'q': detail.rsplit('/', 1)[-1]}))
    require(detail in Links(search).urls, 'Identifier search did not find the selected AWS dataset')
    request(base + detail + '/explore')
    _, context_body = request(base + detail + '/explore/context.json')
    context = json.loads(context_body)
    require(context.get('tables'), 'Explore context has no tables')
    parquet = context['tables'][0]['parquetUrl']
    require(parquet.startswith(download_base + '/'), 'Explore Parquet does not use configured AWS bucket')
    range_headers, prefix = request(parquet, status=206, headers={
        'Origin': base, 'Range': 'bytes=0-3'}, limit=4)
    require(prefix == b'PAR1', 'Downloaded object is not Parquet')
    require(range_headers.get('Access-Control-Allow-Origin') in ('*', base), 'Missing CORS for portal origin')
    require(range_headers.get('Content-Range', '').startswith('bytes 0-3/'), 'Missing byte-range response')
    require('content-range' in range_headers.get('Access-Control-Expose-Headers', '').lower(),
            'Content-Range must be exposed to the browser')

    urls = {(node.text or '').strip() for node in ET.fromstring(expected_catalog).iter()}
    for extension in ('.csv', '.xlsx'):
        target = next((url for url in sorted(urls) if url.startswith(download_base + '/')
                       and url.lower().endswith(extension)), None)
        require(target, 'Missing AWS distribution: ' + extension)
        request(target, method='HEAD')

    for path in ('/admin', '/admin/catalog/status', '/admin/catalog/reload',
                 '/actuator', '/actuator/health', '/apisix/admin', '/apisix/admin/routes'):
        for method in ('GET', 'HEAD'):
            request(base + path, status=403, method=method)
    for path in ('/jenkins/', '/anlieferung', '/datenblatt-editor/', '/dokumentation/', '/ch.so.daten/'):
        request(base + path, status=404)
    _, latest = request(manifest_url)
    require(json.loads(latest) == manifest, 'AWS release changed during smoke test; restart/reload and retry')
    print('PASS: AWS release ' + manifest['releaseId'])
    print('PASS: portal, search, detail, Explore context, XTF/DuckDB equality, CSV/XLSX/Parquet, CORS/Range, gateway restrictions')
    print('Only GET/HEAD requests; browser SQL execution is a separate acceptance check.')


if __name__ == '__main__':
    try:
        check()
    except (AssertionError, OSError, ValueError, KeyError, IndexError, subprocess.CalledProcessError) as error:
        if isinstance(error, subprocess.CalledProcessError):
            sys.exit('FAIL: Could not resolve Compose configuration (details withheld to protect local secrets).')
        sys.exit('FAIL: ' + str(error))
