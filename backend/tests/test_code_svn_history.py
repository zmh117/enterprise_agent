"""Real CLI tests use an isolated synthetic repository; no production SVN access."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from app.modules.knowledge.infrastructure.code_svn import SvnCodeSource
from app.modules.knowledge.infrastructure.code_svn_history import SvnCodeHistory
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError


@unittest.skipUnless(shutil.which("svn") and shutil.which("svnadmin"), "container SVN required")
class SvnHistoryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="code-history-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.auth = self.root / "auth"
        self.auth.mkdir()
        repo = self.root / "repository"
        self.repo = repo
        subprocess.run(["svnadmin", "create", str(repo)], check=True, stdout=subprocess.DEVNULL)
        self.url = repo.as_uri() + "/trunk"
        self.svn("mkdir", self.url, "-m", "synthetic repository")
        self.wc = self.root / "working copy"
        self.svn("checkout", self.url, str(self.wc))
        (self.wc / "代码 目录").mkdir()
        self.file = self.wc / "代码 目录/规则.cpp"
        self.file.write_text("if (a.empty()) return reject;\nreturn accepted;\n")
        self.svn("add", str(self.wc / "代码 目录"))
        self.commit()
        self.file.write_text("return accepted;\n")
        self.commit()
        self.file.write_text("if (a.empty()) return reject;\nreturn accepted;\n")
        self.commit()
        self.source = SvnCodeSource(
            branch_url=self.url,
            expected_uuid=self.svn("info", "--show-item", "repos-uuid", self.url).decode().strip(),
            branch_path="/trunk",
            config_directory=self.auth,
            allow_local_test=True,
        )
        self.history = SvnCodeHistory(self.source, paths=["代码 目录"], lower=1, upper=4)

    def svn(self, *args):
        return subprocess.check_output(
            ["svn", "--non-interactive", "--no-auth-cache", "--config-dir", str(self.auth), *args],
            stderr=subprocess.DEVNULL,
        )

    def commit(self, message="synthetic rule change"):
        self.svn("commit", str(self.wc), "-m", message)
        self.svn("update", str(self.wc), "--ignore-externals")

    def test_log_versions_pagination_and_revert_diff(self):
        result = self.history.log(path="", start=2, end=4, peg=4, limit=2, include_message=True)
        self.assertEqual([r["revision"] for r in result["entries"]], [4, 3])
        self.assertTrue(result["has_more"])
        self.assertTrue(all(r["date"] for r in result["entries"]))
        next_page = self.history.log(path="", start=2, end=4, peg=4, before=result["next_revision"])
        self.assertEqual([r["revision"] for r in next_page["entries"]], [2])
        self.assertFalse(next_page["has_more"])
        restored = self.history.diff(path="代码 目录", start=2, end=4, peg=4)
        self.assertEqual(restored["paths"], [])
        changed = self.history.diff(path="代码 目录/规则.cpp", start=2, end=3, peg=4, mode="text")
        self.assertIn("-if (a.empty()) return reject;", changed["text"])

    def test_repository_root_binding_supports_history_and_checkout(self):
        from app.modules.knowledge.infrastructure.code_working_copy import SvnWorkingCopy
        from app.modules.knowledge.domain.normalization import digest

        root_url = self.repo.as_uri()
        source = SvnCodeSource(
            branch_url=root_url,
            expected_uuid=self.source.expected_uuid,
            branch_path="/",
            config_directory=self.auth,
            allow_local_test=True,
        )
        source.preflight(4)
        history = SvnCodeHistory(source, paths=["trunk/代码 目录"], lower=1, upper=4)
        result = history.diff(path="trunk/代码 目录/规则.cpp", start=2, end=3, peg=4, mode="text")
        self.assertIn("-if (a.empty()) return reject;", result["text"])
        checkout = self.root / "根目录 checkout"
        self.svn("checkout", "-r", "4", root_url, str(checkout))
        stat = checkout.stat()
        working = SvnWorkingCopy(
            source, checkout, [""], physical_key=digest([stat.st_dev, stat.st_ino])
        )
        self.assertEqual(working.inspect(4)["operative_revision"], 4)

    def test_language_and_config_content_is_available_in_diff_and_log(self):
        paths = ["代码 目录/zh-CN.js", "代码 目录/config.ts"]
        before = "export default { password: '请输入密码', splitError: '不能拆批' };\n"
        after = "export default { password: '请输入密码', splitError: '质量状态不允许拆批' };\n"
        for path in paths:
            (self.wc / path).write_text(before)
            self.svn("add", str(self.wc / path))
        self.commit()  # r5
        for path in paths:
            (self.wc / path).write_text(after)
        message = "更新语言资源 password: '请输入密码'"
        self.commit(message)  # r6
        history = SvnCodeHistory(self.source, paths=["代码 目录"], lower=1, upper=6)
        for path in paths:
            with self.subTest(path=path):
                result = history.diff(path=path, start=5, end=6, peg=6, mode="text")
                self.assertIn("-" + before, result["text"])
                self.assertIn("+" + after, result["text"])
                self.assertFalse(result["partial"])
        log = history.log(path="", start=6, end=6, peg=6, include_message=True)
        self.assertEqual(log["entries"][0]["message"], message)
        self.assertFalse(log["entries"][0]["message_omitted"])

    def test_oversized_commit_message_is_still_omitted(self):
        self.file.write_text("return changed;\n")
        self.commit("synthetic " * 1000)  # r5
        history = SvnCodeHistory(self.source, paths=["代码 目录"], lower=1, upper=5)
        log = history.log(path="", start=5, end=5, peg=5, include_message=True)
        self.assertIsNone(log["entries"][0]["message"])
        self.assertTrue(log["entries"][0]["message_omitted"])

    def test_blame_range_and_bounds(self):
        result = self.history.blame(
            path="代码 目录/规则.cpp", revision=4, peg=4, start_line=1, end_line=2
        )
        self.assertEqual([r["line"] for r in result["lines"]], [1, 2])
        self.assertEqual(result["lines"][0]["last_changed_revision"], 4)
        self.assertEqual(result["lines"][1]["last_changed_revision"], 2)
        with self.assertRaises(CodeKnowledgeError):
            self.history.log(path="", start=1, end=5, peg=4)
        with self.assertRaises(CodeKnowledgeError):
            self.history.diff(path="../outside", start=2, end=3, peg=4)
        with self.assertRaises(CodeKnowledgeError):
            self.history.blame(
                path="代码 目录/规则.cpp", revision=4, peg=4, start_line=1, end_line=401
            )

    def test_existing_checkout_updates_in_place_and_rejects_dirty_or_mixed(self):
        from app.modules.knowledge.infrastructure.code_working_copy import SvnWorkingCopy
        from app.modules.knowledge.domain.normalization import digest

        stat = self.wc.stat()
        working = SvnWorkingCopy(
            self.source, self.wc, [""], physical_key=digest([stat.st_dev, stat.st_ino])
        )
        self.assertEqual(working.inspect(4)["operative_revision"], 4)
        self.assertEqual(working.update(2, timeout=20)["operative_revision"], 2)
        self.assertIn("a.empty()", self.file.read_text())
        self.assertEqual(working.update(3, timeout=20)["operative_revision"], 3)
        self.assertNotIn("a.empty()", self.file.read_text())
        self.file.write_text("local edit\n")
        with self.assertRaisesRegex(CodeKnowledgeError, "CODE_CHECKOUT_DIRTY"):
            working.update(4, timeout=20)
        self.assertEqual(self.file.read_text(), "local edit\n")
        # Test setup deliberately repairs its synthetic file, never production.
        self.svn("revert", str(self.file))
        self.svn("update", "-r", "2", str(self.file))
        with self.assertRaisesRegex(CodeKnowledgeError, "CODE_CHECKOUT_MIXED"):
            working.inspect()

    def test_sparse_selection_is_preserved_when_updating_root(self):
        from app.modules.knowledge.infrastructure.code_working_copy import SvnWorkingCopy
        from app.modules.knowledge.domain.normalization import digest

        sparse = self.root / "sparse checkout"
        self.svn("checkout", "--depth", "empty", "-r", "2", self.url, str(sparse))
        self.svn("update", "--set-depth", "infinity", "-r", "2", str(sparse / "代码 目录"))
        stat = sparse.stat()
        working = SvnWorkingCopy(
            self.source, sparse, ["代码 目录"], physical_key=digest([stat.st_dev, stat.st_ino])
        )
        self.assertEqual(working.update(3, timeout=20)["operative_revision"], 3)
        self.assertEqual((sparse / "代码 目录/规则.cpp").read_text(), "return accepted;\n")

    def test_copy_history_cannot_disclose_author_or_message_outside_scope(self):
        private = self.repo.as_uri() + "/private"
        self.svn("mkdir", private, "-m", "synthetic private directory")
        self.svn(
            "copy",
            self.url + "/代码%20目录/规则.cpp",
            private + "/hidden.cpp",
            "-m",
            "synthetic private origin",
        )
        self.svn(
            "copy",
            private + "/hidden.cpp",
            self.url + "/代码%20目录/copied.cpp",
            "-m",
            "synthetic copied secret",
        )
        history = SvnCodeHistory(self.source, paths=["代码 目录"], lower=1, upper=7)
        log = history.log(path="代码 目录/copied.cpp", start=1, end=7, peg=7, include_message=True)
        copied = next(row for row in log["entries"] if row["revision"] == 7)
        self.assertTrue(copied["paths_truncated"])
        self.assertIsNone(copied["message"])
        self.assertIsNone(copied["paths"][0]["copy_from_path"])
        with self.assertRaisesRegex(CodeKnowledgeError, "CODE_HISTORY_PATH_DENIED"):
            history.diff(path="代码 目录/copied.cpp", start=6, end=7, peg=7, mode="text")
        # Unchanged copied lines still originate in the authorized r4 file.
        inherited = history.blame(
            path="代码 目录/copied.cpp", revision=7, peg=7, start_line=1, end_line=2
        )
        self.assertEqual(inherited["lines"][0]["last_changed_revision"], 4)
        private_wc = self.root / "private-working"
        self.svn("checkout", private, str(private_wc))
        (private_wc / "hidden.cpp").write_text("private change;\n")
        self.svn("commit", str(private_wc), "-m", "synthetic private edit")  # r8
        self.svn(
            "copy",
            private + "/hidden.cpp",
            self.url + "/代码%20目录/secret-copy.cpp",
            "-m",
            "synthetic copy",
        )  # r9
        history = SvnCodeHistory(self.source, paths=["代码 目录"], lower=1, upper=9)
        with self.assertRaisesRegex(CodeKnowledgeError, "CODE_HISTORY_PATH_DENIED"):
            history.blame(
                path="代码 目录/secret-copy.cpp", revision=9, peg=9, start_line=1, end_line=1
            )

    def test_time_filters_are_utc_half_open_and_missing_revprops_stay_unknown(self):
        from datetime import datetime, UTC

        for revision, date in (
            (2, "2026-10-01T00:00:00.000000Z"),
            (3, "2026-10-02T00:00:00.000000Z"),
            (4, "2026-10-03T00:00:00.000000Z"),
        ):
            path = self.root / "date.txt"
            path.write_text(date)
            subprocess.run(
                [
                    "svnadmin",
                    "setrevprop",
                    str(self.repo),
                    "-r",
                    str(revision),
                    "svn:date",
                    str(path),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        result = self.history.log(
            path="",
            start=2,
            end=4,
            peg=4,
            start_time=datetime(2026, 10, 2, tzinfo=UTC),
            end_time=datetime(2026, 10, 3, tzinfo=UTC),
        )
        self.assertEqual([entry["revision"] for entry in result["entries"]], [3])
        subprocess.run(
            ["svnadmin", "delrevprop", str(self.repo), "-r", "3", "svn:date"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        result = self.history.log(path="", start=2, end=4, peg=4)
        self.assertTrue(result["partial"])
        self.assertIsNone(next(row for row in result["entries"] if row["revision"] == 3)["date"])

    def test_deleted_recreated_path_requires_the_correct_peg(self):
        path = "代码 目录/规则.cpp"
        self.svn("delete", str(self.file))
        self.commit()  # r5 removes the first identity.
        self.file.write_text("new identity;\n")
        self.svn("add", str(self.file))
        self.commit()  # r6 creates an unrelated file at the same path.
        history = SvnCodeHistory(self.source, paths=["代码 目录"], lower=1, upper=6)
        old = history.blame(path=path, revision=4, peg=4, start_line=1, end_line=2)
        self.assertEqual(old["lines"][0]["last_changed_revision"], 4)
        new = history.blame(path=path, revision=6, peg=6, start_line=1, end_line=1)
        self.assertEqual(new["lines"][0]["last_changed_revision"], 6)
        with self.assertRaises(CodeKnowledgeError):
            history.blame(path=path, revision=4, peg=6, start_line=1, end_line=1)

    def test_eol_changes_are_not_ignored_and_keywords_preserve_line_numbers(self):
        path = "代码 目录/规则.cpp"
        self.file.write_bytes(b"$Id$\nreturn accepted;\n")
        self.svn("propset", "svn:keywords", "Id", str(self.file))
        self.commit()  # r5
        self.file.write_bytes(b"$Id$\r\nreturn accepted;\r\n")
        self.commit()  # r6
        history = SvnCodeHistory(self.source, paths=["代码 目录"], lower=1, upper=6)
        result = history.diff(path=path, start=5, end=6, peg=6, mode="text")
        self.assertIn("@@", result["text"])
        self.assertIn("\r\n", result["text"])
        lines = history.blame(path=path, revision=6, peg=6, start_line=1, end_line=2)
        self.assertEqual([row["line"] for row in lines["lines"]], [1, 2])

    def test_chinese_diff_headers_and_legacy_content_decode_independently(self):
        self.file.write_bytes("// 发布拒绝\nreturn reject;\n".encode("gb18030"))
        self.commit()
        self.file.write_bytes("// 发布允许\nreturn accepted;\n".encode("gb18030"))
        self.commit()
        history = SvnCodeHistory(self.source, paths=["代码 目录"], lower=1, upper=6)
        result = history.diff(path="代码 目录/规则.cpp", start=5, end=6, peg=6, mode="text")
        self.assertIn("规则.cpp", result["text"])
        self.assertIn("-// 发布拒绝", result["text"])
        self.assertIn("+// 发布允许", result["text"])
        self.assertEqual(result["source_encodings"], {"before": "gb18030", "after": "gb18030"})

    def test_runtime_reads_pristine_with_encoding_eol_and_keyword_proof(self):
        from app.python_runtime.code_checkout_reader import CodeCheckoutReader
        from app.modules.knowledge.domain.normalization import digest
        from hashlib import sha256

        self.file.write_bytes(
            "// 中文业务规则 $Id$\nif (a.empty()) return reject;\n".encode("gb18030")
        )
        self.svn("propset", "svn:eol-style", "CRLF", str(self.file))
        self.svn("propset", "svn:keywords", "Id", str(self.file))
        self.commit()
        revision = int(self.svn("info", "--show-item", "revision", str(self.wc)))
        info = self.wc.stat()
        reader = CodeCheckoutReader(
            self.root,
            dict(
                directory=self.wc.name,
                physical_key=digest([info.st_dev, info.st_ino]),
                allowed_paths=["代码 目录"],
                revision=revision,
                branch_path="trunk",
                repository_uuid=self.source.expected_uuid,
            ),
        )
        result = reader.read("代码 目录/规则.cpp", 1, 2)
        self.assertIn("中文业务规则 $Id$", result["text"])
        self.assertEqual(result["representation"]["source_encoding"], "gb18030")
        self.assertEqual((result["line_start"], result["line_end"]), (1, 2))
        pristine = subprocess.check_output(
            ["svnlook", "cat", "-r", str(revision), str(self.repo), "trunk/代码 目录/规则.cpp"]
        )
        self.assertEqual(result["repository_content_hash"], sha256(pristine).hexdigest())
        self.file.write_bytes(self.file.read_bytes().replace(b"reject", b"accept"))
        with self.assertRaisesRegex(CodeKnowledgeError, "CODE_CHECKOUT_DIRTY"):
            reader.read("代码 目录/规则.cpp", 1, 2)

    def test_runtime_denies_untracked_metadata_wrong_version_and_links(self):
        from app.python_runtime.code_checkout_reader import CodeCheckoutReader
        from app.modules.knowledge.domain.normalization import digest

        info = self.wc.stat()
        grant = dict(
            directory=self.wc.name,
            physical_key=digest([info.st_dev, info.st_ino]),
            allowed_paths=[""],
            revision=4,
            branch_path="trunk",
            repository_uuid=self.source.expected_uuid,
        )
        reader = CodeCheckoutReader(self.root, grant)
        self.assertIn("return reject", reader.read("代码 目录/规则.cpp", 1, 2)["text"])
        (self.wc / "untracked.cpp").write_text("untracked")
        for path in ("untracked.cpp", ".svn/wc.db", "../outside"):
            with self.assertRaises(CodeKnowledgeError):
                reader.read(path, 1, 2)
        wrong = CodeCheckoutReader(self.root, {**grant, "revision": 3})
        with self.assertRaisesRegex(CodeKnowledgeError, "CODE_CHECKOUT_SOURCE_MISMATCH"):
            wrong.read("代码 目录/规则.cpp", 1, 2)
        self.file.unlink()
        self.file.symlink_to(self.wc / "untracked.cpp")
        with self.assertRaises(CodeKnowledgeError):
            reader.read("代码 目录/规则.cpp", 1, 2)

    @unittest.skipUnless(shutil.which("rg"), "runtime ripgrep required")
    def test_runtime_search_prepares_only_versioned_normalized_text_and_cleans_cache(self):
        from app.python_runtime.code_checkout_reader import CodeCheckoutReader
        from app.python_runtime.code_source_search import SourceSearchBatch, search_options
        from app.python_runtime.job_sandbox import JobSandboxManager
        from app.modules.knowledge.domain.normalization import digest

        self.file.write_bytes("// 发布失败\nreturn reject;\n".encode("gb18030"))
        self.commit()
        (self.wc / "代码 目录/untracked.cpp").write_text("must not search")
        info = self.wc.stat()
        reader = CodeCheckoutReader(
            self.root,
            dict(
                directory=self.wc.name,
                physical_key=digest([info.st_dev, info.st_ino]),
                allowed_paths=["代码 目录"],
                revision=5,
                branch_path="trunk",
                repository_uuid=self.source.expected_uuid,
            ),
        )
        self.assertEqual(
            list(reader.search_candidates("代码 目录", "*.cpp")), ["代码 目录/规则.cpp"]
        )
        sandbox = JobSandboxManager(self.root / "jobs").create("synthetic-search")
        batch = SourceSearchBatch(sandbox, reader, search_options({"pattern": "发布失败"}))
        try:
            batch.prepare("代码 目录")
            relative = next(iter(batch.paths))
            self.assertEqual((sandbox.path / relative).read_text(), "// 发布失败\nreturn reject;\n")
            self.assertEqual(sandbox.usage()[0], 1)
            batch.close()
            self.assertEqual(sandbox.usage(), (0, 0))
        finally:
            sandbox.cleanup()


if __name__ == "__main__":
    unittest.main()
