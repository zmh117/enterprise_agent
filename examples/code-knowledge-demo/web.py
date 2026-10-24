"""Business-only demo UI and bounded tool-style query, without source access."""

import json
import sqlite3
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DB = Path("/knowledge/business.sqlite3")
WORKER = "http://worker:8081"
UI = Path(__file__).with_name("ui.html")
ROLE_GRANTS = {"analyst": {"order-business"}, "visitor": set()}


class Unavailable(Exception):
    def __init__(self, code):
        self.code = code


def worker(path, data=None):
    payload = None if data is None else json.dumps(data).encode()
    request = urllib.request.Request(
        WORKER + path, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            return json.loads(response.read(100000))
    except (OSError, ValueError):
        raise Unavailable("source_unavailable") from None


def snapshot():
    try:
        with sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=1) as conn:
            conn.execute("BEGIN")
            baseline, applied, scanned, updated_at = conn.execute(
                "SELECT baseline, applied, scanned, updated_at FROM state"
            ).fetchone()
            facts = [
                json.loads(row[0]) for row in conn.execute("SELECT body FROM facts ORDER BY id")
            ]
            events = [
                {
                    "revision": row[0],
                    "topic": row[1],
                    "before": json.loads(row[2]),
                    "after": json.loads(row[3]),
                    "committed_at": row[4],
                    "analyzed_at": row[5],
                }
                for row in conn.execute(
                    "SELECT * FROM events ORDER BY revision DESC, topic LIMIT 50"
                )
            ]
            commits = [
                {
                    "revision": row[0],
                    "outcome": row[1],
                    "committed_at": row[2],
                    "analyzed_at": row[3],
                }
                for row in conn.execute("SELECT * FROM commits ORDER BY revision DESC LIMIT 20")
            ]
        return {
            "baseline": baseline,
            "applied": applied,
            "scanned": scanned,
            "updated_at": updated_at,
            "facts": facts,
            "events": events,
            "commits": commits,
        }
    except (sqlite3.Error, TypeError, ValueError):
        raise Unavailable("knowledge_unavailable") from None


def latest(wait_seconds=8):
    started = time.monotonic()
    target = worker("/head")["head"]  # Fixed at the start; later commits cannot move this target.
    while True:
        result = snapshot()
        if result["applied"] >= target and result["scanned"] >= target:
            result.update(target=target, waited_ms=round((time.monotonic() - started) * 1000))
            return result
        if time.monotonic() - started >= wait_seconds:
            raise Unavailable("knowledge_not_ready")
        status = worker("/status")
        if status["error"]:
            raise Unavailable(status["error"])
        time.sleep(0.2)


def answer(question, result):
    # Deliberately deterministic retrieval: no model and no implied general reasoning.
    if any(word in question for word in ("变化", "变更", "历史", "时间轴")):
        return "已列出接入之后的业务变化；注释或无关路径提交不产生业务事件。", []
    if any(word in question for word in ("字段", "表结构", "数据库")):
        ids = {"schema"}
    elif any(word in question for word in ("数量", "件数", "C++")):
        ids = {"quantity"}
    elif any(word in question for word in ("按钮", "页面", "前端", "Vue")):
        ids = {"submission"}
    elif any(word in question for word in ("金额", "审批", "财务", "Java")):
        ids = {"approval"}
    elif any(word in question for word in ("规则", "流程", "业务", "全部")):
        ids = {f["id"] for f in result["facts"]}
    else:
        return (
            "当前演示支持审批条件、数量范围、页面按钮、表字段和变化时间轴。这个问题未被覆盖，不能根据示例推断。",
            [],
        )
    facts = [f for f in result["facts"] if f["id"] in ids]
    return "以下为当前代码中已核验的样例事实；未列出的路径不代表已经分析。", facts


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, data, html=False):
        body = data if html else json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header(
            "Content-Type",
            "text/html; charset=utf-8" if html else "application/json; charset=utf-8",
        )
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        )
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        if self.path == "/":
            return self.reply(200, UI.read_bytes(), html=True)
        if self.path == "/health":
            return self.reply(200, {"ready": True, "mode": "synthetic-demo"})
        return self.reply(404, {"error": "not_found"})

    def dispatch(self, data):
        if self.path == "/api/status" and set(data) == {"role"}:
            return self.reply(200, worker("/status"))
        if self.path == "/api/scenario" and set(data) == {"role", "scenario"}:
            if data["scenario"] not in {"tighten", "restore", "comment", "unrelated"}:
                raise ValueError()
            return self.reply(200, worker("/scenario", {"scenario": data["scenario"]}))
        if (
            self.path == "/api/pause"
            and set(data) == {"role", "paused"}
            and type(data["paused"]) is bool
        ):
            return self.reply(200, worker("/pause", {"paused": data["paused"]}))
        if self.path == "/api/knowledge" and set(data) == {"role"}:
            return self.reply(200, latest())
        if self.path == "/api/query" and set(data) == {"role", "question"}:
            return self.query(data["question"])
        self.reply(400, {"error": "invalid_request"})

    def query(self, question):
        if not isinstance(question, str) or not 1 <= len(question.strip()) <= 500:
            raise ValueError()
        if any(
            word in question.lower()
            for word in (
                "源码",
                "源代码",
                "source",
                "base64",
                "diff",
                "伪代码",
                "文件路径",
                "下载",
                "函数名",
            )
        ):
            return self.reply(
                200,
                {
                    "message": "只能提供业务规则、示例、表字段和业务变化；此服务没有源码读取或下载能力。",
                    "facts": [],
                    "events": [],
                    "refused": True,
                },
            )
        result = latest()
        message, facts = answer(question, result)
        return self.reply(
            200,
            {
                "message": message,
                "facts": facts,
                "events": result["events"]
                if any(w in question for w in ("变化", "变更", "历史", "时间轴"))
                else [],
                "target": result["target"],
                "applied": result["applied"],
                "waited_ms": result["waited_ms"],
                "trace": [
                    "演示角色授权检查",
                    "确认 SVN 当前目标",
                    "等待业务知识追上目标",
                    "读取业务投影",
                    "确定性回答",
                ],
            },
        )

    def do_POST(self):
        # Loopback-only demo, no credentials. Block browser cross-origin mutations.
        host = self.headers.get("Host", "")
        if host not in {"127.0.0.1:8766", "localhost:8766", "web:8080", "127.0.0.1:8080"}:
            return self.reply(403, {"error": "invalid_host"})
        if self.headers.get("Origin") not in {
            None,
            "http://127.0.0.1:8766",
            "http://localhost:8766",
        }:
            return self.reply(403, {"error": "cross_origin_denied"})
        try:
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                raise ValueError()
            size = int(self.headers.get("Content-Length", "0"))
            if not 1 <= size <= 4096:
                raise ValueError()
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict) or not isinstance(data.get("role"), str):
                raise ValueError()
            if "order-business" not in ROLE_GRANTS.get(data["role"], set()):
                return self.reply(
                    403,
                    {
                        "error": "knowledge_forbidden",
                        "message": "当前演示角色没有此知识库的业务权限。",
                    },
                )
            # This selector simulates role grants, never claims production identity authentication.
            self.dispatch(data)
        except (ValueError, TypeError, KeyError):
            self.reply(400, {"error": "invalid_request"})
        except Unavailable as exc:
            messages = {
                "knowledge_not_ready": "等待 8 秒后知识仍未更新完成，暂不可用；没有返回旧规则。",
                "analysis_incomplete": "新提交包含演示解析器不支持的逻辑，分析证据不足；没有返回旧规则。",
            }
            self.reply(
                503,
                {
                    "error": exc.code,
                    "message": messages.get(exc.code, "来源或知识服务暂不可用，未返回缓存规则。"),
                },
            )
        except Exception:
            self.reply(503, {"error": "temporarily_unavailable", "message": "演示服务暂不可用。"})


if __name__ == "__main__":
    print("Business knowledge demo on :8080", flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
