#!/usr/bin/env python3
"""Behavior tests for orchestration, including preserved state after interruptions."""
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bootstrap", ROOT / "scripts/bootstrap.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
Error = module.BootstrapError
MANIFEST = {"schemaVersion": 1, "releaseId": "first", "datasheets": "datasheets-first.xtf",
            "catalog": None, "duckdb": "catalog-first.duckdb"}


class Fixture(module.Bootstrap):
    def __init__(self, root, manifest=None, status=200, check_only=False):
        self.deadline = time.monotonic() + 5
        self.compose = ["docker", "compose", "-f", "compose.yaml"]
        self.runtime = root
        self.receipt = root / "bootstrap.json"
        self.state = {}
        self.check_only = check_only
        self.public_base = "http://localhost:8081/ch.so.daten/"
        self.base = "http://localhost:8081/jenkins/"
        self.pointer = manifest
        self.status = status
        self.calls = []
        self.quiet = False
        self.seed_result = "SUCCESS"
        self.completion = "0"
        self.report = {"publication": "accepted", "releaseId": "first",
                       "opendata": {"status": "accepted"}}
        self.missing = None
        self.stored_keys = []
        self.env = {
            "ORG_GRADLE_PROJECT_s3Endpoint": "http://garage:3900",
            "ORG_GRADLE_PROJECT_s3Region": "garage",
            "ORG_GRADLE_PROJECT_s3BucketName": "ch.so.daten",
            "ORG_GRADLE_PROJECT_s3AccessKey": "test-key",
            "ORG_GRADLE_PROJECT_s3SecretKey": "test-secret",
            "ORG_GRADLE_PROJECT_s3Publish": "true",
            "ORG_GRADLE_PROJECT_publicationManifestUrl": self.public_base + "current.json",
            "ORG_GRADLE_PROJECT_catalogDownloadBase": self.public_base.rstrip("/"),
            "ORG_GRADLE_PROJECT_portalReloadToken": "test-reload",
        }

    def pause(self):
        self.remaining()
        time.sleep(0.001)

    def http(self, url, method="GET", **kwargs):
        if url.endswith("current.json"):
            status = self.status if self.pointer is not None else 404
            return status, json.dumps(self.pointer).encode(), {}
        return (404 if url.endswith(self.missing or "/missing") else 200), b"", {}

    def get(self, path):
        self.calls.append(("get", path))
        if path == "api/json":
            return {"quietingDown": self.quiet}
        if path.startswith("computer/"):
            return {"computer": [{"executors": [], "oneOffExecutors": []}]}
        if "/queue/" in path:
            return {"executable": {"url": self.base + "job/gretl-datenportal-seed/2/"}}
        return {"building": False, "inQueue": False, "result": self.seed_result}

    def post(self, path):
        self.calls.append(("post", path))
        if path == "quietDown":
            self.quiet = True
        if path == "cancelQuietDown":
            self.quiet = False
        return {"Location": self.base + "queue/item/2/"}

    def container_env(self, service):
        if service == "garage":
            return {"GARAGE_DEFAULT_ACCESS_KEY": "test-key",
                    "GARAGE_DEFAULT_SECRET_KEY": "test-secret"}
        return {"DATENPORTAL_ADMIN_RELOAD_TOKEN": "test-reload"}

    def command(self, *args, **kwargs):
        self.calls.append(("compose", args))
        if "list-objects-v2" in args:
            return self.stored_keys
        if args[-1].endswith("report.json"):
            return json.dumps(self.report)
        if args[-1] == "/var/jenkins_home/datenportal-initialize.XXXXXX":
            return "/var/jenkins_home/datenportal-initialize.fixture"
        if kwargs.get("input_text"):
            return '{"enabled":true}'
        return ""

    def init_status(self):
        return self.completion


class BootstrapTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_existing_manifest_seeds_but_does_not_initialize(self):
        fixture = Fixture(self.root, MANIFEST)
        fixture.run()
        self.assertIn(("post", "job/gretl-datenportal-seed/build"), fixture.calls)
        self.assertNotIn(("post", "quietDown"), fixture.calls)
        self.assertFalse(any("initializePublication" in str(call) for call in fixture.calls))

    def test_check_only_has_no_mutations(self):
        fixture = Fixture(self.root, MANIFEST, check_only=True)
        fixture.run()
        self.assertFalse(any(call[0] == "post" or "up" in call[1] for call in fixture.calls))

    def test_fresh_manifest_initializes_after_seed_and_unpauses(self):
        fixture = Fixture(self.root)
        class Process:
            def communicate(self, script, **kwargs):
                self.script = script
                fixture.pointer = MANIFEST
        process = Process()
        with patch.object(module.subprocess, "Popen", return_value=process):
            fixture.run()
        self.assertIn("initializePublication", process.script)
        self.assertIn("-PgitWriteBack=false", process.script)
        self.assertIn("gretl-datenportal/topic-repo", process.script)
        self.assertIn("flock -n 9", process.script)
        self.assertFalse(fixture.quiet)
        phases = [call[1] for call in fixture.calls if call[0] == "post"]
        self.assertEqual(phases, ["job/gretl-datenportal-seed/build", "quietDown", "cancelQuietDown"])

    def test_http_errors_and_invalid_manifests_never_initialize(self):
        cases = [(503, MANIFEST), (403, MANIFEST), (200, {"releaseId": "old"}),
                 (200, {**MANIFEST, "duckdb": None}), (200, {**MANIFEST, "datasheets": "../outside"})]
        for status, manifest in cases:
            with self.subTest(status=status, manifest=manifest):
                fixture = Fixture(self.root, manifest, status)
                with self.assertRaises(Error):
                    fixture.run()
                self.assertFalse(any(call[0] == "post" for call in fixture.calls))

    def test_missing_artifact_is_not_an_empty_publication(self):
        fixture = Fixture(self.root, MANIFEST)
        fixture.missing = "catalog-first.duckdb"
        with self.assertRaisesRegex(Error, "Artefakt fehlt"):
            fixture.run()

    def test_deleted_pointer_with_existing_publication_is_not_reinitialized(self):
        fixture = Fixture(self.root)
        fixture.stored_keys = ["datasheets-previous.xtf"]
        with self.assertRaisesRegex(Error, "vorhandenen Publikationsartefakten"):
            fixture.run()
        self.assertFalse(any(call[0] == "post" for call in fixture.calls))

    def test_failed_seed_prevents_publication(self):
        fixture = Fixture(self.root)
        fixture.seed_result = "FAILURE"
        with self.assertRaisesRegex(Error, "Seed fehlgeschlagen"):
            fixture.run()
        self.assertNotIn(("post", "quietDown"), fixture.calls)

    def test_existing_quiet_down_is_preserved(self):
        fixture = Fixture(self.root)
        fixture.quiet = True
        with self.assertRaisesRegex(Error, "pausiert"):
            fixture.run()
        self.assertTrue(fixture.quiet)
        self.assertNotIn(("post", "cancelQuietDown"), fixture.calls)

    def test_external_or_disabled_publication_is_rejected_before_seed(self):
        for key, value in [("ORG_GRADLE_PROJECT_s3Endpoint", "https://s3.example.org"),
                           ("ORG_GRADLE_PROJECT_s3BucketName", "external"),
                           ("ORG_GRADLE_PROJECT_s3Publish", "false")]:
            fixture = Fixture(self.root)
            fixture.env[key] = value
            with self.assertRaisesRegex(Error, "lokalen Garage"):
                fixture.run()
            self.assertFalse(any(call[0] == "post" for call in fixture.calls))

    def test_interrupted_unknown_run_is_not_repeated(self):
        fixture = Fixture(self.root)
        fixture.receipt.write_text(json.dumps({
            "phase": "initializing", "work": "/var/jenkins_home/interrupted",
            "owns_quiet_down": True}))
        fixture.completion = "interrupted"
        fixture.quiet = True
        with self.assertRaisesRegex(Error, "unterbrochen"):
            fixture.run()
        self.assertTrue(fixture.quiet)
        self.assertFalse(any(call[0] == "post" for call in fixture.calls))

    def test_completed_disconnected_run_is_recovered(self):
        fixture = Fixture(self.root, MANIFEST)
        fixture.receipt.write_text(json.dumps({
            "phase": "initializing", "work": "/var/jenkins_home/finished",
            "owns_quiet_down": True}))
        fixture.quiet = True
        fixture.run()
        self.assertFalse(fixture.quiet)
        self.assertNotIn(("post", "quietDown"), fixture.calls)

    def test_unconfirmed_seed_submission_is_not_repeated(self):
        fixture = Fixture(self.root)
        fixture.receipt.write_text('{"phase":"seed_submitting"}')
        with self.assertRaisesRegex(Error, "nicht eindeutig"):
            fixture.run()
        self.assertFalse(any(call[0] == "post" for call in fixture.calls))

    def test_invalid_datasheets_before_pointer_can_be_retried_explicitly(self):
        fixture = Fixture(self.root)
        fixture.completion = "1"
        fixture.report = {"publication": "not-published", "pointerAttempted": False}
        class Process:
            def communicate(self, script, **kwargs):
                pass
        with patch.object(module.subprocess, "Popen", return_value=Process()):
            with self.assertRaisesRegex(Error, "nicht vollständig"):
                fixture.run()
        self.assertEqual(fixture.state["phase"], "publication_failed_safe")
        self.assertFalse(fixture.quiet)

    def test_accepted_pointer_with_failed_rdf_is_not_complete(self):
        fixture = Fixture(self.root, MANIFEST)
        fixture.receipt.write_text(json.dumps({
            "phase": "initializing", "work": "/var/jenkins_home/partial",
            "owns_quiet_down": True}))
        fixture.completion = "1"
        fixture.report = {"publication": "accepted", "pointerAttempted": True,
                          "releaseId": "first", "opendata": {"status": "unknown"}}
        with self.assertRaisesRegex(Error, "nicht vollständig"):
            fixture.run()
        self.assertEqual(fixture.state["phase"], "publication_uncertain")
        self.assertFalse(any(call == ("post", "job/gretl-datenportal-seed/build")
                             for call in fixture.calls))

    def test_known_failed_candidates_remain_retryable_after_the_seed(self):
        fixture = Fixture(self.root)
        fixture.receipt.write_text(json.dumps({
            "phase": "publication_failed_safe",
            "safe_candidate_keys": ["datasheets-first.xtf"]}))
        fixture.stored_keys = ["datasheets-first.xtf"]
        class Process:
            def communicate(self, script, **kwargs):
                fixture.pointer = MANIFEST
        with patch.object(module.subprocess, "Popen", return_value=Process()):
            fixture.run()
        self.assertEqual(fixture.state["phase"], "complete")
        self.assertEqual(fixture.state["safe_candidate_keys"], [])

    def test_read_only_check_does_not_hide_an_unknown_initialization(self):
        fixture = Fixture(self.root, MANIFEST, check_only=True)
        fixture.receipt.write_text('{"phase":"publication_uncertain"}')
        with self.assertRaisesRegex(Error, "nicht bestätigt"):
            fixture.run()
        self.assertFalse(fixture.calls)

    def test_parallel_calls_hold_one_lock(self):
        first, second = Fixture(self.root, MANIFEST), Fixture(self.root, MANIFEST)
        entered = threading.Event()
        with first.lock():
            def competing():
                with second.lock():
                    entered.set()
            thread = threading.Thread(target=competing)
            thread.start()
            self.assertFalse(entered.wait(0.05))
        thread.join(timeout=2)
        self.assertTrue(entered.is_set())


class InitTest(unittest.TestCase):
    def test_fresh_credentials_and_reload_token_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "services/garage").mkdir(parents=True)
            for path in ("scripts/init.sh", ".env.example", "services/garage/garage.toml.template"):
                shutil.copy(ROOT / path, root / path)
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith(("DATENPORTAL_", "GARAGE_"))}
            for _ in range(2):
                result = subprocess.run(["bash", "scripts/init.sh"], cwd=root,
                                        env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                content = (root / ".env").read_bytes()
                if _ == 0:
                    original = content
                    self.assertIn(b"DATENPORTAL_PORTAL_RELOAD_TOKEN=", content)
                else:
                    self.assertEqual(content, original)
                self.assertEqual((root / ".env").stat().st_mode & 0o777, 0o600)
                self.assertNotIn("GARAGE_DEFAULT_SECRET_KEY=", result.stdout)


if __name__ == "__main__":
    unittest.main()
