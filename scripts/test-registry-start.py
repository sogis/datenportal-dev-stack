#!/usr/bin/env python3
"""Registry startup contract; temporary checkout without any sibling repositories."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RegistryStartTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='registry-start-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / 'scripts').mkdir()
        (self.root / 'bin').mkdir()
        shutil.copy(ROOT / 'scripts/up.sh', self.root / 'scripts/up.sh')
        self.executable('scripts/init.sh', '#!/bin/sh\necho init >> "$TRACE"\n')
        self.executable('bin/docker', '''#!/bin/sh
echo "$*" >> "$TRACE"
case "$*" in
  'compose version --short') echo "${COMPOSE_VERSION:-2.24.4}" ;;
  'image inspect '*) [ "$3" != "${MISSING_IMAGE:-}" ] ;;
  'pull '*) echo 'manifest unknown' >&2; exit 1 ;;
esac
''')
        self.executable('bin/curl', '#!/bin/sh\nprintf 404\n')
        (self.root / '.env').write_text('GARAGE_BROWSER_ACCESS_KEY=test\nGARAGE_BROWSER_SECRET_KEY=test\n')
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(('DATENPORTAL_', 'GARAGE_', 'COMPOSE_', 'THEMEN_'))}
        self.env.update(PATH=str(self.root / 'bin') + ':' + os.environ['PATH'],
                        TRACE=str(self.root / 'trace'))

    def executable(self, path, content):
        p = self.root / path
        p.write_text(content)
        p.chmod(0o755)

    def start(self, *args, **env):
        result = subprocess.run([str(self.root / 'scripts/up.sh'), '--registry-only', *args],
                                env={**self.env, **env}, capture_output=True, text=True)
        trace = self.root / 'trace'
        return result, trace.read_text() if trace.exists() else ''

    def test_every_compose_action_uses_registry_override(self):
        result, trace = self.start()
        self.assertEqual(result.returncode, 0, result.stderr)
        actions = [line for line in trace.splitlines() if line.startswith('compose ') and 'version' not in line]
        self.assertTrue(actions)
        for line in actions:
            self.assertTrue(line.startswith('compose -f compose.yaml -f compose.registry.yaml '), line)
        self.assertNotIn(' build ', trace)
        self.assertIn('docker compose -f compose.yaml -f compose.registry.yaml up', result.stdout)

    def test_all_local_flags_rejected_before_init(self):
        for flag in ('--local-editor', '--local-jenkins', '--local-sodata', '--local-docs'):
            with self.subTest(flag=flag):
                result, trace = self.start(flag)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(trace, '')

    def test_old_or_unknown_compose_rejected_before_init(self):
        for version in ('2.24.3', '2.23.9', '1.29.2', 'unknown'):
            with self.subTest(version=version):
                result, trace = self.start(COMPOSE_VERSION=version)
                self.assertEqual(result.returncode, 2)
                self.assertNotIn('\ninit\n', '\n' + trace)

    def test_missing_images_abort_without_build_or_container_start(self):
        for image in ('sogis/datenportal-jenkins:0.1.0-3', 'sogis/datenportal-sodata:0.1.10',
                      'sogis/datenportal-dokumentation:0.1.18'):
            with self.subTest(image=image):
                (self.root / 'trace').unlink(missing_ok=True)
                result, trace = self.start(MISSING_IMAGE=image)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('pull ' + image, trace)
                self.assertNotIn(' up ', trace)
                self.assertNotIn(' build ', trace)
                self.assertNotIn('--local-', result.stderr)

    @unittest.skipUnless(shutil.which('docker'), 'Docker Compose required for configuration validation')
    def test_real_merged_configuration_has_no_external_mounts_or_builds(self):
        for filename in ('compose.yaml', 'compose.registry.yaml'):
            shutil.copy(ROOT / filename, self.root / filename)
        env = {**self.env, 'PATH': os.environ['PATH'],
               'GARAGE_DEFAULT_ACCESS_KEY': 'test', 'GARAGE_DEFAULT_SECRET_KEY': 'test',
               'GARAGE_BROWSER_ACCESS_KEY': 'test', 'GARAGE_BROWSER_SECRET_KEY': 'test'}
        result = subprocess.run(['docker', 'compose', '-f', 'compose.yaml', '-f', 'compose.registry.yaml',
                                 'config', '--format', 'json'], cwd=self.root, env=env,
                                capture_output=True, text=True, check=True)
        services = json.loads(result.stdout)['services']
        for service in services.values():
            self.assertNotIn('build', service)
            self.assertRegex(service['image'], r':[0-9v][0-9.\w-]*$')
            for mount in service.get('volumes', []):
                if mount['type'] == 'bind':
                    self.assertTrue(Path(mount['source']).is_relative_to(self.root), mount['source'])
        jenkins = services['jenkins']
        self.assertEqual(len(jenkins['volumes']), 2)
        self.assertEqual(jenkins['environment']['THEMEN_REPO_URL'], 'https://github.com/sogis/datenportal-themenrepo.git')
        self.assertEqual(jenkins['environment']['THEMEN_REPO_MODE'], 'managed-git')
        self.assertEqual(jenkins['environment']['THEMEN_REPO_PATH'], '')
        self.assertEqual(jenkins['environment']['ORG_GRADLE_PROJECT_gitWriteBack'], 'false')
        self.assertEqual(services['sodata']['image'], 'sogis/datenportal-sodata:0.1.10')


if __name__ == '__main__':
    unittest.main()
