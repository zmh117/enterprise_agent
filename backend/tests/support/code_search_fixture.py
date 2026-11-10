"""Small synthetic SVN-format fixture for runtime guards; no network or real source."""

from hashlib import sha1
from pathlib import Path
import sqlite3

from app.modules.knowledge.domain.normalization import digest
from app.python_runtime.code_checkout_reader import CodeCheckoutReader


def make_reader(root: Path) -> CodeCheckoutReader:
    wc = root / "checkout"
    (wc / ".svn/pristine").mkdir(parents=True)
    with sqlite3.connect(wc / ".svn/wc.db") as conn:
        conn.executescript("""
            PRAGMA user_version=31;
            CREATE TABLE REPOSITORY(id INTEGER, uuid TEXT);
            INSERT INTO REPOSITORY VALUES(1,'synthetic-uuid');
            CREATE TABLE ACTUAL_NODE(local_relpath TEXT);
            CREATE TABLE NODES(local_relpath TEXT, repos_id INTEGER DEFAULT 1,
                op_depth INTEGER DEFAULT 0, presence TEXT DEFAULT 'normal',
                file_external INTEGER, moved_here INTEGER, moved_to TEXT, symlink_target TEXT,
                revision INTEGER DEFAULT 7, repos_path TEXT, kind TEXT, checksum TEXT, properties BLOB);
        """)
        for path in ("", "src", "other"):
            (wc / path).mkdir(exist_ok=True)
            conn.execute(
                "INSERT INTO NODES(local_relpath,repos_path,kind) VALUES(?,?, 'dir')",
                (path, "trunk" + ("/" + path if path else "")),
            )
    info = wc.stat()
    reader = CodeCheckoutReader(
        root,
        {
            "directory": wc.name,
            "physical_key": digest([info.st_dev, info.st_ino]),
            "allowed_paths": ["src"],
            "revision": 7,
            "branch_path": "trunk",
            "repository_uuid": "synthetic-uuid",
            "analysis_id": "synthetic-analysis",
        },
    )
    add_file(reader, "src/订单.cpp", "// 中文规则\n发布失败\nreturn reject;\n".encode("gb18030"))
    add_file(reader, "src/Review.cpp", "// review\n发布失败\nreturn reject;\n".encode())
    add_file(reader, "other/hidden.cpp", b"outside scope")
    (wc / "src/untracked.cpp").write_text("untracked needle")
    return reader


def add_file(reader: CodeCheckoutReader, path: str, raw: bytes) -> None:
    checksum = sha1(raw).hexdigest()
    pristine = reader.root / f".svn/pristine/{checksum[:2]}/{checksum}.svn-base"
    pristine.parent.mkdir(parents=True, exist_ok=True)
    pristine.write_bytes(raw)
    target = reader.root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    with sqlite3.connect(reader.root / ".svn/wc.db") as conn:
        conn.execute(
            "INSERT INTO NODES(local_relpath,repos_path,kind,checksum) VALUES(?,?,'file',?)",
            (path, "trunk/" + path, "$sha1$" + checksum),
        )
