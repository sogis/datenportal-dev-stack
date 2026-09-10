"""Fault injection gateway used only by test-publication.py's disposable Docker network."""
import http.client
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

class Proxy(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *args):
        pass
    def reply(self, status, body=b'', headers=()):
        self.send_response(status)
        for key,value in headers: self.send_header(key,value)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True
    def dispatch(self):
        control = json.loads(Path('/test/control.json').read_text())
        if self.path == '/reload':
            if self.headers.get('X-Reload-Token') != 'local-test-token':
                return self.reply(401)
            return self.reply(503 if control.get('reload_failure') else 200, b'{"success":true}')
        public = self.path.startswith('/public/')
        if self.command == 'PUT' and ((control.get('fail_catalog') and 'published-catalog-' in self.path)
                or (control.get('fail_pointer') and self.path.endswith('/current.json'))):
            return self.reply(503, b'<Error><Code>ServiceUnavailable</Code></Error>')
        if self.headers.get('Transfer-Encoding', '').lower() == 'chunked':
            chunks = []
            while True:
                count = int(self.rfile.readline().split(b';')[0], 16)
                if count == 0:
                    while self.rfile.readline().strip():
                        pass
                    break
                chunks.append(self.rfile.read(count)); self.rfile.read(2)
            body = b''.join(chunks)
        else:
            body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
        headers = {k:v for k,v in self.headers.items() if k.lower() not in ('connection','transfer-encoding','expect')}
        headers['Content-Length'] = str(len(body))
        target = http.client.HTTPConnection('browser' if public else 'garage', 8080 if public else 3900, timeout=30)
        path = self.path[len('/public'):] if public else self.path
        if public:
            headers['Host']='browser:8080'
        target.request(self.command, path, body, headers)
        response=target.getresponse()
        data=response.read()
        status=response.status
        response_headers=[(k,v) for k,v in response.getheaders() if k.lower() in ('content-encoding','content-type')]
        target.close()
        if control.get('lose_pointer_response') and self.command=='PUT' and self.path.endswith('/current.json'):
            return self.reply(503,b'<Error><Code>ServiceUnavailable</Code></Error>')
        self.reply(status,data,response_headers)
    do_GET=dispatch
    do_HEAD=dispatch
    do_POST=dispatch
    do_PUT=dispatch

ThreadingHTTPServer(('0.0.0.0',8000),Proxy).serve_forever()
