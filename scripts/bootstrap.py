#!/usr/bin/env python3
"""Stack orchestration only; publication logic stays in the topics repository."""
import argparse
import base64
import contextlib
import fcntl
import http.cookiejar
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
validate_manifest = runpy.run_path(
    str(ROOT / "scripts/testing/check-publication-manifest.py"))["validate"]


class BootstrapError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Bootstrap:
    def __init__(self, files, timeout=1800, check_only=False):
        self.compose = ["docker", "compose"]
        for file in files or ["compose.yaml"]:
            self.compose += ["-f", file]
        self.deadline = time.monotonic() + timeout
        self.check_only = check_only
        self.public = urllib.request.build_opener(NoRedirect)
        self.jenkins = urllib.request.build_opener(
            NoRedirect, urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.config = self.command("config", "--format", "json", json_output=True)
        self.project = self.config["name"]
        self.runtime = ROOT / ".runtime" / self.project
        self.runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.runtime, 0o700)
        self.receipt = self.runtime / "bootstrap.json"
        self.state = {}
        configured = self.config["services"]["jenkins"]["environment"]
        self.env = self.container_env("jenkins")
        # Both commands contain secrets; capture their output without logging it.
        for key in ("THEMEN_REPO_MODE", "THEMEN_REPO_PATH", "THEMEN_REPO_URL",
                    "THEMEN_REPO_BRANCH", "ORG_GRADLE_PROJECT_publicationManifestUrl",
                    "ORG_GRADLE_PROJECT_s3Endpoint", "ORG_GRADLE_PROJECT_s3BucketName",
                    "ORG_GRADLE_PROJECT_s3AccessKey", "ORG_GRADLE_PROJECT_s3SecretKey",
                    "ORG_GRADLE_PROJECT_s3Publish", "ORG_GRADLE_PROJECT_portalReloadToken"):
            if str(configured.get(key, "")) != self.env.get(key, ""):
                raise BootstrapError(
                    "Jenkins-Laufzeit passt nicht zur Compose-Konfiguration; "
                    "up.sh mit den passenden Optionen ausführen.")
        parsed = urllib.parse.urlsplit(self.env.get("JENKINS_URL", ""))
        if (self.env.get("JENKINS_RUNTIME_MODE") != "dev"
                or parsed.scheme != "http" or parsed.hostname != "localhost"
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path.rstrip("/") != "/jenkins"):
            raise BootstrapError("Bootstrap ist nur für die lokale Stack-Testumgebung vorgesehen.")
        self.base = urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, "/jenkins/", "", ""))
        self.public_base = urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, "/ch.so.daten/", "", ""))
        user = os.environ.get("DATENPORTAL_BOOTSTRAP_USER", "admin")
        password = os.environ.get("DATENPORTAL_BOOTSTRAP_PASSWORD", "admin")
        self.authorization = "Basic " + base64.b64encode(
            (user + ":" + password).encode()).decode()

    def remaining(self):
        seconds = self.deadline - time.monotonic()
        if seconds <= 0:
            raise BootstrapError(
                "Bootstrap-Zeitlimit erreicht. Prüfstand unter .runtime und "
                "Jenkins-Bericht prüfen; unklare Uploads nicht erneut starten.")
        return seconds

    def pause(self):
        time.sleep(min(1, self.remaining()))

    def command(self, *args, json_output=False, input_text=None):
        try:
            result = subprocess.run(
                self.compose + list(args), cwd=ROOT, input=input_text, text=True,
                capture_output=True, timeout=self.remaining())
        except subprocess.TimeoutExpired as error:
            raise BootstrapError("Compose-Zeitlimit erreicht; aktiven Lauf prüfen.") from error
        if result.returncode:
            raise BootstrapError("Compose-Aufruf fehlgeschlagen: " + args[0])
        if json_output:
            return json.loads(result.stdout)
        return result.stdout.strip()

    def container_env(self, service):
        container = self.command("ps", "-q", service)
        if not container or len(container.splitlines()) != 1:
            raise BootstrapError("Genau ein laufender " + service + "-Container wird benötigt.")
        result = subprocess.run(["docker", "inspect", container], cwd=ROOT,
                                capture_output=True, text=True, timeout=self.remaining())
        if result.returncode:
            raise BootstrapError("Containerstatus nicht lesbar: " + service)
        data = json.loads(result.stdout)[0]
        if not data["State"]["Running"]:
            raise BootstrapError("Container ist gestoppt: " + service)
        return dict(item.split("=", 1) for item in data["Config"]["Env"] if "=" in item)

    def http(self, url, method="GET", headers=None, data=None, authenticated=False):
        request_headers = {"Cache-Control": "no-cache, no-store"}
        request_headers.update(headers or {})
        if authenticated:
            url = self.trusted(url)
            request_headers["Authorization"] = self.authorization
        req = urllib.request.Request(url, data=data, headers=request_headers, method=method)
        opener = self.jenkins if authenticated else self.public
        try:
            with opener.open(req, timeout=min(30, self.remaining())) as response:
                return response.status, response.read(), response.headers
        except urllib.error.HTTPError as response:
            return response.code, response.read(), response.headers
        except (urllib.error.URLError, TimeoutError) as error:
            raise BootstrapError("HTTP-Verbindung zum lokalen Stack fehlgeschlagen.") from error

    def trusted(self, location):
        url = urllib.parse.urljoin(self.base, location)
        parsed = urllib.parse.urlsplit(url)
        base = urllib.parse.urlsplit(self.base)
        if (parsed.scheme != base.scheme or parsed.netloc != base.netloc
                or parsed.username or parsed.password
                or not parsed.path.startswith(base.path)
                or "/../" in urllib.parse.unquote(parsed.path)):
            raise BootstrapError("Jenkins-Antwort verweist auf eine andere Basisadresse.")
        return url

    def get(self, path):
        status, body, _ = self.http(path, authenticated=True)
        if status != 200:
            raise BootstrapError("Jenkins-API ist nicht lesbar (HTTP %s)." % status)
        try:
            return json.loads(body)
        except ValueError as error:
            raise BootstrapError("Ungültige Jenkins-API-Antwort.") from error

    def post(self, path):
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        status, body, _ = self.http("crumbIssuer/api/json", authenticated=True)
        if status == 200:
            crumb = json.loads(body)
            headers[crumb["crumbRequestField"]] = crumb["crumb"]
        elif status != 404:
            raise BootstrapError("Jenkins-Anmeldung/CSRF-Abfrage fehlgeschlagen.")
        status, _, response_headers = self.http(
            path, "POST", headers, b"", authenticated=True)
        if status not in (200, 201, 202, 302, 303):
            raise BootstrapError("Jenkins-Auftrag nicht bestätigt (HTTP %s)." % status)
        return response_headers

    def save(self, **values):
        self.state.update(values)
        temporary = self.receipt.with_suffix(".tmp")
        with temporary.open("w") as output:
            os.chmod(temporary, 0o600)
            json.dump(self.state, output, indent=2)
            output.write("\n")
        temporary.replace(self.receipt)

    @contextlib.contextmanager
    def lock(self):
        with (self.runtime / "bootstrap.lock").open("a") as handle:
            os.chmod(handle.name, 0o600)
            while True:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    self.pause()
            self.state = json.loads(self.receipt.read_text()) if self.receipt.exists() else {}
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def manifest(self):
        status, body, _ = self.http(self.public_base + "current.json")
        if status == 404:
            return None
        if status != 200:
            raise BootstrapError("current.json ist nicht verfügbar (HTTP %s)." % status)
        try:
            manifest = validate_manifest(json.loads(body))
        except (ValueError, TypeError) as error:
            raise BootstrapError(
                "current.json benötigt gültige Release-Dateinamen und DuckDB. "
                "Bestand prüfen bzw. regulär publizieren; keine Neuinitialisierung.") from error
        for key in ("datasheets", "catalog", "duckdb"):
            if manifest[key] is not None:
                status, _, _ = self.http(self.public_base + manifest[key], method="HEAD")
                if status != 200:
                    raise BootstrapError("Referenziertes Artefakt fehlt: " + key)
        return manifest

    def local_target(self):
        garage = self.container_env("garage")
        expected = {
            "ORG_GRADLE_PROJECT_s3Endpoint": "http://garage:3900",
            "ORG_GRADLE_PROJECT_s3Region": "garage",
            "ORG_GRADLE_PROJECT_s3BucketName": "ch.so.daten",
            "ORG_GRADLE_PROJECT_publicationManifestUrl": self.public_base + "current.json",
            "ORG_GRADLE_PROJECT_catalogDownloadBase": self.public_base.rstrip("/"),
            "ORG_GRADLE_PROJECT_s3AccessKey": garage.get("GARAGE_DEFAULT_ACCESS_KEY"),
            "ORG_GRADLE_PROJECT_s3SecretKey": garage.get("GARAGE_DEFAULT_SECRET_KEY"),
        }
        if any(self.env.get(key) != value for key, value in expected.items()) or \
                self.env.get("ORG_GRADLE_PROJECT_s3Publish", "").lower() != "true":
            raise BootstrapError(
                "Automatische Erstpublikation erfordert den lokalen Garage-Bestand "
                "und aktivierte S3-Publikation. Abweichende Ziele administrativ initialisieren.")
        # Only candidates from runs conclusively failed before attempting the
        # pointer are eligible for an explicit retry. Persist this evidence
        # across the subsequent seed, rather than relying on its current phase.
        safe_keys = set(self.state.get("safe_candidate_keys", []))
        if len(safe_keys) >= 1000:
            raise BootstrapError("Zu viele fehlgeschlagene Kandidaten; Bestand administrativ klären.")
        keys = self.command(
            "--profile", "tools", "run", "--rm", "--no-deps", "aws",
            "s3api", "list-objects-v2", "--bucket", "ch.so.daten",
            "--prefix", "datasheets-", "--max-keys", str(len(safe_keys) + 1),
            "--no-paginate", "--query", "Contents[].Key", "--output", "json",
            json_output=True)
        if keys and not set(keys).issubset(safe_keys):
            raise BootstrapError(
                "current.json fehlt bei vorhandenen Publikationsartefakten. "
                "Vorhandenen Bestand klären; kein automatischer neuer Erststand.")

    def wait_seed(self, queue=None, build=None):
        while not build:
            item = self.get(self.trusted(queue).rstrip("/") + "/api/json")
            if item.get("cancelled"):
                raise BootstrapError("Seed wurde abgebrochen.")
            if item.get("executable"):
                build = self.trusted(item["executable"]["url"])
                self.save(seed_build=build)
            else:
                self.pause()
        while True:
            result = self.get(self.trusted(build).rstrip("/") + "/api/json")
            if not result["building"]:
                if result["result"] != "SUCCESS":
                    self.save(phase="seed_failed")
                    raise BootstrapError("Seed fehlgeschlagen; Jenkins-Build prüfen: " + build)
                print("Seed erfolgreich: " + build, flush=True)
                self.save(phase="seed_complete")
                return
            self.pause()

    def seed(self):
        if self.get("api/json").get("quietingDown"):
            raise BootstrapError("Jenkins ist administrativ pausiert; Quiet Down bleibt erhalten.")
        if self.state.get("phase") == "seed_submitting":
            raise BootstrapError(
                "Vorheriger Seed-Auftrag wurde nicht eindeutig bestätigt. "
                "Queue/Build prüfen und bootstrap.json erst nach Klärung bereinigen.")
        if self.state.get("phase") == "seeding":
            self.wait_seed(self.state.get("seed_queue"), self.state.get("seed_build"))
            return
        job = "job/gretl-datenportal-seed/"
        # Finish the plugin's initial seed, then request this startup's snapshot.
        while True:
            status = self.get(job + "api/json?tree=building,inQueue,lastBuild[url]")
            if not status.get("building") and not status.get("inQueue"):
                break
            self.pause()
        self.save(phase="seed_submitting", seed_queue=None, seed_build=None)
        headers = self.post(job + "build")
        location = headers.get("Location")
        if not location:
            raise BootstrapError("Seed möglicherweise gestartet, aber Queue-Kennung fehlt.")
        queue = self.trusted(location)
        self.save(phase="seeding", seed_queue=queue)
        print("Seed gestartet; warte auf erfolgreichen Abschluss ...", flush=True)
        self.wait_seed(queue)

    def running_builds(self):
        data = self.get(
            "computer/api/json?tree=computer[executors[currentExecutable[url]],"
            "oneOffExecutors[currentExecutable[url]]]")
        return any(executor.get("currentExecutable") is not None
                   for computer in data["computer"]
                   for kind in ("executors", "oneOffExecutors")
                   for executor in computer.get(kind, []))

    def init_status(self):
        work = self.state["work"]
        return self.command("exec", "-T", "jenkins", "bash", "-c",
                            'if test -f "$1/exit-code"; then cat "$1/exit-code"; '
                            'elif flock -n /var/jenkins_home/datenportal-bootstrap.lock true; '
                            'then echo interrupted; else echo running; fi',
                            "bash", work)

    def release_pause(self):
        if self.state.get("owns_quiet_down"):
            self.post("cancelQuietDown")
            self.save(owns_quiet_down=False)

    def recover(self):
        status = self.init_status()
        while status == "running":
            self.pause()
            status = self.init_status()
        if status == "interrupted":
            raise BootstrapError(
                "Initialisierung wurde unterbrochen, ohne Abschlussnachweis. "
                "Arbeitskopie und Bericht prüfen: " + self.state["work"])
        self.release_pause()
        work = self.state["work"]
        try:
            report = json.loads(self.command(
                "exec", "-T", "jenkins", "cat", work + "/build/publication/outputs/report.json"))
        except (BootstrapError, ValueError):
            report = {}
        manifest = self.manifest()
        if (status == "0" and manifest and report.get("publication") == "accepted"
                and report.get("opendata", {}).get("status") == "accepted"
                and report.get("releaseId") == manifest["releaseId"]):
            self.save(phase="publication_complete")
            return manifest
        if manifest is None and report.get("publication") in ("not-published", "candidates-uploaded") \
                and not report.get("pointerAttempted"):
            safe = set(self.state.get("safe_candidate_keys", []))
            if report.get("releaseId"):
                safe.add("datasheets-" + report["releaseId"] + ".xtf")
            self.save(phase="publication_failed_safe", safe_candidate_keys=sorted(safe))
        else:
            self.save(phase="publication_uncertain")
        raise BootstrapError(
            "Erstpublikation nicht vollständig bestätigt. Bericht: " +
            work + "/build/publication/outputs/report.json; Log: " +
            str(self.runtime / "publication.log"))

    def initialize(self):
        self.local_target()
        if self.get("api/json").get("quietingDown"):
            raise BootstrapError("Jenkins ist bereits administrativ pausiert.")
        self.save(phase="pausing", owns_quiet_down=True)
        self.post("quietDown")
        started = False
        try:
            while self.running_builds():
                self.pause()
            manifest = self.manifest()
            if manifest:
                return manifest
            work = self.command("exec", "-T", "jenkins", "mktemp", "-d",
                                "/var/jenkins_home/datenportal-initialize.XXXXXX")
            self.save(phase="initializing", work=work)
            print("Erstpublikation in " + work + " ...", flush=True)
            with (self.runtime / "publication.log").open("w") as log:
                os.chmod(log.name, 0o600)
                started = True
                process = subprocess.Popen(
                    self.compose + ["exec", "-T", "jenkins", "bash", "-s", "--", work],
                    cwd=ROOT, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT,
                    text=True)
                try:
                    process.communicate(
                        (ROOT / "scripts/bootstrap-publication.sh").read_text(),
                        timeout=self.remaining())
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait()
                    raise BootstrapError(
                        "Host-Zeitlimit erreicht; Containerlauf/Prüfstand vor erneutem Aufruf prüfen.")
            return self.recover()
        finally:
            if not started:
                self.release_pause()
                self.save(phase="seed_complete")

    def portal_ready(self, manifest, start):
        if start:
            self.command("up", "-d", "--no-deps", "--wait", "--wait-timeout", "120", "sodata")
        portal = self.container_env("sodata")
        token = self.env.get("ORG_GRADLE_PROJECT_portalReloadToken", "")
        if not token or portal.get("DATENPORTAL_ADMIN_RELOAD_TOKEN") != token:
            raise BootstrapError(
                "Gemeinsamer Reload-Token fehlt oder passt nicht; up.sh ausführen.")
        script = (
            'set -eu\n'
            'printf "X-Reload-Token: %s\\n" "$ORG_GRADLE_PROJECT_portalReloadToken" | '
            'curl --fail --silent --show-error --header @- '
            'http://sodata:8080/admin/catalog/status\n')
        status = json.loads(self.command(
            "exec", "-T", "jenkins", "bash", "-s", input_text=script))
        self.command("exec", "-T", "jenkins", "curl", "--fail", "--silent",
                     "http://sodata:8080/actuator/health")
        if not isinstance(status, dict) or status.get("enabled") is not True:
            raise BootstrapError("Portalstatus ist ungültig.")
        print("Stack bereit; releaseId=" + manifest["releaseId"], flush=True)

    def run(self):
        with self.lock():
            if self.check_only:
                if self.state.get("phase") in (
                        "initializing", "publication_uncertain", "pausing"):
                    raise BootstrapError(
                        "Vorheriger Initialisierungslauf ist noch nicht bestätigt; "
                        "Bootstrap-Prüfstand und Bericht zuerst klären.")
                manifest = self.manifest()
                if not manifest:
                    raise BootstrapError("Publikationsbestand fehlt; Bootstrap ausführen.")
                self.portal_ready(manifest, start=False)
                return
            if self.state.get("phase") in ("initializing", "publication_uncertain"):
                self.recover()
            elif self.state.get("phase") == "pausing":
                self.release_pause()
                self.save(phase="seed_complete")
            manifest = self.manifest()
            if manifest is None:
                self.local_target()
            self.seed()
            manifest = self.manifest()
            if manifest is None:
                manifest = self.initialize()
            self.portal_ready(manifest, start=True)
            self.save(phase="complete", release_id=manifest["releaseId"], safe_candidate_keys=[])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-f", "--file", action="append", default=[])
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--check-only", action="store_true",
                        help="Check existing publication/portal without seed, upload or recreation")
    args = parser.parse_args()
    if not 1 <= args.timeout <= 7200:
        parser.error("--timeout must be between 1 and 7200 seconds")
    try:
        Bootstrap(args.file, args.timeout, args.check_only).run()
    except (BootstrapError, ValueError, KeyError, OSError, subprocess.TimeoutExpired) as error:
        print("Bootstrap fehlgeschlagen: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
