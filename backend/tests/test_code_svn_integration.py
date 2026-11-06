"""An isolated local SVN repository, never the production SVN or MES runtime."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError, COMPONENTS
from app.modules.knowledge.infrastructure.code_svn import SvnCodeSource
from app.modules.knowledge.infrastructure.code_source import LocalCodeCollector
from app.modules.knowledge.infrastructure.code_svn_admission import (
    SvnSourceAdmission,
    compare_baseline,
)


@unittest.skipUnless(shutil.which("svn") and shutil.which("svnadmin"), "local SVN tools required")
class LocalSvnAcceptance(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="code-svn-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = self.root / "auth"
        self.config.mkdir()
        self.url, self.workspace, self.source = self.repository("main")
        self.external_url, self.external_workspace, self.external = self.repository("external")
        for component in COMPONENTS.values():
            (self.workspace / component).mkdir(parents=True)
        self.order = self.workspace / "set_server/order.cpp"
        self.order.write_text("if (a.empty()) return reject;\nreturn accepted;\n")
        (self.workspace / "set_server/temp.cpp").write_text("return 1;\n")
        (self.external_workspace / "rule.cpp").write_text("return external_rule;\n")
        self.svn("add", str(self.workspace / "set_server"), str(self.workspace / "set_web"))
        self.svn("add", str(self.external_workspace / "rule.cpp"))
        self.commit(self.workspace)
        self.commit(self.external_workspace)

    def svn(self, *args):
        return (
            subprocess.check_output(
                [
                    "svn",
                    "--non-interactive",
                    "--no-auth-cache",
                    "--config-dir",
                    str(self.config),
                    *args,
                ],
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )

    def commit(self, workspace):
        self.svn("commit", str(workspace), "-m", "synthetic acceptance change")
        self.svn("update", str(workspace), "--ignore-externals")

    def repository(self, name):
        repository = self.root / name
        subprocess.run(
            ["svnadmin", "create", str(repository)], check=True, stdout=subprocess.DEVNULL
        )
        url = repository.as_uri() + "/trunk"
        self.svn("mkdir", url, "-m", "synthetic repository")
        workspace = self.root / (name + "-working")
        self.svn("checkout", url, str(workspace), "--ignore-externals")
        source = SvnCodeSource(
            branch_url=url,
            expected_uuid=self.svn("info", "--show-item", "repos-uuid", url),
            branch_path="/trunk",
            config_directory=self.config,
            allow_local_test=True,
        )
        return url, workspace, source

    def test_encoded_branch_name_still_verifies_identity(self):
        from urllib.parse import quote

        branch = "/版本 分支"
        url = self.url.rsplit("/", 1)[0] + quote(branch)
        self.svn("copy", self.url + "@2", url, "-m", "synthetic branch")
        source = SvnCodeSource(
            branch_url=url,
            expected_uuid=self.source.expected_uuid,
            branch_path=branch,
            config_directory=self.config,
            allow_local_test=True,
        )
        self.assertEqual(source.head(), 3)
        source.preflight_components(3, dict(COMPONENTS))
        self.assertEqual(source.content("set_server/order.cpp", 3), self.order.read_bytes())

    def test_pinned_revision_copy_move_replace_properties_and_new_commit(self):
        self.source.preflight_components(2, dict(COMPONENTS))
        original = self.source.content("set_server/order.cpp", 2)
        self.order.write_text("return accepted;\n")
        self.commit(self.workspace)  # r3 relaxes the guard.
        pinned = self.source.head()
        self.assertEqual(pinned, 3)
        self.order.write_bytes(original)
        self.svn(
            "move",
            str(self.workspace / "set_server/temp.cpp"),
            str(self.workspace / "set_server/moved.cpp"),
        )
        self.svn("copy", str(self.order), str(self.workspace / "set_server/copied.cpp"))
        self.svn("propset", "test:policy", "restored", str(self.order))
        self.commit(self.workspace)  # r4 restores it and moves/copies a file.
        copied = self.workspace / "set_server/copied.cpp"
        self.svn("delete", str(copied))
        copied.write_text("return replacement;\n")
        self.svn("add", str(copied))
        self.commit(self.workspace)  # r5 replacement.
        self.assertEqual(self.source.content("set_server/order.cpp", pinned), b"return accepted;\n")
        self.assertEqual(self.source.content("set_server/order.cpp", 4), original)
        self.assertEqual(
            [row["revision"] for row in self.source.commits(after=2, target=pinned)], [3]
        )
        log = self.source.commits(after=2, target=5)
        self.assertEqual([row["revision"] for row in log], [3, 4, 5])
        paths = log[1]["paths"]
        self.assertTrue(any(p["action"] == "D" and p["path"].endswith("temp.cpp") for p in paths))
        self.assertTrue(any(p["action"] == "A" and p["copy_from_revision"] == 3 for p in paths))
        self.assertTrue(any(p["properties_modified"] == "true" for p in paths))
        self.assertTrue(any(p["action"] == "R" for p in log[2]["paths"]))
        self.assertTrue(self.source.changed_paths(4))
        with self.assertRaises(CodeKnowledgeError):
            self.source.preflight_components(5, {**COMPONENTS, "backend": "outside_branch"})

    def test_external_allowlist_pinning_and_independent_change(self):
        self.svn(
            "propset",
            "svn:externals",
            "--",
            f"-r2 {self.external_url}@2 set_server/library",
            str(self.workspace),
        )
        self.commit(self.workspace)
        self.assertFalse(self.source.external_declarations(3)["complete"])
        approved = {"set_server/library": self.external}
        pinned = self.source.external_declarations(3, approved=approved)
        self.assertTrue(pinned["complete"])
        self.assertEqual(pinned["declarations"][0]["revision"], 2)
        (self.external_workspace / "rule.cpp").write_text("return changed_rule;\n")
        self.commit(self.external_workspace)
        self.assertEqual(self.source.external_declarations(3, approved=approved), pinned)
        self.svn(
            "propset",
            "svn:externals",
            f"{self.external_url} set_server/library",
            str(self.workspace),
        )
        self.commit(self.workspace)
        self.assertFalse(self.source.external_declarations(4, approved=approved)["complete"])
        first = self.source.external_declarations(4, approved=approved, capture_floating=True)
        (self.external_workspace / "rule.cpp").write_text("return changed_again;\n")
        self.commit(self.external_workspace)
        second = self.source.external_declarations(4, approved=approved, capture_floating=True)
        self.assertEqual(first["declarations"][0]["revision"], 3)
        self.assertEqual(second["declarations"][0]["revision"], 4)
        self.assertEqual(self.source.head(), 4)

    def test_admission_matches_baseline_filters_before_persisting_and_pins_bytes(self):
        local = LocalCodeCollector(self.workspace).freeze()
        admission = SvnSourceAdmission(self.source, dict(COMPONENTS))
        with admission.prepare(2) as (_, frozen):
            self.assertEqual(compare_baseline(local.manifest, frozen.manifest)["state"], "VERIFIED")
        config = self.workspace / "set_server/config"
        config.mkdir()
        (config / "private.cpp").write_text("synthetic excluded configuration")
        (self.workspace / "set_server/sensitive.cpp").write_text(
            'password = "synthetic-test-value";'
        )
        (self.workspace / "set_server/link.cpp").symlink_to("order.cpp")
        self.svn(
            "add",
            str(config),
            str(self.workspace / "set_server/sensitive.cpp"),
            str(self.workspace / "set_server/link.cpp"),
        )
        self.commit(self.workspace)
        fetched = []
        original = self.source.content

        def content(path, revision):
            fetched.append(path)
            return original(path, revision)

        self.source.content = content
        with admission.prepare(3) as (collector, frozen):
            self.assertNotIn("set_server/config/private.cpp", fetched)
            self.assertNotIn("set_server/link.cpp", fetched)
            self.assertFalse((collector.root / "set_server/sensitive.cpp").exists())
            self.assertEqual(len(frozen.files), 2)
            self.assertEqual(compare_baseline(local.manifest, frozen.manifest)["state"], "UNMAPPED")
            collector.verify_stable(frozen.manifest)
            self.order.write_text("newer uncommitted work\n")
            self.assertTrue(any("a.empty" in file.text for file in frozen.files.values()))

    def test_external_bytes_are_frozen_and_unknown_historical_external_is_incomplete(self):
        self.svn(
            "propset",
            "svn:externals",
            f"{self.external_url} set_server/library",
            str(self.workspace),
        )
        self.commit(self.workspace)
        admission = SvnSourceAdmission(
            self.source, dict(COMPONENTS), externals={"set_server/library": self.external}
        )
        with admission.prepare(3) as (_, historical):
            self.assertFalse(historical.manifest["scan_complete"])
        with admission.prepare(3, capture_floating=True) as (_, first):
            self.assertTrue(first.manifest["scan_complete"])
            self.assertTrue(
                any(file.path == "set_server/library/rule.cpp" for file in first.files.values())
            )
        (self.external_workspace / "rule.cpp").write_text("return independently_changed;\n")
        self.commit(self.external_workspace)
        with admission.prepare(3, capture_floating=True) as (_, second):
            self.assertNotEqual(
                first.source_ref["manifest_hash"], second.source_ref["manifest_hash"]
            )
            self.assertEqual(first.source_ref["revision"], second.source_ref["revision"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
