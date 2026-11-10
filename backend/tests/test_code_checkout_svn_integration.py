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
    publish_directory,
)
from app.modules.knowledge.infrastructure.code_svn import SvnCodeSource


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
        self.assertEqual(
            browse["files"],
            [
                "first/.env",
                "first/config/settings.json",
                "first/library.bin",
                "first/link",
                "second/nested/rule.cpp",
            ],
        )
        writer = self.root / "writer"
        self.svn("checkout", self.url, str(writer))
        (writer / "second/nested/rule.cpp").write_text("new rule\n")
        self.svn("commit", str(writer), "-m", "synthetic r3")
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

    def test_atomic_publish_refuses_even_an_empty_racing_directory(self):
        source, target = self.root / "partial", self.root / "destination"
        source.mkdir()
        target.mkdir()
        with self.assertRaisesRegex(CodeKnowledgeError, "destination_exists"):
            publish_directory(source, target)
        self.assertTrue(source.is_dir())
        self.assertTrue(target.is_dir())

    def test_failure_cleans_only_own_temporary_directory(self):
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
