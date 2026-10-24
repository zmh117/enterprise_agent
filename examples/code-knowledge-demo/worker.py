"""Synthetic SVN owner and analysis worker. Never expose a source-reading API."""

import json
import os
import sqlite3
import subprocess
import tempfile
import threading
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from analyzer import AnalysisGap, analyze


def now():
    return datetime.now(timezone.utc).isoformat()


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, timeout=20).stdout.decode()


class Engine:
    def __init__(
        self, private=Path("/private"), public=Path("/knowledge"), fixtures=Path("/app/fixtures")
    ):
        self.private, self.public = private, public
        private.mkdir(parents=True, exist_ok=True)
        public.mkdir(parents=True, exist_ok=True)
        self.repo, self.wc = private / "repository", private / "working-copy"
        self.url = self.repo.as_uri()
        self.db = public / "business.sqlite3"
        self.lock = threading.RLock()
        self.sync_lock = threading.Lock()
        self.paused = False
        self.error = None
        self.analyzing = None
        self.stop = threading.Event()
        if not self.repo.exists():
            run("svnadmin", "create", str(self.repo))
        if self.head() == 0:
            run(
                "svn",
                "import",
                str(fixtures),
                self.url + "/trunk",
                "-m",
                "建立合成业务基线",
                "--non-interactive",
            )
        if not self.wc.exists():
            run("svn", "checkout", self.url + "/trunk", str(self.wc), "--non-interactive")
        with self.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS state (
                    id INTEGER PRIMARY KEY CHECK(id=1), baseline INTEGER NOT NULL,
                    applied INTEGER NOT NULL, scanned INTEGER NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS facts (id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    revision INTEGER, topic TEXT, before_body TEXT, after_body TEXT,
                    committed_at TEXT, analyzed_at TEXT, PRIMARY KEY(revision, topic));
                CREATE TABLE IF NOT EXISTS commits (
                    revision INTEGER PRIMARY KEY, outcome TEXT, committed_at TEXT, analyzed_at TEXT);
            """)
            conn.execute("INSERT OR IGNORE INTO state VALUES (1, ?, 0, 0, ?)", (self.head(), now()))

    def connect(self):
        return sqlite3.connect(self.db, timeout=5)

    def head(self):
        with self.lock:
            return int(
                run(
                    "svn",
                    "info",
                    "--show-item",
                    "revision",
                    "-r",
                    "HEAD",
                    self.url,
                    "--non-interactive",
                ).strip()
            )

    def status(self):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT baseline, applied, scanned, updated_at FROM state"
            ).fetchone()
            event_count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        return {
            "head": self.head(),
            "baseline": row[0],
            "applied": row[1],
            "scanned": row[2],
            "updated_at": row[3],
            "event_count": event_count,
            "paused": self.paused,
            "analyzing": self.analyzing,
            "error": self.error,
        }

    def logs(self, start, end):
        raw = run(
            "svn", "log", "--xml", "-v", "-r", f"{start}:{end}", self.url, "--non-interactive"
        )
        entries = []
        for item in ET.fromstring(raw).findall("logentry"):
            paths = [p.text or "" for p in item.findall("paths/path")]
            relevant = any(p == "/trunk" or p.startswith("/trunk/") for p in paths)
            entries.append((int(item.attrib["revision"]), item.findtext("date"), relevant))
        return sorted(entries)

    def apply(self, revision, committed_at, baseline=False, relevant=True):
        self.analyzing = revision
        if relevant:
            with tempfile.TemporaryDirectory() as temp:
                candidate = Path(temp) / "candidate"
                run(
                    "svn",
                    "export",
                    "--ignore-externals",
                    "--non-interactive",
                    "-r",
                    str(revision),
                    self.url + "/trunk",
                    str(candidate),
                )
                facts, evidence = analyze(candidate)
            # Evidence and machine expressions never enter the public volume.
            (self.private / "evidence.json").write_text(
                json.dumps(
                    {"revision": revision, "evidence": evidence, "facts": facts}, ensure_ascii=False
                )
            )
            public_facts = [{k: v for k, v in f.items() if k != "condition"} for f in facts]
        else:
            public_facts = None
        analyzed_at = now()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            applied = conn.execute("SELECT applied FROM state").fetchone()[0]
            if revision <= applied:
                return
            old = {row[0]: json.loads(row[1]) for row in conn.execute("SELECT id, body FROM facts")}
            changes = 0
            if public_facts is not None:
                new = {f["id"]: f for f in public_facts}
                if not baseline:
                    for topic in sorted(old.keys() | new.keys()):
                        before, after = old.get(topic), new.get(topic)
                        if before != after:
                            conn.execute(
                                "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?)",
                                (
                                    revision,
                                    topic,
                                    json.dumps(before, ensure_ascii=False),
                                    json.dumps(after, ensure_ascii=False),
                                    committed_at,
                                    analyzed_at,
                                ),
                            )
                            changes += 1
                conn.execute("DELETE FROM facts")
                conn.executemany(
                    "INSERT INTO facts VALUES (?, ?)",
                    [(f["id"], json.dumps(f, ensure_ascii=False)) for f in public_facts],
                )
            outcome = (
                "BASELINE" if baseline else "BUSINESS_CHANGED" if changes else "NO_BUSINESS_CHANGE"
            )
            conn.execute(
                "INSERT INTO commits VALUES (?, ?, ?, ?)",
                (revision, outcome, committed_at, analyzed_at),
            )
            conn.execute(
                "UPDATE state SET applied=?, scanned=?, updated_at=? WHERE id=1",
                (revision, revision, analyzed_at),
            )
        self.analyzing = None

    def sync_once(self):
        with self.sync_lock:
            if self.paused:
                return
            try:
                with self.connect() as conn:
                    baseline, applied = conn.execute(
                        "SELECT baseline, applied FROM state"
                    ).fetchone()
                if applied == 0:
                    entry = self.logs(baseline, baseline)[0]
                    self.apply(baseline, entry[1], baseline=True)
                    applied = baseline
                upper = self.head()
                if upper > applied:
                    entries = self.logs(applied + 1, upper)
                    # This isolated repository grants access to every revision.
                    if [e[0] for e in entries] != list(range(applied + 1, upper + 1)):
                        raise AnalysisGap()
                    for revision, date, relevant in entries:
                        if self.paused:
                            break
                        self.apply(revision, date, relevant=relevant)
                self.error = None
            except AnalysisGap:
                self.error = "analysis_incomplete"
            except (subprocess.SubprocessError, OSError, ValueError, ET.ParseError, sqlite3.Error):
                self.error = "source_or_storage_unavailable"
            finally:
                self.analyzing = None

    def loop(self):
        while not self.stop.is_set():
            self.sync_once()
            self.stop.wait(2)

    def commit(self, scenario):
        # Fixed synthetic presets only. Neither user code nor arbitrary paths/URLs accepted.
        with self.lock:
            run("svn", "update", str(self.wc), "--ignore-externals", "--non-interactive")
            java = self.wc / "OrderPolicy.java"
            cpp = self.wc / "quantity.cpp"
            if scenario in {"tighten", "restore"}:
                pairs = [(java, "100000", "50000"), (cpp, "<= 100", "<= 50")]
                for path, previous, next_value in pairs:
                    if scenario == "restore":
                        previous, next_value = next_value, previous
                    path.write_text(path.read_text().replace(previous, next_value))
            elif scenario == "comment":
                java.write_text(
                    java.read_text() + "\n// Misleading note: all orders are rejected.\n"
                )
            elif scenario == "unrelated":
                return_value = run(
                    "svn",
                    "mkdir",
                    self.url + f"/unrelated-{self.head() + 1}",
                    "-m",
                    "无关路径演示提交",
                    "--non-interactive",
                )
                del return_value
                return {"revision": self.head(), "created": True}
            else:
                raise ValueError("unsupported scenario")
            changed = bool(run("svn", "status", str(self.wc)).strip())
            if changed:
                run(
                    "svn",
                    "commit",
                    str(self.wc),
                    "-m",
                    "演示提交：" + scenario,
                    "--non-interactive",
                )
            return {"revision": self.head(), "created": changed}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            if self.path == "/health":
                return self.reply(200, {"ready": True})
            if self.path in {"/status", "/head"}:
                return self.reply(
                    200,
                    self.server.engine.status()
                    if self.path == "/status"
                    else {"head": self.server.engine.head()},
                )
            self.reply(404, {"error": "not_found"})
        except Exception:
            self.reply(503, {"error": "source_unavailable"})

    def do_POST(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size < 1 or size > 1024:
                return self.reply(400, {"error": "invalid_request"})
            data = json.loads(self.rfile.read(size))
            if self.path == "/scenario" and set(data) == {"scenario"}:
                return self.reply(200, self.server.engine.commit(data["scenario"]))
            if self.path == "/pause" and set(data) == {"paused"} and type(data["paused"]) is bool:
                # Wait until an in-flight activation finishes so pause has deterministic semantics.
                with self.server.engine.sync_lock:
                    self.server.engine.paused = data["paused"]
                return self.reply(200, {"paused": data["paused"]})
            self.reply(400, {"error": "invalid_request"})
        except (ValueError, TypeError):
            self.reply(400, {"error": "invalid_request"})
        except Exception:
            self.reply(503, {"error": "demo_operation_failed"})


if __name__ == "__main__":
    os.umask(0o022)
    engine = Engine()
    server = ThreadingHTTPServer(("0.0.0.0", 8081), Handler)
    server.engine = engine
    threading.Thread(target=engine.loop, daemon=True).start()
    print("Synthetic SVN analysis worker ready", flush=True)
    server.serve_forever()
