"""Exercise the local Chrome and evidence stack with generated inputs and an isolated Compose project."""

import json
import os
import secrets
import socket
import ssl
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

repo = Path(__file__).resolve().parents[2]


def configure_tls(base, env):
    def openssl(*args):
        subprocess.run(
            ["openssl", *map(str, args)],
            cwd=base,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )

    openssl(
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-days",
        "1",
        "-keyout",
        "ca.key",
        "-out",
        "ca.crt",
        "-subj",
        "/CN=synthetic-trial",
    )

    def pair(subdir, kind, name):
        d = base / subdir
        d.mkdir(exist_ok=True)
        tag = subdir + kind
        ext = base / (tag + ".ext")
        ext.write_text(
            "extendedKeyUsage="
            + ("serverAuth" if kind == "server" else "clientAuth")
            + "\nsubjectAltName=DNS:"
            + name
            + ",IP:127.0.0.1\n"
        )
        openssl(
            "req",
            "-new",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            d / (kind + ".key"),
            "-out",
            tag + ".csr",
            "-subj",
            "/CN=" + name,
        )
        openssl(
            "x509",
            "-req",
            "-days",
            "1",
            "-in",
            tag + ".csr",
            "-CA",
            "ca.crt",
            "-CAkey",
            "ca.key",
            "-CAcreateserial",
            "-out",
            d / (kind + ".crt"),
            "-extfile",
            ext,
        )
        shutil.copyfile(base / "ca.crt", d / "ca.crt")
        (d / (kind + ".key")).chmod(0o444)

    pair("loki", "server", "evidence-loki")
    pair("alloy", "server", "evidence-alloy")
    pair("alloy", "client", "synthetic-writer")
    pair("api", "client", "synthetic-api")
    env.update(
        BROWSER_EVIDENCE_LOKI_TLS_DIR=str(base / "loki"),
        BROWSER_EVIDENCE_ALLOY_TLS_DIR=str(base / "alloy"),
        BROWSER_EVIDENCE_API_TLS_DIR=str(base / "api"),
    )
    trusted = ssl.create_default_context(cafile=base / "ca.crt")
    trusted.load_cert_chain(base / "api/client.crt", base / "api/client.key")
    return trusted


def check_storage_and_identity(compose, ports, base, trusted):
    with urllib.request.urlopen(
        urllib.request.Request(ports["evidence-loki"] + "/flush", method="POST"),
        timeout=10,
        context=trusted,
    ) as res:
        assert res.status in (200, 204)
    check_bucket = 'mc alias set trial http://evidence-minio:9000 "$AWS_ACCESS_KEY_ID" "$AWS_SECRET_ACCESS_KEY" >/dev/null 2>&1 && mc ls --recursive --json trial/browser-evidence'
    until = time.monotonic() + 25
    while True:
        result = compose(
            "run",
            "--rm",
            "--no-deps",
            "--entrypoint",
            "sh",
            "evidence-bucket",
            "-ec",
            check_bucket,
        )
        records = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
        chunks = [
            r for r in records if len(r.get("key", "").split("/")[0]) == 64 and r.get("size", 0) > 0
        ]
        if chunks:
            print("isolated Loki chunk objects", len(chunks))
            break
        assert time.monotonic() < until, "no MinIO objects after flush"
        time.sleep(0.4)
    # A client on the reachable QA loopback routes has the public CA and tenant header, but no client certificate.
    ordinary = ssl.create_default_context(cafile=base / "ca.crt")
    for service, url in ports.items():
        request = urllib.request.Request(url + "/ready", headers={"X-Scope-OrgID": "synthetic"})
        try:
            response = urllib.request.urlopen(request, context=ordinary, timeout=4)
        except (OSError, ssl.SSLError):
            continue
        else:
            response.close()
            raise AssertionError("uncredentialed client reached " + service)
    print("Loki and Alloy rejected a reachable client without its certificate", flush=True)


def await_ready(url, trusted):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url + "/ready", timeout=2, context=trusted) as resp:
                if resp.status == 200:
                    return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError("Synthetic evidence endpoint did not become ready")


def main():
    project = "mes-workshop-qa-" + secrets.token_hex(6)
    env = dict(
        os.environ,
        BROWSER_EVIDENCE_S3_ACCESS_ID="trial-" + secrets.token_hex(6),
        BROWSER_EVIDENCE_S3_ACCESS_SECRET=secrets.token_urlsafe(30),
    )
    with tempfile.TemporaryDirectory(prefix="mes-workshop-stack-") as folder:
        base = Path(folder)

        trusted = configure_tls(base, env)
        override = Path(folder) / "test.yaml"

        def available():
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                return sock.getsockname()[1]

        loki_port, alloy_port = available(), available()
        override.write_text(
            f'services:\n  evidence-loki:\n    ports: ["127.0.0.1:{loki_port}:3100"]\n    networks: [ingress, objects, test_client]\n  evidence-alloy:\n    ports: ["127.0.0.1:{alloy_port}:3500"]\n    networks: [ingress, test_client]\nnetworks:\n  test_client: {{}}\n'
        )
        cli = [
            "docker",
            "compose",
            "--env-file",
            "/dev/null",
            "-p",
            project,
            "-f",
            str(repo / "services/browser_evidence/compose.yaml"),
            "-f",
            str(override),
        ]

        def compose(*args, check=True):
            return subprocess.run(
                [*cli, *args],
                env=env,
                cwd=repo,
                check=check,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

        try:
            up = compose("up", "-d", "--pull", "never", check=False)
            if up.returncode:
                print(
                    up.stdout.replace(env["BROWSER_EVIDENCE_S3_ACCESS_ID"], "***").replace(
                        env["BROWSER_EVIDENCE_S3_ACCESS_SECRET"], "***"
                    )[-1700:]
                )
                sys.exit(1)
            ports = {
                "evidence-loki": f"https://127.0.0.1:{loki_port}",
                "evidence-alloy": f"https://127.0.0.1:{alloy_port}",
            }
            for url in ports.values():
                await_ready(url, trusted)
            env.update(
                BROWSER_EVIDENCE_SYNTHETIC_ROUNDTRIP="1",
                BROWSER_EVIDENCE_WRITE_URL=ports["evidence-alloy"],
                BROWSER_EVIDENCE_READ_URL=ports["evidence-loki"],
            )
            p = subprocess.run(
                [
                    str(repo / ".venv/bin/python"),
                    "-m",
                    "pytest",
                    "--tb=short",
                    "-q",
                    "backend/tests/test_browser_recordings.py::test_workshop_binding_versions_overlap_and_revocation",
                    "backend/tests/test_browser_recordings.py::test_live_tools_isolate_workshop_owner_and_reassemble_large_events",
                ],
                env=env,
                cwd=repo,
            )
            if p.returncode:
                sys.exit(p.returncode)
            browser_env = {**env, "EA_TEST_FLOAT": "1", "PLAYWRIGHT_SKIP_BROWSER_GC": "1"}
            subprocess.run(
                ["npm", "run", "test:agent"],
                env=browser_env,
                cwd=repo / "browser-extension",
                check=True,
            )
            check_storage_and_identity(compose, ports, base, trusted)
            sys.exit(0)
        finally:
            result = compose("down", "--volumes", "--timeout", "8", check=False)
            print("isolated trial cleanup", result.returncode, flush=True)


if __name__ == "__main__":
    main()
