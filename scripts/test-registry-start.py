#!/usr/bin/env python3
"""Registry startup contract; temporary checkout without any sibling repositories."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('docker'), 'Docker Compose required for image resolution')
class RegistryStartTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='registry-start-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / 'scripts').mkdir()
        (self.root / 'bin').mkdir()
        shutil.copy(ROOT / 'scripts/up.sh', self.root / 'scripts/up.sh')
        for source in ROOT.glob('compose*.yaml'):
            shutil.copy(source, self.root / source.name)
        shutil.copy(ROOT / '.env.example', self.root / '.env.example')
        self.executable('scripts/init.sh', '#!/bin/sh\necho init >> "$TRACE"\n')
        self.executable('scripts/bootstrap.sh', '#!/bin/sh\necho "bootstrap $*" >> "$TRACE"\n')
        self.executable('bin/docker', '''#!/bin/sh
echo "$*" >> "$TRACE"
case "$*" in
  'compose version --short') echo "${COMPOSE_VERSION:-2.24.4}" ;;
  *'config --format json')
    if [ "${COMPOSE_JSON+x}" ]; then
      printf '%s' "$COMPOSE_JSON"
      exit "${CONFIG_EXIT:-0}"
    fi
    exec "$REAL_DOCKER" "$@" ;;
  'image inspect '*) [ "$3" != "${MISSING_IMAGE:-}" ] ;;
  'pull '*) echo "${PULL_ERROR:-manifest unknown}" >&2; exit 1 ;;
esac
''')
        self.executable('bin/curl', '#!/bin/sh\nprintf 404\n')
        (self.root / '.env').write_text('GARAGE_DEFAULT_ACCESS_KEY=test\nGARAGE_DEFAULT_SECRET_KEY=test\n'
                                      'GARAGE_BROWSER_ACCESS_KEY=test\nGARAGE_BROWSER_SECRET_KEY=test\n')
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(('DATENPORTAL_', 'GARAGE_', 'COMPOSE_', 'THEMEN_'))}
        self.env.update(PATH=str(self.root / 'bin') + ':' + os.environ['PATH'],
                        REAL_DOCKER=shutil.which('docker'),
                        TRACE=str(self.root / 'trace'))
        for script in ('build-jenkins-local.sh', 'build-sodata-local.sh', 'build-docs-local.sh'):
            self.executable('scripts/' + script, '#!/bin/sh\necho ' + script + ' >> "$TRACE"\n')

    def executable(self, path, content):
        p = self.root / path
        p.write_text(content)
        p.chmod(0o755)

    def start(self, *args, **env):
        result = subprocess.run([str(self.root / 'scripts/up.sh'), '--registry-only', *args],
                                env={**self.env, **env}, capture_output=True, text=True)
        trace = self.root / 'trace'
        return result, trace.read_text() if trace.exists() else ''

    def configuration(self, prefix=None, **env):
        prefix = prefix or ['compose', '-f', 'compose.yaml', '-f', 'compose.registry.yaml']
        result = subprocess.run([self.env['REAL_DOCKER'], *prefix, 'config', '--format', 'json'],
                                cwd=self.root, env={**self.env, **env},
                                capture_output=True, text=True, check=True)
        return json.loads(result.stdout)

    def assert_checked_images_match_started_services(self, trace, **env):
        checks = [line.removeprefix('image inspect ') for line in trace.splitlines()
                  if line.startswith('image inspect ')]
        self.assertEqual(len(checks), 3)
        starts = 0
        for line in trace.splitlines():
            args = shlex.split(line)
            if args and args[0] == 'compose' and 'up' in args:
                starts += 1
                services = self.configuration(args[:args.index('up')], **env)['services']
                self.assertEqual(set(checks), {services[name]['image']
                                              for name in ('dokumentation', 'jenkins', 'sodata')})
        self.assertGreater(starts, 0)

    def test_default_checks_match_started_images(self):
        result, trace = self.start()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_checked_images_match_started_services(trace)

    def test_env_image_overrides_are_preserved(self):
        with (self.root / '.env').open('a') as stream:
            stream.write('DATENPORTAL_JENKINS_IMAGE=jenkins:custom\n'
                         'DATENPORTAL_SODATA_IMAGE=portal:custom\n'
                         'DATENPORTAL_DOCS_IMAGE=docs:custom\n')
        before = (self.root / '.env').read_bytes()
        result, trace = self.start()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_checked_images_match_started_services(trace)
        self.assertEqual((self.root / '.env').read_bytes(), before)

    def test_shell_images_win_over_env_images(self):
        with (self.root / '.env').open('a') as stream:
            stream.write('DATENPORTAL_JENKINS_IMAGE=jenkins:env\n'
                         'DATENPORTAL_SODATA_IMAGE=portal:env\n'
                         'DATENPORTAL_DOCS_IMAGE=docs:env\n')
        overrides = dict(DATENPORTAL_JENKINS_IMAGE='jenkins:shell',
                         DATENPORTAL_SODATA_IMAGE='portal:shell', DATENPORTAL_DOCS_IMAGE='docs:shell')
        result, trace = self.start(**overrides)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_checked_images_match_started_services(trace, **overrides)

    def test_new_env_defaults_match_compose_defaults(self):
        defaults = self.configuration()['services']
        (self.root / '.env').unlink()
        shutil.copy(ROOT / 'scripts/init.sh', self.root / 'scripts/init.sh')
        (self.root / 'services/garage').mkdir(parents=True)
        shutil.copy(ROOT / 'services/garage/garage.toml.template',
                    self.root / 'services/garage/garage.toml.template')
        result, trace = self.start()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_checked_images_match_started_services(trace)
        actual = self.configuration()['services']
        for name in ('jenkins', 'sodata', 'dokumentation'):
            self.assertEqual(actual[name]['image'], defaults[name]['image'])

    def test_invalid_compose_output_aborts_without_exposing_json(self):
        config = self.configuration()
        config['secret-sentinel'] = 'do-not-print-this-secret'
        cases = [('malformed', '{broken'), ('failed-command', json.dumps(config))]
        for name in ('dokumentation', 'jenkins', 'sodata'):
            for value in (None, '', ' ', 42):
                broken = json.loads(json.dumps(config))
                broken['services'][name]['image'] = value
                cases.append((name, json.dumps(broken)))
            broken = json.loads(json.dumps(config))
            del broken['services'][name]['image']
            cases.append((name, json.dumps(broken)))
        for name, output in cases:
            with self.subTest(case=name, output_type=type(output)):
                (self.root / 'trace').unlink(missing_ok=True)
                result, trace = self.start(COMPOSE_JSON=output,
                                          CONFIG_EXIT='7' if name == 'failed-command' else '0')
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('image inspect ', trace)
                self.assertNotIn('pull ', trace)
                self.assertNotIn(' up ', trace)
                self.assertNotIn('do-not-print-this-secret', result.stdout + result.stderr + trace)

    def test_local_build_options_keep_local_images(self):
        result = subprocess.run([str(self.root / 'scripts/up.sh'), '--local-editor',
                                 '--local-jenkins', '--local-sodata', '--local-docs'],
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        trace = (self.root / 'trace').read_text()
        for component in ('jenkins', 'sodata', 'docs'):
            self.assertIn('build-' + component + '-local.sh', trace)
        self.assertNotIn('image inspect ', trace)
        self.assertNotIn('pull ', trace)
        prefix = ['compose', '-f', 'compose.yaml', '-f', 'compose.editor-local.yaml',
                  '-f', 'compose.docs-local.yaml', '-f', 'compose.jenkins-local.yaml',
                  '-f', 'compose.sodata-local.yaml']
        services = self.configuration(prefix)['services']
        for name, image in [('datenblatt-editor', 'datenblatt-editor:local'),
                            ('jenkins', 'datenportal-jenkins:local'),
                            ('sodata', 'datenportal-sodata:local'),
                            ('dokumentation', 'datenportal-dokumentation:local')]:
            self.assertEqual(services[name]['image'], image)

    def test_missing_registry_tags_still_use_local_fallback(self):
        for name, image in [('jenkins', 'sogis/datenportal-jenkins:0.1.0-7'),
                            ('sodata', 'sogis/datenportal-sodata:0.1.20')]:
            with self.subTest(service=name):
                (self.root / 'trace').unlink(missing_ok=True)
                result = subprocess.run([str(self.root / 'scripts/up.sh')],
                                        env={**self.env, 'MISSING_IMAGE': image},
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                trace = (self.root / 'trace').read_text()
                self.assertIn('pull ' + image, trace)
                self.assertIn('-f compose.' + name + '-local.yaml up', trace)

    def test_registry_access_failure_does_not_use_local_fallback(self):
        result = subprocess.run([str(self.root / 'scripts/up.sh')],
                                env={**self.env, 'MISSING_IMAGE': 'sogis/datenportal-sodata:0.1.20',
                                     'PULL_ERROR': 'unauthorized'},
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        trace = (self.root / 'trace').read_text()
        self.assertNotIn(' up ', trace)
        self.assertNotIn('image inspect datenportal-sodata:local', trace)

    def test_every_compose_action_uses_registry_override(self):
        result, trace = self.start()
        self.assertEqual(result.returncode, 0, result.stderr)
        actions = [line for line in trace.splitlines() if line.startswith('compose ') and 'version' not in line]
        self.assertTrue(actions)
        for line in actions:
            self.assertTrue(line.startswith('compose -f compose.yaml -f compose.registry.yaml '), line)
        self.assertNotIn(' build ', trace)
        self.assertIn('bootstrap -f compose.yaml -f compose.registry.yaml', trace)
        self.assertIn('Portal (sodata):', result.stdout)

    def test_all_local_flags_rejected_before_init(self):
        for flag in ('--local-editor', '--local-jenkins', '--local-sodata', '--local-docs'):
            with self.subTest(flag=flag):
                result, trace = self.start(flag)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(trace, '')

    def test_infrastructure_mode_does_not_bootstrap(self):
        result, trace = self.start('--infrastructure-only')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('bootstrap ', trace)
        self.assertIn('Basisdienste bereit', result.stdout)
        self.assertNotIn('Portal (sodata):', result.stdout)

    def test_old_or_unknown_compose_rejected_before_init(self):
        for version in ('2.24.3', '2.23.9', '1.29.2', 'unknown'):
            with self.subTest(version=version):
                result, trace = self.start(COMPOSE_VERSION=version)
                self.assertEqual(result.returncode, 2)
                self.assertNotIn('\ninit\n', '\n' + trace)

    def test_missing_images_abort_without_build_or_container_start(self):
        for image in ('sogis/datenportal-jenkins:0.1.0-7', 'sogis/datenportal-sodata:0.1.20',
                      'sogis/datenportal-dokumentation:0.1.27'):
            with self.subTest(image=image):
                (self.root / 'trace').unlink(missing_ok=True)
                result, trace = self.start(MISSING_IMAGE=image)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('pull ' + image, trace)
                self.assertNotIn(' up ', trace)
                self.assertNotIn(' build ', trace)
                self.assertNotIn('--local-', result.stderr)

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
        self.assertEqual(services['sodata']['image'], 'sogis/datenportal-sodata:0.1.20')


if __name__ == '__main__':
    unittest.main()
