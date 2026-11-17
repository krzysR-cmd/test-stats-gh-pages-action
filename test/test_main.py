import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import datetime as dt


SOURCE = Path(__file__).parents[1] / "src" / "main.py"
SPEC = importlib.util.spec_from_file_location("main", SOURCE)
main = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(main)


class StatsActionTests(unittest.TestCase):
    def test_junit_counts_success_failure_and_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "results.xml"
            path.write_text(
                '<testsuites><testsuite><testcase name="pass" time="0.5"/>'
                '<testcase name="fail"><failure message="broken"/></testcase>'
                '<testcase name="skip"><skipped/></testcase></testsuite></testsuites>'
            )
            counts, failures, flaky = main.parse_junit(path)
        self.assertEqual((counts["total"], counts["passed"], counts["failed"], counts["skipped"]), (3, 1, 1, 1))
        self.assertEqual(failures[0]["error"], "broken")
        self.assertEqual(flaky, [])

    def test_playwright_flaky_is_passed_and_counted_separately(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "results.json"
            path.write_text(json.dumps({
                "stats": {"expected": 2, "unexpected": 1, "flaky": 1, "skipped": 1, "duration": 900},
                "suites": [],
            }))
            counts, _, _ = main.parse_playwright(path)
        self.assertEqual(
            (counts["total"], counts["passed"], counts["failed"], counts["skipped"], counts["flaky"]),
            (5, 3, 1, 1, 1),
        )

    def test_missing_result_fails_explicitly(self):
        with patch.dict(os.environ, {"INPUT_RESULT_FILES": "/missing/results.xml"}):
            with self.assertRaises(SystemExit) as exc:
                main.input_paths()
        self.assertEqual(exc.exception.code, 1)

    def test_dashboard_url_must_be_an_absolute_http_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / "summary"
            with patch.dict(os.environ, {
                "GITHUB_STEP_SUMMARY": str(summary),
                "INPUT_DASHBOARD_URL": "javascript:alert(1)",
            }, clear=True):
                with self.assertRaises(SystemExit) as exc:
                    main.write_summary("CI tests", {"passed": 1, "failed": 0, "skipped": 0, "total": 1})
        self.assertEqual(exc.exception.code, 1)

    def test_junit_rejects_non_junit_xml(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "not-junit.xml"
            path.write_text("<root/>")
            with self.assertRaises(SystemExit) as exc:
                main.parse_junit(path)
        self.assertEqual(exc.exception.code, 1)

    def test_action_updates_history_and_writes_github_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            results = root / "junit.xml"
            results.write_text('<testsuite><testcase name="ok"/></testsuite>')
            output = root / "output"
            summary = root / "summary"
            now = dt.datetime.now(dt.timezone.utc)
            old_timestamp = (now - dt.timedelta(days=45)).isoformat().replace("+00:00", "Z")
            recent_timestamp = (now - dt.timedelta(days=2)).isoformat().replace("+00:00", "Z")
            runs_path = root / "site" / "reusable-stats" / "runs.json"
            runs_path.parent.mkdir(parents=True)
            runs_path.write_text(json.dumps({"runs": [
                {"run_id": "old", "timestamp": old_timestamp},
                {"run_id": "recent", "timestamp": recent_timestamp},
            ]}))
            env = {
                "INPUT_RESULT_FILES": str(results),
                "INPUT_FORMAT": "auto",
                "INPUT_SITE_DIRECTORY": str(root / "site"),
                "INPUT_STATS_SUBDIRECTORY": "reusable-stats",
                "INPUT_HISTORY_DAYS": "30",
                "INPUT_REPORT_NAME": "CI tests",
                "INPUT_DASHBOARD_URL": "https://owner.github.io/repo/reusable-stats/",
                "GITHUB_RUN_NUMBER": "42",
                "GITHUB_RUN_ID": "42",
                "GITHUB_SERVER_URL": "https://github.com",
                "GITHUB_REPOSITORY": "owner/repo",
                "GITHUB_OUTPUT": str(output),
                "GITHUB_STEP_SUMMARY": str(summary),
            }
            with patch.dict(os.environ, env, clear=True):
                main.main()
            stored = json.loads(runs_path.read_text())
            self.assertEqual([item["run_id"] for item in stored["runs"]], ["recent", "42"])
            self.assertTrue((runs_path.parent / "index.html").is_file())
            self.assertIn("passed**", summary.read_text())
            self.assertIn(
                "[View test statistics dashboard](https://owner.github.io/repo/reusable-stats/)",
                summary.read_text(),
            )
            self.assertIn("total=1", output.read_text())

    def test_action_aggregates_junit_and_playwright_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            junit = root / "shell-tests.xml"
            junit.write_text('<testsuite><testcase name="shell pass"/></testsuite>')
            playwright = root / "results.json"
            playwright.write_text(json.dumps({
                "stats": {"expected": 2, "unexpected": 1, "flaky": 1, "skipped": 1, "duration": 900},
                "suites": [],
            }))
            runs_path = root / "site" / "stats" / "runs.json"
            env = {
                "INPUT_RESULT_FILES": f"{junit}\n{playwright}",
                "INPUT_FORMAT": "auto",
                "INPUT_SITE_DIRECTORY": str(root / "site"),
                "INPUT_HISTORY_DAYS": "30",
                "INPUT_REPORT_NAME": "CI tests",
                "GITHUB_RUN_NUMBER": "17",
            }
            with patch.dict(os.environ, env, clear=True):
                main.main()
            run = json.loads(runs_path.read_text())["runs"][0]
            self.assertEqual(
                (run["total"], run["passed"], run["failed"], run["skipped"], run["flaky_count"]),
                (6, 4, 1, 1, 1),
            )


if __name__ == "__main__":
    unittest.main()
