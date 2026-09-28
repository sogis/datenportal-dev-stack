#!/usr/bin/env python3
"""Read-only HTTP checks for documentation through the running APISIX gateway."""
import argparse
import json
from html.parser import HTMLParser
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key in ('href', 'src') and value:
                self.urls.append(value)


def request(url, method='GET', headers=None):
    try:
        response = build_opener(NoRedirect).open(
            Request(url, method=method, headers=headers or {}), timeout=15)
    except HTTPError as error:
        response = error
    with response:
        return response.code, response.headers, response.read()


def check(base):
    base = base.rstrip('/') + '/dokumentation/'
    status, headers, _ = request(base.rstrip('/') + '?test=1')
    assert status == 308 and headers['Location'] == '/dokumentation/?test=1', (status, dict(headers))
    status, headers, body = request(base)
    assert status == 200 and b'<html' in body.lower(), status
    assert headers.get('Cache-Control') == 'no-cache'
    assert request(base, 'HEAD')[0] == 200
    status, _, index = request(base + 'search-index.json')
    assert status == 200 and json.loads(index)
    assert request(base + 'search/')[0] == 200
    home = Links()
    home.feed(body.decode())
    chapters = []
    checked = set()
    assets = set()

    def check_links(page, links):
        for link in links:
            if link.startswith(('https:', 'http:', '//', 'mailto:', 'data:', '#', 'javascript:')):
                continue
            url = urljoin(page, link).split('#')[0]
            assert url.startswith(base), ('Link escaped documentation prefix', url)
            if url not in checked:
                assert request(url)[0] == 200, url
                checked.add(url)
            if 'site-assets/' in url or urlsplit(url).path.endswith('.svg'):
                assets.add(url)
            elif page == base and url.endswith('/') and url not in (base, base + 'search/'):
                chapters.append(url)

    check_links(base, home.urls)
    assert chapters and assets, 'Missing documentation chapters/assets'
    for chapter in dict.fromkeys(chapters):
        status, _, body = request(chapter)
        assert status == 200
        links = Links()
        links.feed(body.decode())
        check_links(chapter, links.urls)
        status, headers, _ = request(chapter.rstrip('/') + '?test=1', headers={'X-Forwarded-Prefix': '/wrong'})
        assert status == 308 and headers['Location'] == urlsplit(chapter).path + '?test=1', (chapter, status, dict(headers))
    for missing in ('not-a-page', 'not-a-page/', 'site-assets/missing.js'):
        assert request(base + missing)[0] == 404, missing
    print('PASS: documentation through APISIX, chapters, assets, search, HEAD, redirects and 404')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://localhost:8081')
    check(parser.parse_args().base_url)
