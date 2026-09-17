"""Fault injection gateway used only by test-publication.py's disposable Docker network."""
import http.client
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

class Proxy(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    faults = {}
    def log_message(self, *args):
        pass
    def reply(self, status, body=b'', headers=()):
        # Nur Methode, Objektpfad und Status protokollieren; niemals Signaturen,
        # Credentials oder Lieferinhalte. Damit kann der Test die Reihenfolge belegen.
        with Path('/test/events.jsonl').open('a') as stream:
            stream.write(json.dumps({'method':self.command,'path':self.path,'status':status,
                'contentType':self.headers.get('Content-Type')})+'\n')
        self.send_response(status)
        for key,value in headers: self.send_header(key,value)
        if not any(key.lower() == 'content-length' for key, _ in headers):
            self.send_header('Content-Length', str(len(body)))
        self.send_header('Connection', 'close')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.send_header('Access-Control-Expose-Headers', 'Content-Length, Content-Range, Accept-Ranges')
        self.end_headers()
        if self.command != 'HEAD': self.wfile.write(body)
        self.close_connection = True
    def dispatch(self):
        if self.command=='OPTIONS': return self.reply(204)
        if self.path == '/control':
            if self.command == 'POST':
                Proxy.faults = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            return self.reply(200, json.dumps(Proxy.faults).encode())
        control = Proxy.faults
        if self.path == '/reload':
            if self.headers.get('X-Reload-Token') != 'local-test-token':
                return self.reply(401)
            return self.reply(503 if control.get('reload_failure') else 200, b'{"success":true}')
        public = self.path.startswith('/public/')
        if public and self.path.endswith('/opendata.rdf') and control.get('rdf_readback_unavailable'):
            return self.reply(503)
        if public and self.path.endswith('.parquet') and control.get('missing_parquet'):
            return self.reply(404)
        if self.command == 'PUT' and ((control.get('fail_catalog') and 'published-catalog-' in self.path)
                or (control.get('fail_duckdb') and self.path.endswith('.duckdb'))
                or (control.get('fail_pointer') and self.path.endswith('/current.json'))
                or (control.get('fail_rdf') and self.path.endswith('/opendata.rdf'))):
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
        response_headers=[(k,v) for k,v in response.getheaders() if k.lower() in ('content-encoding','content-type','content-range','accept-ranges') or self.command=='HEAD' and k.lower()=='content-length']
        target.close()
        if control.get('lose_pointer_response') and self.command=='PUT' and self.path.endswith('/current.json'):
            return self.reply(503,b'<Error><Code>ServiceUnavailable</Code></Error>')
        if control.get('lose_rdf_response') and self.command=='PUT' and self.path.endswith('/opendata.rdf'):
            return self.reply(503,b'<Error><Code>ServiceUnavailable</Code></Error>')
        if public and self.path.endswith('/opendata.rdf') and control.get('corrupt_rdf_readback'):
            data = b'<beschadigteUebertragung/>'
        if public and self.path.endswith('.duckdb') and control.get('corrupt_duckdb'):
            data = b'corrupted duckdb transfer'
        if public and self.path.endswith('/current.json') and control.get('legacy_release') and status==200:
            manifest = json.loads(data)
            if manifest['releaseId'] == control['legacy_release']:
                manifest.pop('duckdb', None)
                data = json.dumps(manifest).encode()
        self.reply(status,data,response_headers)
    do_OPTIONS=dispatch
    do_GET=dispatch
    do_HEAD=dispatch
    do_POST=dispatch
    do_PUT=dispatch

ThreadingHTTPServer(('0.0.0.0',8000),Proxy).serve_forever()
