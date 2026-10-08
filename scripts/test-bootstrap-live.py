#!/usr/bin/env python3
"""Fresh/repeated full startup in two disposable, isolated Compose projects."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
import uuid

STACK = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def request(url):
    with urllib.request.urlopen(url, timeout=20) as response:
        return response.read()


def run_mode(mode):
    # Only this test's own volumes are removed; the normal stack is never touched.
    directory = Path(tempfile.mkdtemp(prefix="datenportal-start-" + mode + "-"))
    root = directory / "datenportal-dev-stack"
    shutil.copytree(STACK, root, ignore=shutil.ignore_patterns(
        ".git", ".env", ".runtime", "__pycache__", "garage.toml", "demo-inputs"))
    if mode == "working-tree":
        (directory / "datenportal-themenrepo").symlink_to(
            STACK.parent / "datenportal-themenrepo", target_is_directory=True)
    project = "dp-start-" + mode + "-" + uuid.uuid4().hex[:8]
    port, s3_port = free_port(), free_port()
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("DATENPORTAL_", "GARAGE_", "COMPOSE_", "THEMEN_", "PLUGIN_"))}
    env.update(COMPOSE_PROJECT_NAME=project, GARAGE_PUBLIC_PORT=str(port),
               GARAGE_S3_PORT=str(s3_port))
    compose = ["docker", "compose", "-f", "compose.yaml"]
    flags = []
    if mode == "registry":
        flags.append("--registry-only")
        compose += ["-f", "compose.registry.yaml"]
    log = directory / "startup.log"

    def command(args, append=True):
        with log.open("a" if append else "w") as output:
            result = subprocess.run(args, cwd=root, env=env, stdout=output,
                                    stderr=subprocess.STDOUT, timeout=1800)
        if result.returncode:
            raise RuntimeError("Command failed (%s); log: %s" % (args[0], log))

    def seed_number():
        # Existing local JCasC test account; request headers are never logged.
        import base64
        req = urllib.request.Request(
            "http://localhost:%s/jenkins/job/gretl-datenportal-seed/api/json"
            "?tree=lastBuild[number,result]" % port,
            headers={"Authorization": "Basic " + base64.b64encode(b"admin:admin").decode()})
        with urllib.request.urlopen(req, timeout=20) as response:
            build = json.load(response)["lastBuild"]
            assert build["result"] == "SUCCESS"
            return build["number"]

    print("Testing %s: project=%s, log=%s" % (mode, project, log), flush=True)
    try:
        command(["bash", "scripts/init.sh"], append=False)
        command(compose + ["config", "--quiet"])
        command(compose + ["build"])
        command(["bash", "scripts/up.sh"] + flags)
        base = "http://localhost:%s" % port
        manifest = json.loads(request(base + "/ch.so.daten/current.json"))
        assert manifest["catalog"] is None and manifest["duckdb"]
        assert request(base + "/")
        for name in (manifest["datasheets"], manifest["duckdb"], "opendata.rdf"):
            assert request(base + "/ch.so.daten/" + name)
        first_seed = seed_number()
        secrets = hashlib.sha256((root / ".env").read_bytes()).hexdigest()
        garage_config = hashlib.sha256(
            (root / "services/garage/garage.toml").read_bytes()).hexdigest()
        command(["bash", "scripts/up.sh"] + flags)
        assert json.loads(request(base + "/ch.so.daten/current.json")) == manifest
        assert seed_number() > first_seed
        assert hashlib.sha256((root / ".env").read_bytes()).hexdigest() == secrets
        assert hashlib.sha256(
            (root / "services/garage/garage.toml").read_bytes()).hexdigest() == garage_config
        # A missing pointer in an already published bucket is not a fresh stack.
        # Delete/restore only this isolated test's pointer, never a shared one.
        def s3(*args):
            return compose + ["--profile", "tools", "run", "--rm", "--no-deps",
                              "aws", "s3api"] + list(args)
        (directory / "current.json").write_text(json.dumps(manifest))
        command(s3("delete-object", "--bucket", "ch.so.daten", "--key", "current.json"))
        try:
            with log.open("a") as output:
                result = subprocess.run(
                    ["bash", "scripts/bootstrap.sh"] + compose[2:], cwd=root, env=env,
                    stdout=output, stderr=subprocess.STDOUT, timeout=60)
            assert result.returncode != 0, "Deleted pointer was reinitialized"
            assert seed_number() > first_seed
        finally:
            command(compose + ["--profile", "tools", "run", "--rm", "--no-deps",
                               "-v", str(directory / "current.json") + ":/restore.json:ro",
                               "aws", "s3api", "put-object", "--bucket", "ch.so.daten",
                               "--key", "current.json", "--body", "/restore.json",
                               "--content-type", "application/json"])
        assert json.loads(request(base + "/ch.so.daten/current.json")) == manifest
        # Prove the container lock/completion receipt survive a disconnected
        # client, without another publication or modifying the seed snapshot.
        work = subprocess.check_output(
            compose + ["exec", "-T", "jenkins", "mktemp", "-d",
                       "/var/jenkins_home/datenportal-lock-test.XXXXXX"],
            cwd=root, env=env, text=True).strip()
        script = ('exec 9>/var/jenkins_home/datenportal-bootstrap.lock; '
                  'flock -n 9 || exit 75; echo locked; sleep 4; '
                  'printf "0\\n" > "$1/exit-code"')
        client = subprocess.Popen(
            compose + ["exec", "-T", "jenkins", "bash", "-c", script, "bash", work],
            cwd=root, env=env, stdout=subprocess.PIPE, text=True)
        assert client.stdout.readline().strip() == "locked"
        client.terminate()
        client.wait(timeout=10)
        probe = subprocess.run(
            compose + ["exec", "-T", "jenkins", "flock", "-n",
                       "/var/jenkins_home/datenportal-bootstrap.lock", "true"],
            cwd=root, env=env, capture_output=True)
        assert probe.returncode != 0, "Disconnected run lost its container lock"
        deadline = time.monotonic() + 15
        while True:
            completion = subprocess.run(
                compose + ["exec", "-T", "jenkins", "cat", work + "/exit-code"],
                cwd=root, env=env, capture_output=True, text=True)
            if completion.returncode == 0:
                assert completion.stdout.strip() == "0"
                break
            assert time.monotonic() < deadline, "Disconnected run did not finish"
            time.sleep(0.2)
        command(compose + ["ps", "-a"])
        # The smoke script uses default compose arguments; COMPOSE_FILE selects
        # the same registry override for its independent Docker invocations.
        if mode == "registry":
            env["COMPOSE_FILE"] = "compose.yaml:compose.registry.yaml"
        # Persist test ports for the smoke script, which sources its test .env.
        content = (root / ".env").read_text()
        content = content.replace("GARAGE_PUBLIC_PORT=8081", "GARAGE_PUBLIC_PORT=" + str(port))
        content = content.replace("GARAGE_S3_PORT=3900", "GARAGE_S3_PORT=" + str(s3_port))
        (root / ".env").write_text(content)
        command(["bash", "scripts/smoke-test.sh"])
        print("PASS %s: automatic first publication, fresh second seed, unchanged "
              "release/secrets, deleted-pointer guard, surviving container lock, "
              "portal and smoke checks; log=%s" %
              (mode, log), flush=True)
        return {"mode": mode, "project": project, "releaseId": manifest["releaseId"],
                "log": str(log), "firstSeed": first_seed, "secondSeed": seed_number()}
    finally:
        command(compose + ["down", "-v", "--remove-orphans"])


if __name__ == "__main__":
    results = [run_mode(mode) for mode in ("working-tree", "registry")]
    print(json.dumps(results, indent=2), flush=True)
