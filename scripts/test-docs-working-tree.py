#!/usr/bin/env python3
"""Build an uncommitted docs fixture and verify its image through real APISIX.

Requires Java 25, Docker, Python/PyYAML and a Biblios JAR supporting working-tree
builds. Uses only temporary sources, containers, network and image.
"""
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import uuid
from urllib.error import URLError
from urllib.request import urlopen

STACK = Path(__file__).resolve().parents[1]
DOCS = Path(os.environ.get('DOCS_REPO_DIR', STACK.parent / 'datenportal-dokumentation')).resolve()
SCOPE = 'docs-working-tree-' + uuid.uuid4().hex[:10]


def run(*args, **kwargs):
    return subprocess.check_output(args, text=True, **kwargs).strip()


def main():
    with tempfile.TemporaryDirectory(prefix=SCOPE) as directory:
        root = Path(directory)
        source = root / 'fixture'
        source.mkdir()
        run('git', 'init', '-b', 'main', str(source))
        (source / 'docs').mkdir()
        page = source / 'docs/index.adoc'
        page.write_text('= Fixture\n\nCOMMITTED-CONTENT\n')
        run('git', '-C', str(source), 'add', '.')
        run('git', '-C', str(source), '-c', 'user.name=Docs Test', '-c', 'user.email=docs@example.invalid',
            'commit', '-m', 'Fixture')
        marker = 'UNCOMMITTED-WORKTREE-' + uuid.uuid4().hex
        page.write_text('= Fixture\n\n' + marker + '\n')
        aggregator = root / 'aggregator'
        aggregator.mkdir()
        for item in ('scripts', 'nginx'):
            shutil.copytree(DOCS / item, aggregator / item, ignore=shutil.ignore_patterns('__pycache__'))
        for item in ('Dockerfile', '.dockerignore'):
            shutil.copy(DOCS / item, aggregator / item)
        (aggregator / 'biblios.yml').write_text('''site:
  title: Working tree fixture
output:
  dir: build/site
  clean: true
content:
  sources:
    - id: fixture
      display_name: Fixture
      url: https://example.invalid/fixture.git
      branches:
        - name: main
      start_path: docs
      default_version: main
''')
        env = dict(os.environ)
        if not env.get('PYTHON') and (DOCS / '.venv/bin/python').exists():
            env['PYTHON'] = str(DOCS / '.venv/bin/python')
        env.setdefault('THOTH_REPO_DIR', str(STACK.parent / 'thoth'))
        subprocess.run([str(aggregator / 'scripts/build-local.sh')], env=env, check=True)
        assert run('git', '-C', str(source), 'status', '--porcelain'), 'Fixture should remain uncommitted'
        image = SCOPE + ':test'
        try:
            subprocess.run(['docker', 'build', '-t', image, str(aggregator)], check=True)
            run('docker', 'network', 'create', SCOPE)
            run('docker', 'run', '-d', '--name', SCOPE + '-docs', '--network', SCOPE,
                '--network-alias', 'dokumentation', image)
            run('docker', 'run', '-d', '--name', SCOPE + '-gateway', '--network', SCOPE,
                '-e', 'APISIX_STAND_ALONE=true', '-e', 'APISIX_NODE_LISTEN=8081',
                '-p', '127.0.0.1::8081',
                '-v', str(STACK / 'services/apisix/config.yaml') + ':/usr/local/apisix/conf/config.yaml:ro',
                '-v', str(STACK / 'services/apisix/apisix.yaml') + ':/usr/local/apisix/conf/apisix.yaml:ro',
                'apache/apisix:3.19.0-debian')
            port = run('docker', 'port', SCOPE + '-gateway', '8081/tcp').rsplit(':', 1)[1]
            url = 'http://127.0.0.1:' + port + '/dokumentation/fixture/main/'
            for attempt in range(60):
                try:
                    with urlopen(url, timeout=2) as response:
                        assert marker in response.read().decode(), 'Uncommitted content missing'
                    break
                except (URLError, TimeoutError, socket.timeout, ConnectionError):
                    if attempt == 59:
                        raise
                    time.sleep(1)
            print('PASS: uncommitted temporary source → Thoth working-tree build → image → APISIX')
        finally:
            for name in (SCOPE + '-gateway', SCOPE + '-docs'):
                subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(['docker', 'network', 'rm', SCOPE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(['docker', 'image', 'rm', image], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
