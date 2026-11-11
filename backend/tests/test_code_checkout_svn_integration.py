"""在 Linux 容器的真实 SVN 上验证完整稀疏工作副本，不连接模型或数据库。"""

from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import unittest
import os

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.infrastructure.code_checkout_client import (
    WorkingCopyClient,
    checkout_directory,
)
from app.modules.knowledge.infrastructure.code_svn import SvnCodeSource, SvnCommandFailure


@unittest.skipUnless(os.environ.get("CODE_AUTH_SVN_URL"), "isolated authenticated fixture required")
class AuthenticatedWorkingCopyAcceptance(unittest.TestCase):
    def test_page_connections_use_deployment_ca_without_reusing_auth_configuration(self):
        from unittest.mock import patch
        from app.modules.knowledge.infrastructure.code_svn_access import CodeSvnAccess

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            access = CodeSvnAccess(None, root / "unused-registry.json")
            public_url = os.environ["CODE_AUTH_SVN_URL"].replace(
                "/repos/fixture/", "/public/fixture/"
            )
            entry = dict(
                public_url=public_url,
                branch_url=public_url,
                repository_uuid="",
                branch_path="/",
                resource_id="synthetic-resource",
                secret_ref="",
            )
            # No configured CA must keep rejecting the self-signed server.
            with self.assertRaisesRegex(CodeKnowledgeError, "CODE_SVN_CERTIFICATE_INVALID"):
                with access.client(entry, root, lambda: False):
                    self.fail("untrusted connection was accepted")
            trusted = root / "trusted-ca"
            trusted.mkdir()
            shutil.copyfile(os.environ["CODE_AUTH_SVN_CA"], trusted / "synthetic.crt")
            # Auth material elsewhere under the auth root must not be inherited.
            (root / "servers").write_text("this is not a usable SVN configuration")
            with access.client(entry, root, lambda: False) as client:
                assert client.source._credentials is None
                assert client.source.branch_url == public_url
                assert client.browse(2)["revision"] == 2
                config = client.source.config_directory
                assert (config / "trusted-ca.pem").is_file()
                assert not any(p.is_file() for p in (config / "auth").rglob("*"))
            assert not config.exists()
            private_url = os.environ["CODE_AUTH_SVN_URL"]
            entry.update(
                public_url=private_url, branch_url=private_url, secret_ref="synthetic-reference"
            )
            with patch.object(
                access, "_credentials", return_value=("synthetic-user", "synthetic-password")
            ):
                with access.client(entry, root, lambda: False) as client:
                    assert client.browse(2)["revision"] == 2

    @unittest.skipUnless(
        os.environ.get("CODE_HTTP_SVN_URL") and os.environ.get("CODE_SVN_PROTOCOL_URL"),
        "network protocol fixture required",
    )
    def test_network_protocols_browse_checkout_and_update(self):
        from app.modules.knowledge.infrastructure.code_checkout_identity import persistent_identity
        from app.modules.knowledge.infrastructure.code_working_copy import SvnWorkingCopy

        public_urls = (os.environ["CODE_HTTP_SVN_URL"], os.environ["CODE_SVN_PROTOCOL_URL"])
        cases = [(url, None) for url in public_urls] + [
            (
                url.replace("/public/", "/repos/").replace("/repo/", "/repo-auth/"),
                ("synthetic-user", "synthetic-password"),
            )
            for url in public_urls
        ]
        for url, credentials in cases:
            with (
                self.subTest(scheme=url.split(":")[0], authenticated=bool(credentials)),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary).resolve()
                config = root / "config"
                config.mkdir()
                entry = dict(
                    public_url=url,
                    branch_url=url,
                    repository_uuid="",
                    branch_path="/",
                    resource_id="synthetic-resource",
                    secret_ref="",
                )
                if credentials:
                    with self.assertRaisesRegex(CodeKnowledgeError, "CODE_SVN_AUTH_FAILED"):
                        WorkingCopyClient(entry, root, config_directory=config)
                client = WorkingCopyClient(
                    entry, root, config_directory=config, credentials=credentials
                )
                assert client.source.branch_url == url
                assert client.browse(None)["revision"] == 2
                client.checkout(
                    root=root,
                    folder="checkout",
                    job_id="protocol-test",
                    revision=2,
                    paths=["module"],
                )
                key = persistent_identity(root / "checkout", create=True)
                copy = SvnWorkingCopy(
                    client.source, root / "checkout", ["module"], physical_key=key
                )
                assert copy.inspect(2)["operative_revision"] == 2
                assert copy.update(1, timeout=30)["operative_revision"] == 1
                assert not any(path.is_file() for path in (config / "auth").rglob("*"))

    def test_anonymous_connection_discovers_without_account_or_cached_credentials(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary).resolve()
            (config / "servers").write_text(
                "[global]\nssl-authority-files = " + os.environ["CODE_AUTH_SVN_CA"] + "\n"
            )
            url = os.environ["CODE_AUTH_SVN_URL"].replace("/repos/fixture/", "/public/fixture/")
            entry = dict(
                public_url=url,
                branch_url=url,
                repository_uuid="",
                branch_path="/",
                resource_id="synthetic-resource",
                secret_ref="",
            )
            client = WorkingCopyClient(entry, config, config_directory=config)
            assert client.source._credentials is None
            assert client.browse(None)["revision"] == 2
            assert client.source.branch_path == "/trunk"
            assert client.source.expected_uuid
            assert not any(path.is_file() for path in (config / "auth").rglob("*"))
            entry.update(
                public_url=os.environ["CODE_AUTH_SVN_URL"],
                branch_url=os.environ["CODE_AUTH_SVN_URL"],
            )
            with self.assertRaisesRegex(CodeKnowledgeError, "CODE_SVN_AUTH_FAILED"):
                WorkingCopyClient(entry, config, config_directory=config)

    def test_authenticated_browse_checkout_history_update_and_read(self):
        from app.modules.knowledge.infrastructure.code_checkout_identity import persistent_identity
        from app.modules.knowledge.infrastructure.code_working_copy import SvnWorkingCopy
        from app.python_runtime.code_checkout_reader import CodeCheckoutReader

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            config = root / "config"
            config.mkdir()
            (config / "servers").write_text(
                "[global]\nssl-authority-files = " + os.environ["CODE_AUTH_SVN_CA"] + "\n"
            )
            entry = dict(
                public_url=os.environ["CODE_AUTH_SVN_URL"],
                branch_url=os.environ["CODE_AUTH_SVN_URL"],
                repository_uuid="",
                branch_path="/",
                secret_ref="synthetic-only",
            )
            with self.assertRaisesRegex(CodeKnowledgeError, "CODE_SVN_AUTH_FAILED"):
                WorkingCopyClient(
                    entry,
                    root,
                    credentials=("synthetic-user", "incorrect"),
                    config_directory=config,
                )
            client = WorkingCopyClient(
                entry,
                root,
                credentials=("synthetic-user", "synthetic-password"),
                config_directory=config,
            )
            self.assertEqual(client.browse(None)["revision"], 2)
            client.checkout(
                root=root, folder="checkout", job_id="auth-test", revision=2, paths=["module"]
            )
            key = persistent_identity(root / "checkout", create=True)
            copy = SvnWorkingCopy(client.source, root / "checkout", ["module"], physical_key=key)
            self.assertEqual(copy.inspect(2)["operative_revision"], 2)
            self.assertIn(
                b"synthetic rule change",
                client.source._run("log", ["--xml", "-v", "-r", "2:1", client.source._target(2)]),
            )
            self.assertIn(
                b"release_allowed",
                client.source._run(
                    "diff", ["-r", "1:2", client.source._target(2, "module/rule.cpp")]
                ),
            )
            self.assertEqual(copy.update(1, timeout=30)["operative_revision"], 1)
            reader = CodeCheckoutReader(
                root,
                dict(
                    directory="checkout",
                    physical_key=key,
                    allowed_paths=["module"],
                    branch_path="trunk",
                    repository_uuid=client.source.expected_uuid,
                    revision=1,
                ),
            )
            self.assertEqual(reader.tracked("module/rule.cpp")["revision"], 1)
            self.assertEqual(persistent_identity(root / "checkout"), key)
            self.assertFalse(any(path.is_file() for path in (config / "auth").rglob("*")))
            untrusted = root / "untrusted"
            untrusted.mkdir()
            with self.assertRaisesRegex(CodeKnowledgeError, "CODE_SVN_CERTIFICATE_INVALID"):
                WorkingCopyClient(
                    entry,
                    root,
                    credentials=("synthetic-user", "synthetic-password"),
                    config_directory=untrusted,
                )


@unittest.skipUnless(
    shutil.which("svnadmin") and platform.system() == "Linux", "Linux SVN container required"
)
class WorkingCopyAcceptance(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        repository = self.root / "repo"
        subprocess.run(
            ["svnadmin", "create", str(repository)], check=True, stdout=subprocess.DEVNULL
        )
        self.url = repository.as_uri() + "/trunk"
        self.svn("mkdir", self.url, "-m", "synthetic trunk")
        source = self.root / "original"
        (source / "first/config").mkdir(parents=True)
        (source / "second/nested").mkdir(parents=True)
        (source / "first/config/settings.json").write_bytes(b'{"synthetic": true}\r\n')
        (source / "first/.env").write_text("SYNTHETIC=example\n")
        (source / "first/library.bin").write_bytes(b"\x00\xff\x12binary")
        (source / "first/link").symlink_to("library.bin")
        (source / "second/nested/rule.cpp").write_text("original rule\n")
        self.svn(
            "import",
            str(source),
            self.url,
            "--no-ignore",
            "--no-auto-props",
            "-m",
            "synthetic complete source",
        )
        config = self.root / "auth/fixture"
        config.mkdir(parents=True)
        entry = {
            "public_url": "https://synthetic.invalid/trunk",
            "branch_url": "https://synthetic.invalid/trunk",
            "repository_uuid": self.svn("info", "--show-item", "repos-uuid", self.url),
            "branch_path": "/trunk",
            "auth_ref": "fixture",
        }
        self.client = WorkingCopyClient(entry, config.parent)
        # Production constructor still rejects file://; only this isolated fixture replaces its reader.
        self.client.source = SvnCodeSource(
            branch_url=self.url,
            expected_uuid=entry["repository_uuid"],
            branch_path="/trunk",
            config_directory=config,
            allow_local_test=True,
        )

    def svn(self, *args):
        return (
            subprocess.check_output(
                ["svn", "--non-interactive", "--no-auth-cache", *args], stderr=subprocess.DEVNULL
            )
            .decode()
            .strip()
        )

    def test_complete_files_multiple_selection_and_pinned_revision(self):
        browse = self.client.browse(None)
        self.assertEqual(browse["revision"], 2)
        self.assertEqual(browse["files"], [])
        self.assertEqual(browse["directories"], ["first", "second"])
        first = self.client.browse(browse["revision"], path="first")
        self.assertEqual(first["directories"], ["first/config"])
        self.assertEqual(first["files"], ["first/.env", "first/library.bin", "first/link"])
        writer = self.root / "writer"
        self.svn("checkout", self.url, str(writer))
        (writer / "second/nested/rule.cpp").write_text("new rule\n")
        self.svn("commit", str(writer), "-m", "synthetic r3")
        child = self.client.browse(browse["revision"], path="second/nested")
        self.assertEqual(child["revision"], 2)
        self.assertEqual(child["files"], ["second/nested/rule.cpp"])
        result = self.client.checkout(
            root=self.root,
            folder="copy",
            job_id="test-one",
            revision=browse["revision"],
            paths=["first", "second/nested"],
        )
        self.assertEqual(result["revision"], 2)
        output = self.root / "copy"
        self.assertEqual(
            (output / "first/config/settings.json").read_bytes(), b'{"synthetic": true}\r\n'
        )
        self.assertEqual((output / "first/.env").read_text(), "SYNTHETIC=example\n")
        self.assertEqual((output / "first/library.bin").read_bytes(), b"\x00\xff\x12binary")
        self.assertTrue((output / "first/link").is_symlink())
        self.assertEqual((output / "second/nested/rule.cpp").read_text(), "original rule\n")
        self.assertEqual(self.svn("status", str(output)), "")
        self.assertFalse((self.root / ".partial-test-one").exists())
        with self.assertRaisesRegex(CodeKnowledgeError, "destination_exists"):
            self.client.checkout(
                root=self.root, folder="copy", job_id="test-two", revision=3, paths=[""]
            )

    def test_selected_files_and_directory_leave_unselected_siblings_absent(self):
        self.client.checkout(
            root=self.root,
            folder="files",
            job_id="mixed",
            revision=2,
            paths=["first/.env", "first/library.bin", "second/nested"],
        )
        output = self.root / "files"
        self.assertEqual((output / "first/.env").read_text(), "SYNTHETIC=example\n")
        self.assertEqual((output / "first/library.bin").read_bytes(), b"\x00\xff\x12binary")
        self.assertTrue((output / "second/nested/rule.cpp").is_file())
        self.assertFalse((output / "first/config").exists())
        self.assertFalse((output / "first/link").exists())
        self.assertEqual(self.svn("status", str(output)), "")
        self.client.checkout(
            root=self.root,
            folder="single",
            job_id="single-file",
            revision=2,
            paths=["second/nested/rule.cpp"],
        )
        self.assertEqual(
            (self.root / "single/second/nested/rule.cpp").read_text(), "original rule\n"
        )
        self.assertFalse((self.root / "single/first").exists())

    def test_reservation_refuses_even_an_empty_racing_directory(self):
        target = self.root / "destination"
        target.mkdir()
        with self.assertRaisesRegex(CodeKnowledgeError, "destination_exists"):
            with checkout_directory(target):
                self.fail("an existing directory must never be reused")
        self.assertTrue(target.is_dir())

    def test_real_svn_failure_preserves_numeric_diagnostic_without_path(self):
        with self.assertRaises(SvnCommandFailure) as caught:
            self.client.source._run(
                "info", ["--xml", self.url + "/synthetic-private-missing-file@2"]
            )
        diagnostic = caught.exception.diagnostic
        self.assertEqual(diagnostic["operation"], "info")
        self.assertEqual(diagnostic["exit_code"], 1)
        self.assertTrue(diagnostic["svn_error_codes"])
        for code in diagnostic["svn_error_codes"]:
            self.assertRegex(code, r"^E[0-9]{6}$")
        self.assertNotIn("private", str(diagnostic))
        self.assertNotIn(self.url, str(diagnostic))

    def test_real_pending_work_and_wc_lock_are_classified_without_repair(self):
        import sqlite3

        for folder, table, statement, native, classification in [
            (
                "pending",
                "WORK_QUEUE",
                "INSERT INTO WORK_QUEUE (work) VALUES (X'2873796E74686574696329')",
                "E155037",
                "CODE_SVN_WC_CLEANUP_REQUIRED",
            ),
            (
                "locked",
                "WC_LOCK",
                "INSERT INTO WC_LOCK (wc_id, local_dir_relpath, locked_levels) "
                "SELECT id, '', -1 FROM WCROOT",
                "E155004",
                "CODE_SVN_WC_LOCKED",
            ),
        ]:
            with self.subTest(state=folder):
                self.client.checkout(
                    root=self.root, folder=folder, job_id=folder, revision=2, paths=["first"]
                )
                directory = self.root / folder
                # Only this isolated synthetic fixture's SVN metadata is altered.
                # A deterministic pending queue/lock models an interrupted operation.
                with sqlite3.connect(directory / ".svn/wc.db") as database:
                    database.execute(statement)
                with self.assertRaises(SvnCommandFailure) as caught:
                    self.client.source.execute(
                        "update", ["-r", "2", str(directory) + "@"], timeout=10, limit=1024**2
                    )
                self.assertEqual(caught.exception.code, classification)
                self.assertIn(native, caught.exception.diagnostic["svn_error_codes"])
                self.assertEqual(caught.exception.diagnostic["operation"], "update")
                with sqlite3.connect(directory / ".svn/wc.db") as database:
                    self.assertEqual(
                        database.execute(f"SELECT count(*) FROM {table}").fetchone()[0], 1
                    )

    def test_checkout_does_not_require_noreplace_or_plain_rename(self):
        import ctypes
        import errno
        from types import SimpleNamespace
        from unittest.mock import Mock, patch

        def unsupported(*args):
            ctypes.set_errno(errno.EINVAL)
            return -1

        noreplace = Mock(side_effect=unsupported)
        root = self.root / "Windows 绑定盘"
        root.mkdir()
        with (
            patch("ctypes.CDLL", return_value=SimpleNamespace(renameat2=noreplace)),
            patch("os.rename", side_effect=AssertionError("unsafe rename fallback")),
            patch("os.replace", side_effect=AssertionError("unsafe replace fallback")),
        ):
            result = self.client.checkout(
                root=root,
                folder="sanjiu_mes1",
                job_id="no-noreplace",
                revision=2,
                paths=["first", "second/nested/rule.cpp"],
            )
        output = root / "sanjiu_mes1"
        self.assertEqual(result["container_directory"], str(output))
        self.assertEqual((output / "second/nested/rule.cpp").read_text(), "original rule\n")
        self.assertTrue((output / "first/link").is_symlink())
        self.assertEqual(self.svn("status", str(output)), "")
        self.assertEqual(self.svn("info", "--show-item", "revision", str(output)), "2")
        noreplace.assert_not_called()

    def test_download_failure_removes_only_reserved_directory(self):
        from unittest.mock import patch

        original_command = self.client._checkout_command

        def download(args, *, root):
            if args[0] == "update":
                self.assertTrue((root / "failed/.svn/wc.db").is_file())
                raise CodeKnowledgeError("CODE_SVN_UPDATE_TIMEOUT")
            original_command(args, root=root)

        with patch.object(self.client, "_checkout_command", side_effect=download):
            with self.assertRaisesRegex(CodeKnowledgeError, "CODE_SVN_UPDATE_TIMEOUT"):
                self.client.checkout(
                    root=self.root, folder="failed", job_id="failed", revision=2, paths=["first"]
                )
        self.assertFalse((self.root / "failed").exists())
        self.assertTrue((self.root / "repo").is_dir())

    def test_whole_directory_and_two_sibling_children_without_parent_selection(self):
        for kind in ("file", "directory"):
            with self.subTest(kind=kind):
                fixture = self.root / ("selection-" + kind)
                (fixture / "A").mkdir(parents=True)
                (fixture / "B").mkdir()
                for name in ("a", "b", "c"):
                    (fixture / "A" / name).write_text("synthetic complete A")
                for name in ("d", "e", "f"):
                    child = fixture / "B" / name
                    if kind == "directory":
                        child.mkdir()
                        child = child / "file.cpp"
                    child.write_text("synthetic selected child")
                self.svn("import", str(fixture), self.url + "/" + kind, "-m", "selection fixture")
                revision = int(self.svn("info", "--show-item", "revision", self.url))
                self.client.checkout(
                    root=self.root,
                    folder="selected-" + kind,
                    job_id="selected-" + kind,
                    revision=revision,
                    paths=[kind + "/A", kind + "/B/d", kind + "/B/e"],
                )
                output = self.root / ("selected-" + kind) / kind
                self.assertEqual(sorted(p.name for p in (output / "A").iterdir()), ["a", "b", "c"])
                self.assertEqual(sorted(p.name for p in (output / "B").iterdir()), ["d", "e"])
                self.assertEqual(self.svn("status", str(output)), "")

    def test_externals_precheck_covers_only_selected_directories_for_checkout_and_update(self):
        from app.modules.knowledge.infrastructure.code_checkout_identity import persistent_identity
        from app.modules.knowledge.infrastructure.code_working_copy import SvnWorkingCopy

        writer = self.root / "writer"
        self.svn("checkout", self.url, str(writer))
        for path in (writer, writer / "first", writer / "second"):
            self.svn("propset", "svn:externals", "^/unselected-do-not-fetch external", str(path))
        self.svn("commit", str(writer), "-m", "unselected external declarations")
        original_run = self.client.source._run
        checked = []
        budgets = []

        def run(operation, args, *, timeout=60):
            budgets.append((operation, timeout))
            if operation == "propget":
                checked.append(args[-1])
            return original_run(operation, args, timeout=timeout)

        self.client.source._run = run
        paths = ["first/config", "second/nested/rule.cpp"]
        self.client.checkout(
            root=self.root, folder="scoped", job_id="scoped", revision=3, paths=paths
        )
        output = self.root / "scoped"
        working = SvnWorkingCopy(
            self.client.source,
            output,
            paths,
            physical_key=persistent_identity(output, create=True),
        )
        (writer / "second/nested/rule.cpp").write_text("updated selected rule\n")
        self.svn("commit", str(writer), "-m", "selected update")
        self.assertEqual(working.update(4, timeout=30)["operative_revision"], 4)
        self.assertEqual(checked, [self.url + "/first/config@3", self.url + "/first/config@4"])
        self.assertTrue(
            all(timeout == 300 for op, timeout in budgets if op in {"status", "propget", "list"})
        )
        self.assertIn(("info", 300), budgets)
        self.assertFalse((output / "first/library.bin").exists())
        self.assertFalse((output / "external").exists())

        self.svn(
            "propset",
            "svn:externals",
            "^/selected-do-not-fetch external",
            str(writer / "first/config"),
        )
        self.svn("commit", str(writer), "-m", "selected external declaration")
        with self.assertRaisesRegex(CodeKnowledgeError, "CODE_CHECKOUT_EXTERNALS_UNSUPPORTED"):
            working.update(5, timeout=30)
        self.assertEqual(working.inspect(4)["operative_revision"], 4)
        with self.assertRaisesRegex(CodeKnowledgeError, "code_checkout_externals_unsupported"):
            self.client.checkout(
                root=self.root, folder="blocked", job_id="blocked", revision=5, paths=paths
            )
        self.assertFalse((self.root / "blocked").exists())

    def test_slow_local_inspection_renews_claim_and_still_honors_revocation(self):
        from app.modules.knowledge.infrastructure.code_checkout_identity import persistent_identity
        from app.modules.knowledge.infrastructure.code_working_copy import SvnWorkingCopy

        self.client.checkout(
            root=self.root,
            folder="slow-inspection",
            job_id="slow-inspection",
            revision=2,
            paths=["first/config"],
        )
        output = self.root / "slow-inspection"
        working = SvnWorkingCopy(
            self.client.source,
            output,
            ["first/config"],
            physical_key=persistent_identity(output, create=True),
        )
        original_entry = working._entry
        elapsed, renewed, denied = 0, 0, False

        def check():
            nonlocal renewed
            if denied:
                raise CodeKnowledgeError("CODE_CONFIGURATION_CHANGED")
            if elapsed - renewed >= 30:
                raise CodeKnowledgeError("CODE_OPERATION_LEASE_LOST")
            renewed = elapsed
            return False

        def slow_entry(node):
            nonlocal elapsed
            # Virtual time models slow filesystem metadata without a timed sleep.
            elapsed += 12
            return original_entry(node)

        self.client.source.cancelled = check
        working._entry = slow_entry
        self.assertEqual(working.inspect(2)["operative_revision"], 2)
        self.assertGreater(elapsed, 30)
        self.assertEqual(renewed, elapsed)

        def revoked_entry(node):
            nonlocal denied
            denied = True
            return original_entry(node)

        working._entry = revoked_entry
        with self.assertRaisesRegex(CodeKnowledgeError, "CODE_CONFIGURATION_CHANGED"):
            working.inspect(2)

    def test_update_checks_externals_when_selected_file_becomes_directory(self):
        from app.modules.knowledge.infrastructure.code_checkout_identity import persistent_identity
        from app.modules.knowledge.infrastructure.code_working_copy import SvnWorkingCopy

        paths = ["second/nested/rule.cpp"]
        self.client.checkout(
            root=self.root, folder="kind-change", job_id="kind-change", revision=2, paths=paths
        )
        output = self.root / "kind-change"
        working = SvnWorkingCopy(
            self.client.source,
            output,
            paths,
            physical_key=persistent_identity(output, create=True),
        )
        writer = self.root / "writer"
        self.svn("checkout", self.url, str(writer))
        replaced = writer / paths[0]
        self.svn("delete", str(replaced))
        replaced.mkdir()
        (replaced / "rule.cpp").write_text("synthetic replacement")
        self.svn("add", str(replaced))
        self.svn("propset", "svn:externals", "^/do-not-fetch external", str(replaced))
        self.svn("commit", str(writer), "-m", "file becomes directory with external")
        with self.assertRaisesRegex(CodeKnowledgeError, "CODE_CHECKOUT_EXTERNALS_UNSUPPORTED"):
            working.update(3, timeout=30)
        self.assertEqual(working.inspect(2)["operative_revision"], 2)
        self.assertTrue((output / paths[0]).is_file())

    def test_invalid_selection_preserves_unrelated_directory(self):
        kept = self.root / "manual"
        kept.mkdir()
        (kept / "keep.txt").write_text("keep")
        with self.assertRaises(CodeKnowledgeError):
            self.client.checkout(
                root=self.root,
                folder="failed",
                job_id="test-bad-path",
                revision=2,
                paths=["absent"],
            )
        self.assertFalse((self.root / "failed").exists())
        self.assertFalse((self.root / ".partial-test-bad-path").exists())
        self.assertEqual((kept / "keep.txt").read_text(), "keep")
