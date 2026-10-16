#!/usr/bin/env python3
"""AWS portal startup contract; isolated checkout, real Compose, mocked Docker actions."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('docker'), 'Docker Compose required')
class RegistryStartTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='aws-start-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / 'scripts').mkdir()
        (self.root / 'bin').mkdir()
        for name in ('up.sh', 'down.sh', 'build-sodata-local.sh'):
            shutil.copy(ROOT / 'scripts' / name, self.root / 'scripts' / name)
        for source in ROOT.glob('compose*.yaml'):
            shutil.copy(source, self.root / source.name)
        self.executable('bin/docker', '''#!/bin/sh
echo "$*" >> "$TRACE"
case "$*" in
  *'config --format json')
    if [ "${BROKEN_CONFIG:-0}" = 1 ]; then
      printf '{broken secret-sentinel'
      exit 0
    fi
    exec "$REAL_DOCKER" "$@" ;;
  *'config --quiet') exec "$REAL_DOCKER" "$@" ;;
  *'pull '*) exit "${PULL_FAIL:-0}" ;;
  *'build sodata') exit "${BUILD_FAIL:-0}" ;;
esac
''')
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(('DATENPORTAL_', 'GARAGE_', 'COMPOSE_', 'SODATA_', 'AWS_'))}
        self.env.update(PATH=str(self.root / 'bin') + ':' + os.environ['PATH'],
                        REAL_DOCKER=shutil.which('docker'), TRACE=str(self.root / 'trace'))

    def executable(self, path, content):
        target = self.root / path
        target.write_text(content)
        target.chmod(0o755)

    def run_script(self, name='up.sh', args=(), **env):
        result = subprocess.run([str(self.root / 'scripts' / name), *args],
                                cwd=self.root, env={**self.env, **env}, capture_output=True, text=True)
        trace = self.root / 'trace'
        return result, trace.read_text() if trace.exists() else ''

    def configuration(self, files=(), **env):
        command = [self.env['REAL_DOCKER'], 'compose', '-f', 'compose.yaml']
        for name in files:
            command += ['-f', name]
        result = subprocess.run(command + ['config', '--format', 'json'], cwd=self.root,
                                env={**self.env, **env}, capture_output=True, text=True, check=True)
        return json.loads(result.stdout)

    def test_fresh_checkout_without_credentials_or_siblings(self):
        services = self.configuration()['services']
        self.assertEqual(set(services), {'sodata', 'downloads'})
        self.assertNotIn('depends_on', services['sodata'])
        self.assertNotIn('ports', services['sodata'])
        self.assertNotIn('network_mode', services['downloads'])
        self.assertEqual(set(services['downloads']['depends_on']), {'sodata'})
        self.assertEqual(services['downloads']['ports'][0]['published'], '8081')
        self.assertEqual(services['sodata']['image'], 'sogis/datenportal-sodata:0.1.20')
        env = services['sodata']['environment']
        self.assertEqual(env['DATENPORTAL_CATALOG_SOURCE_TYPE'], 'manifest')
        self.assertEqual(env['DATENPORTAL_CATALOG_DUCKDB_SOURCE_TYPE'], 'manifest')
        self.assertEqual(env['DATENPORTAL_CATALOG_HTTP_URL'], 'https://s3.eu-central-1.amazonaws.com/ch.so.daten-test/current.json')
        self.assertEqual(env['DATENPORTAL_CATALOG_DOWNLOAD_URL'], 'https://s3.eu-central-1.amazonaws.com/ch.so.daten-test')
        for service in services.values():
            self.assertNotIn('build', service)
            for mount in service.get('volumes', []):
                if mount['type'] == 'bind':
                    self.assertTrue(Path(mount['source']).is_relative_to(self.root))
            self.assertFalse(any(key.startswith(('AWS_', 'GARAGE_')) for key in service.get('environment', {})))

    def test_default_and_registry_alias_start_only_two_services(self):
        for args in ((), ('--registry-only',)):
            with self.subTest(args=args):
                (self.root / 'trace').unlink(missing_ok=True)
                result, trace = self.run_script(args=args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('pull --policy missing sodata downloads', trace)
                self.assertIn('up -d --remove-orphans --wait --wait-timeout 120', trace)
                self.assertNotIn(' build ', trace)
                self.assertNotIn('compose.registry.yaml', trace)
                self.assertIn('http://localhost:8081/', result.stdout)
                self.assertFalse((self.root / '.env').exists())
                self.assertFalse((self.root / 'services/garage/garage.toml').exists())

    def test_env_defaults_match_compose_and_file_is_preserved(self):
        defaults = self.configuration()
        shutil.copy(ROOT / '.env.example', self.root / '.env')
        before = (self.root / '.env').read_bytes()
        self.assertEqual(self.configuration(), defaults)
        result, _ = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / '.env').read_bytes(), before)

    def test_shell_overrides_win_over_existing_env(self):
        (self.root / '.env').write_text('DATENPORTAL_SODATA_IMAGE=portal:env\nGARAGE_PUBLIC_PORT=18081\n'
                                      'DATENPORTAL_CATALOG_HTTP_URL=https://env.invalid/current.json\n'
                                      'DATENPORTAL_CATALOG_DOWNLOAD_URL=https://env.invalid/bucket\n'
                                      'DATENPORTAL_PORTAL_RELOAD_TOKEN=secret-sentinel\n')
        overrides = dict(DATENPORTAL_SODATA_IMAGE='portal:shell', GARAGE_PUBLIC_PORT='18082',
                         DATENPORTAL_CATALOG_HTTP_URL='https://shell.invalid/current.json',
                         DATENPORTAL_CATALOG_DOWNLOAD_URL='https://shell.invalid/bucket')
        config = self.configuration(**overrides)['services']
        self.assertEqual(config['sodata']['image'], 'portal:shell')
        for key in ('DATENPORTAL_CATALOG_HTTP_URL', 'DATENPORTAL_CATALOG_DOWNLOAD_URL'):
            self.assertEqual(config['sodata']['environment'][key], overrides[key])
        result, trace = self.run_script(**overrides)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('http://localhost:18082/', result.stdout)
        self.assertNotIn('secret-sentinel', result.stdout + result.stderr + trace)

    def test_pull_failure_never_builds_or_starts(self):
        result, trace = self.run_script(PULL_FAIL='7')
        self.assertEqual(result.returncode, 7)
        self.assertNotIn(' up ', trace)
        self.assertNotIn(' build ', trace)

    def test_invalid_configuration_does_not_start_or_print_contents(self):
        result, trace = self.run_script(BROKEN_CONFIG='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('secret-sentinel', result.stdout + result.stderr)
        self.assertNotIn('pull ', trace)
        self.assertNotIn(' up ', trace)

    def local_repo(self):
        (self.root / 'portal-source').mkdir()
        (self.root / 'portal-source/Dockerfile').write_text('FROM scratch\n')
        (self.root / '.env').write_text('SODATA_REPO_DIR=./portal-source\n')

    def test_local_build_uses_component_dockerfile_and_override(self):
        self.local_repo()
        result, trace = self.run_script(args=('--local-sodata',))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('-f compose.sodata-local.yaml build sodata', trace)
        self.assertIn('-f compose.sodata-local.yaml pull --policy missing downloads', trace)
        self.assertIn('-f compose.sodata-local.yaml up ', trace)
        self.assertNotIn('pull --policy missing sodata', trace)
        portal = self.configuration(files=('compose.sodata-local.yaml',))['services']['sodata']
        self.assertEqual(portal['image'], 'datenportal-sodata:local')
        self.assertEqual(portal['build']['context'], str(self.root / 'portal-source'))
        self.assertEqual(portal['build']['dockerfile'], 'Dockerfile')

    def test_failed_local_build_never_starts(self):
        self.local_repo()
        result, trace = self.run_script(args=('--local-sodata',), BUILD_FAIL='9')
        self.assertEqual(result.returncode, 9)
        self.assertNotIn(' up ', trace)

    def test_missing_sibling_fails_with_clear_message(self):
        result, trace = self.run_script(args=('--local-sodata',), SODATA_REPO_DIR='./missing')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Sodata-Repository nicht gefunden', result.stderr)
        self.assertNotIn(' build ', trace)
        self.assertNotIn(' up ', trace)

    def test_inactive_and_conflicting_options_fail_before_docker(self):
        for args in (('--local-editor',), ('--local-jenkins',), ('--local-docs',),
                     ('--infrastructure-only',), ('--unknown',), ('--registry-only', '--local-sodata')):
            with self.subTest(args=args):
                result, trace = self.run_script(args=args)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(trace, '')

    def test_inactive_overrides_do_not_resurrect_services(self):
        config = self.configuration(files=('compose.registry.yaml', 'compose.editor-local.yaml',
                                          'compose.jenkins-local.yaml', 'compose.docs-local.yaml'))
        self.assertEqual(set(config['services']), {'sodata', 'downloads'})

    def test_down_keeps_volumes_and_removes_obsolete_containers(self):
        result, trace = self.run_script(name='down.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(trace.strip(), 'compose down --remove-orphans')


if __name__ == '__main__':
    unittest.main()
