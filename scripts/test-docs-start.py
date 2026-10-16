#!/usr/bin/env python3
"""Documentation startup is explicitly disabled on the AWS portal branch."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DocsStartTest(unittest.TestCase):
    def test_local_docs_reports_inactive_branch_option(self):
        result = subprocess.run([str(ROOT / 'scripts/up.sh'), '--local-docs'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('im Branch s3-aws deaktiviert', result.stderr)


if __name__ == '__main__':
    unittest.main()
