import json
import shutil
import tempfile
import unittest
from pathlib import Path

from analyzer import AnalysisGap, PROFILES, analyze, parse_rule
from worker import Engine, run

FIXTURES = Path(__file__).with_name("fixtures")


class AnalyzerTests(unittest.TestCase):
    def test_wrong_comments_do_not_define_rules(self):
        facts, evidence = analyze(FIXTURES)
        approval, quantity, submission, schema = facts
        self.assertIn("不超过100000", approval["rule"])
        self.assertEqual([e["result"] for e in approval["examples"]], ["通过", "不通过", "通过"])
        self.assertIn("不超过100", quantity["rule"])
        self.assertEqual(
            [e["result"] for e in quantity["examples"]], ["不通过", "通过", "通过", "不通过"]
        )
        self.assertIn("不代表后端授权", submission["scope"])
        self.assertEqual([e["result"] for e in submission["examples"]], ["不通过", "通过"])
        self.assertEqual(
            [f["name"] for f in schema["fields"]], ["id", "amount_cents", "quantity", "approved"]
        )
        self.assertEqual(len(evidence), 4)

    def test_threshold_is_read_from_expression_not_preset_answer(self):
        source = (FIXTURES / "OrderPolicy.java").read_text().replace("100000", "90000")
        self.assertIn("不超过90000", parse_rule(source, PROFILES[0])["rule"])

    def test_wrong_comment_changes_nothing(self):
        source = (FIXTURES / "OrderPolicy.java").read_text()
        self.assertEqual(
            parse_rule(source, PROFILES[0]),
            parse_rule(source + "\n// 12345 everything rejected", PROFILES[0]),
        )

    def test_and_is_distinguished_from_or(self):
        source = (FIXTURES / "OrderPolicy.java").read_text().replace("||", "&&")
        result = parse_rule(source, PROFILES[0])
        self.assertIn("并且", result["rule"])
        self.assertEqual([e["result"] for e in result["examples"]], ["不通过", "不通过", "不通过"])

    def test_strict_numeric_boundary(self):
        source = (FIXTURES / "quantity.cpp").read_text().replace("<= 100", "< 80")
        result = parse_rule(source, PROFILES[1])
        self.assertEqual(
            [e["result"] for e in result["examples"]], ["不通过", "通过", "不通过", "不通过"]
        )

    def test_unrecognized_semantics_fail_closed(self):
        source = (FIXTURES / "OrderPolicy.java").read_text()
        variants = [
            source.replace("amountCents <= 100000 || finance", "unknownPolicy()"),
            source.replace("return ", "if (finance) return true; return "),
            source.replace("int amountCents", "long amountCents"),
            source.replace("100000", '"raw-source-canary"'),
            "import java.lang.reflect.*;\n" + source,
            source.replace("amountCents <= 100000", "amountCents + 1 <= 100000"),
        ]
        for variant in variants:
            with self.subTest(variant=variants.index(variant)), self.assertRaises(AnalysisGap):
                parse_rule(variant, PROFILES[0])

    def test_vue_template_change_is_not_ignored(self):
        source = (FIXTURES / "OrderForm.vue").read_text().replace("!canSubmit(approved)", "false")
        with self.assertRaises(AnalysisGap):
            parse_rule(source, PROFILES[2])

    def test_cpp_macro_is_not_silently_ignored(self):
        source = "#define quantity 1\n" + (FIXTURES / "quantity.cpp").read_text()
        with self.assertRaises(AnalysisGap):
            parse_rule(source, PROFILES[1])

    def test_unknown_files_and_symlinks_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "source"
            shutil.copytree(FIXTURES, root)
            (root / "other.java").write_text("class Other {}")
            with self.assertRaises(AnalysisGap):
                analyze(root)
            (root / "other.java").unlink()
            (root / "quantity.cpp").unlink()
            (root / "quantity.cpp").symlink_to(FIXTURES / "quantity.cpp")
            with self.assertRaises(AnalysisGap):
                analyze(root)


class SvnTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.engine = Engine(root / "private", root / "public", FIXTURES)

    def tearDown(self):
        self.temp.cleanup()

    def count_events(self):
        with self.engine.connect() as conn:
            return conn.execute("SELECT count(*) FROM events").fetchone()[0]

    def test_baseline_has_no_fabricated_history(self):
        self.engine.sync_once()
        self.assertEqual(self.engine.status()["applied"], 1)
        self.assertEqual(self.count_events(), 0)

    def test_commits_during_baseline_are_not_lost(self):
        self.engine.commit("tighten")
        self.engine.sync_once()
        self.assertEqual(self.engine.status()["baseline"], 1)
        self.assertEqual(self.engine.status()["applied"], 2)
        self.assertEqual(self.count_events(), 2)

    def test_changes_comments_revert_and_idempotent_replay(self):
        self.engine.sync_once()
        for scenario in ("tighten", "comment", "restore"):
            self.engine.commit(scenario)
        self.engine.sync_once()
        self.engine.sync_once()
        self.assertEqual(self.engine.status()["applied"], 4)
        self.assertEqual(self.count_events(), 4)
        with self.engine.connect() as conn:
            self.assertEqual(
                conn.execute("SELECT outcome FROM commits WHERE revision=3").fetchone()[0],
                "NO_BUSINESS_CHANGE",
            )
            body = conn.execute("SELECT body FROM facts WHERE id='approval'").fetchone()[0]
            self.assertIn("不超过100000", json.loads(body)["rule"])
            self.assertNotIn("condition", json.loads(body))

    def test_unrelated_commit_advances_without_business_event(self):
        self.engine.sync_once()
        self.engine.commit("unrelated")
        self.engine.sync_once()
        self.assertEqual(self.engine.status()["applied"], 2)
        self.assertEqual(self.count_events(), 0)

    def test_pause_resume_and_restart(self):
        self.engine.sync_once()
        self.engine.paused = True
        self.engine.commit("tighten")
        self.engine.sync_once()
        self.assertEqual(self.engine.status()["applied"], 1)
        self.engine.paused = False
        self.engine.sync_once()
        restarted = Engine(self.engine.private, self.engine.public, FIXTURES)
        restarted.sync_once()
        self.assertEqual(restarted.status()["applied"], 2)
        self.assertEqual(self.count_events(), 2)

    def test_failed_analysis_does_not_activate_or_skip(self):
        self.engine.sync_once()
        source = self.engine.wc / "OrderPolicy.java"
        source.write_text(source.read_text().replace("100000", "unknown()"))
        run("svn", "commit", str(self.engine.wc), "-m", "不支持的语义测试")
        self.engine.commit("comment")
        self.engine.sync_once()
        self.assertEqual(self.engine.status()["applied"], 1)
        self.assertEqual(self.engine.error, "analysis_incomplete")
        self.assertEqual(self.count_events(), 0)

    def test_public_store_has_no_source_or_private_evidence(self):
        self.engine.sync_once()
        with self.engine.connect() as conn:
            dump = "\n".join(conn.iterdump())
        for canary in (
            "return amountCents",
            "canApprove",
            "OrderPolicy.java",
            "sha256",
            "Deliberately",
            "CREATE TABLE orders",
        ):
            self.assertNotIn(canary, dump)


if __name__ == "__main__":
    unittest.main()
