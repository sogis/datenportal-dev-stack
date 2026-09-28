#!/usr/bin/env python3
"""Test up.sh docs selection/failure behavior without Docker or stack mutations."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DocsStartTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'scripts').mkdir()
        (self.root / 'bin').mkdir()
        shutil.copy(ROOT / 'scripts/up.sh', self.root / 'scripts/up.sh')
        self.executable('scripts/init.sh', '#!/bin/sh\nexit 0\n')
        self.executable('scripts/build-docs-local.sh', '#!/bin/sh\necho "docs-build $DOCS_REPO_DIR" >> "$TRACE"\nexit "${BUILD_FAIL:-0}"\n')
        self.executable('bin/docker', '''#!/bin/sh
echo "$*" >> "$TRACE"
case "$*" in
  "image inspect "*docs*) exit "${IMAGE_MISSING:-0}" ;;
  "pull "*) exit "${PULL_FAIL:-0}" ;;
esac
exit 0
''')
        self.executable('bin/curl', '#!/bin/sh\nprintf 404\n')
        (self.root / '.env').write_text('DATENPORTAL_DOCS_IMAGE=docs:env\nDOCS_REPO_DIR=env-repo\nGARAGE_BROWSER_ACCESS_KEY=test\nGARAGE_BROWSER_SECRET_KEY=test\n')
        self.env = {**os.environ, 'PATH': str(self.root / 'bin') + ':' + os.environ['PATH'],
                    'TRACE': str(self.root / 'trace')}
        for key in ('DATENPORTAL_DOCS_IMAGE', 'DOCS_REPO_DIR'):
            self.env.pop(key, None)

    def executable(self, path, content):
        p = self.root / path
        p.write_text(content)
        p.chmod(0o755)

    def run_start(self, *args, **env):
        result = subprocess.run([str(self.root / 'scripts/up.sh'), *args], env={**self.env, **env},
                                cwd=self.root, capture_output=True, text=True)
        trace = self.root / 'trace'
        return result, trace.read_text() if trace.exists() else ''

    def test_local_build_and_override_work_without_manifest(self):
        result, trace = self.run_start('--local-docs', DOCS_REPO_DIR='shell-repo')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(trace.startswith('docs-build shell-repo\n'))
        self.assertIn('-f compose.docs-local.yaml up', trace)
        self.assertIn('dokumentation datenblatt-editor', trace)
        self.assertIn('/dokumentation/', result.stdout)
        self.assertNotIn('image inspect docs', trace)

    def test_failed_build_never_starts_containers(self):
        result, trace = self.run_start('--local-docs', BUILD_FAIL='7')
        self.assertEqual(result.returncode, 7)
        self.assertNotIn('docker', trace)
        self.assertNotIn('compose', trace)

    def test_registry_failure_has_no_local_fallback(self):
        result, trace = self.run_start(IMAGE_MISSING='1', PULL_FAIL='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('pull docs:env', trace)
        self.assertNotIn('docs-build', trace)
        self.assertNotIn('compose', trace)
        self.assertIn('--local-docs', result.stderr)

    def test_shell_image_wins_and_cached_image_is_reused(self):
        result, trace = self.run_start(DATENPORTAL_DOCS_IMAGE='docs:shell')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('image inspect docs:shell', trace)
        self.assertNotIn('pull ', trace)
        self.assertNotIn('docs-build', trace)

    def test_conflicting_flags_fail_before_initialization(self):
        result, trace = self.run_start('--local-docs', '--registry-only')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(trace, '')


if __name__ == '__main__':
    unittest.main()
