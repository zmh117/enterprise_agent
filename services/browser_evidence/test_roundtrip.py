"""Exercise the local Chrome and evidence stack with generated inputs and an isolated Compose project."""

import json
import os
import secrets
import ssl
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import boto3
import yaml
from botocore.exceptions import ClientError

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


def check_bucket_quotas(compose):
    quota = compose(
        "run",
        "--rm",
        "--no-deps",
        "--entrypoint",
        "sh",
        "evidence-bucket-init",
        "-ec",
        'mc alias set admin http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1 && '
        "mc quota info --json admin/browser-evidence && mc quota info --json admin/agent-files",
    )
    rows = [json.loads(line) for line in quota.stdout.splitlines() if line.startswith("{")]
    assert [row.get("quota", 0) for row in rows] == [1024**3, 0]


def check_bucket_isolation(endpoint, file_key, evidence_key):
    def client(key):
        return boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name="us-east-1",
            aws_access_key_id=key[0],
            aws_secret_access_key=key[1],
        )

    buckets = {"agent-files": client(file_key), "browser-evidence": client(evidence_key)}
    for bucket, owner in buckets.items():
        owner.put_object(Bucket=bucket, Key="boundary-test", Body=b"synthetic")
    for bucket, owner in buckets.items():
        other = next(client for name, client in buckets.items() if name != bucket)
        for operation, arguments in (
            (other.list_objects_v2, {}),
            (other.get_object, {"Key": "boundary-test"}),
            (other.put_object, {"Key": "boundary-test", "Body": b"denied"}),
            (other.delete_object, {"Key": "boundary-test"}),
        ):
            try:
                operation(Bucket=bucket, **arguments)
            except ClientError as exc:
                assert exc.response["Error"]["Code"] == "AccessDenied"
            else:
                raise AssertionError("cross-bucket access succeeded")
        assert owner.get_object(Bucket=bucket, Key="boundary-test")["Body"].read() == b"synthetic"
        owner.delete_object(Bucket=bucket, Key="boundary-test")
    return buckets["browser-evidence"]


def check_storage_and_identity(storage, ports, base, trusted):
    with urllib.request.urlopen(
        urllib.request.Request(ports["evidence-loki"] + "/flush", method="POST"),
        timeout=10,
        context=trusted,
    ) as res:
        assert res.status in (200, 204)
    until = time.monotonic() + 25
    while True:
        records = storage.list_objects_v2(Bucket="browser-evidence").get("Contents", [])
        if any(len(row["Key"].split("/")[0]) == 64 and row["Size"] > 0 for row in records):
            print("Loki chunks verified in the shared MinIO evidence bucket")
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
        # Use the system service definitions but only project-owned volumes, networks and ports.
        # The separate File Service readiness gate is covered by the Compose and credential tests.
        root = yaml.safe_load((repo / "docker-compose.yml").read_text())
        names = ("minio", "minio-init", "evidence-bucket-init", "evidence-loki", "evidence-alloy")
        services = {name: root["services"][name] for name in names}
        del services["evidence-bucket-init"]["depends_on"]["file-service"]
        env.update(
            PLATFORM_SECRETS_DIR=folder,
            APP_ENV="test",
            FILE_STORAGE_BUCKET="agent-files",
            MINIO_ROOT_USER="qa-" + secrets.token_hex(8),
            MINIO_ROOT_PASSWORD=secrets.token_urlsafe(32),
            BROWSER_EVIDENCE_QUOTA="1GiB",
        )
        file_key = ("qa-" + secrets.token_hex(8), secrets.token_hex(20))
        for name, value in zip(("file-storage-access-id", "file-storage-secret-key"), file_key):
            (base / name).write_text(value)
            (base / name).chmod(0o400)
        for name, port in (("minio", 9000), ("evidence-loki", 3100), ("evidence-alloy", 3500)):
            services[name]["ports"] = [f"127.0.0.1::{port}"]
            if name != "minio":
                services[name]["networks"].append("test-client")
        spec = {
            "services": services,
            "networks": {
                "test-client": {},
                **{n: root["networks"][n] for n in ("evidence-ingress", "evidence-objects")},
            },
            "volumes": {
                n: {}
                for n in (
                    "minio-data",
                    "file-storage-identity",
                    "evidence-index",
                    "evidence-alloy-data",
                )
            },
            "secrets": {n: root["secrets"][n] for n in services["minio-init"]["secrets"]},
        }
        fixture = base / "compose.yaml"
        fixture.write_text(yaml.safe_dump(spec))
        cli = [
            "docker",
            "compose",
            "--env-file",
            "/dev/null",
            "--project-directory",
            str(repo),
            "--profile",
            "browser-evidence",
            "-p",
            project,
            "-f",
            str(fixture),
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
                notes = compose(
                    "logs", "--no-log-prefix", "minio-init", "evidence-bucket-init", check=False
                )
                for line in notes.stdout.splitlines():
                    if line.startswith("MinIO 初始化失败"):
                        print(line)
                raise RuntimeError("Synthetic evidence Compose startup failed: " + up.stdout[-450:])
            compose("run", "--rm", "--no-deps", "minio-init")
            compose("run", "--rm", "--no-deps", "evidence-bucket-init")
            check_bucket_quotas(compose)

            def address(name, port):
                return compose("port", name, str(port)).stdout.strip()

            storage = check_bucket_isolation(
                "http://" + address("minio", 9000),
                file_key,
                (env["BROWSER_EVIDENCE_S3_ACCESS_ID"], env["BROWSER_EVIDENCE_S3_ACCESS_SECRET"]),
            )
            ports = {
                "evidence-loki": "https://" + address("evidence-loki", 3100),
                "evidence-alloy": "https://" + address("evidence-alloy", 3500),
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
            check_storage_and_identity(storage, ports, base, trusted)
            browser_env = {**env, "EA_TEST_FLOAT": "1", "PLAYWRIGHT_SKIP_BROWSER_GC": "1"}
            subprocess.run(
                ["npm", "run", "test:agent"],
                env=browser_env,
                cwd=repo / "browser-extension",
                check=True,
            )
            sys.exit(0)
        finally:
            result = compose("down", "--volumes", "--timeout", "8", check=False)
            if result.returncode:
                raise RuntimeError("Could not clean up isolated project " + project)
            print("isolated trial cleanup complete", flush=True)


if __name__ == "__main__":
    main()
