import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).parents[1] / "src" / "update-stats.sh"


class DetailedStatsTests(unittest.TestCase):
    def test_lists_all_tests_and_marks_new_or_changed_statuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            results = root / "results"
            results.mkdir()
            shell_xml = root / "shell.xml"
            site = root / "site"

            def write_results(tests, shell_failure=False):
                (results / "playwright.json").write_text(json.dumps({
                    "stats": {
                        "expected": sum(status == "expected" for _, status in tests),
                        "unexpected": sum(status == "unexpected" for _, status in tests),
                        "flaky": sum(status == "flaky" for _, status in tests),
                        "skipped": sum(status == "skipped" for _, status in tests),
                        "duration": 1200,
                    },
                    "suites": [{
                        "title": "suite",
                        "specs": [{
                            "title": title,
                            "file": "tests/example.spec.js",
                            "tests": [{"status": status, "results": []}],
                        } for title, status in tests],
                    }],
                }))
                failure = '<failure message="failed"/>' if shell_failure else ""
                shell_xml.write_text(
                    '<testsuites><testsuite name="shell">'
                    f'<testcase classname="sh" name="check">{failure}</testcase>'
                    '</testsuite></testsuites>'
                )

            def run(number):
                env = os.environ.copy()
                env.update({
                    "RESULTS_DIR": str(results),
                    "SITE_DIR": str(site),
                    "SHELL_TESTS_XML": str(shell_xml),
                    "GITHUB_RUN_NUMBER": str(number),
                    "GITHUB_RUN_ID": f"run-{number}",
                    "GITHUB_SERVER_URL": "https://github.com",
                    "GITHUB_REPOSITORY": "owner/repo",
                })
                subprocess.run(["bash", str(SCRIPT)], check=True, env=env, capture_output=True, text=True)

            write_results([("stable", "expected"), ("changes", "expected")])
            run(1)
            write_results([
                ("stable", "expected"),
                ("changes", "unexpected"),
                ("added", "expected"),
            ], shell_failure=True)
            run(2)

            store = json.loads((site / "stats" / "runs.json").read_text())
            latest = store["runs"][-1]
            tests = {(test["source"], test["title"]): test for test in latest["tests"]}
            dashboard = (site / "stats" / "index.html").read_text()

            self.assertEqual(len(latest["tests"]), 4)
            self.assertNotIn("change", tests[("Playwright", "suite > stable")])
            self.assertEqual(tests[("Playwright", "suite > added")]["change"], "new")
            self.assertEqual(tests[("Playwright", "suite > changes")]["previous_status"], "passed")
            self.assertEqual(tests[("Playwright", "suite > changes")]["status"], "failed")
            self.assertEqual(tests[("JUnit", "shell > check")]["change"], "changed")
            self.assertIn("Compared with run #1", dashboard)
            self.assertIn("New</span>", dashboard)
            self.assertIn("passed &rarr; failed", dashboard)
            self.assertIn("test-trend-match", dashboard)

    def test_preserves_rolling_failure_flaky_runtime_and_shell_statistics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            results = root / "results"
            results.mkdir()
            (results / "playwright.json").write_text(json.dumps({
                "stats": {"expected": 2, "unexpected": 1, "flaky": 1, "skipped": 1, "duration": 1200},
                "suites": [{
                    "title": "suite",
                    "specs": [{
                        "title": "fails",
                        "file": "tests/example.spec.js",
                        "tests": [{
                            "status": "unexpected",
                            "results": [{"duration": 300, "errors": [{"message": "failure detail"}]}],
                        }],
                    }],
                }],
            }))
            shell_xml = root / "shell.xml"
            shell_xml.write_text(
                '<testsuites><testsuite name="syntax">'
                '<testcase classname="sh" name="pass"/>'
                '<testcase classname="sh" name="fail"><failure message="shell failure"/></testcase>'
                '<testcase classname="sh" name="skip"><skipped/></testcase>'
                '</testsuite></testsuites>'
            )
            site = root / "site"
            env = os.environ.copy()
            env.update({
                "RESULTS_DIR": str(results),
                "SITE_DIR": str(site),
                "SHELL_TESTS_XML": str(shell_xml),
                "GITHUB_RUN_NUMBER": "23",
                "GITHUB_RUN_ID": "run-23",
                "GITHUB_SERVER_URL": "https://github.com",
                "GITHUB_REPOSITORY": "owner/repo",
            })
            subprocess.run(["bash", str(SCRIPT)], check=True, env=env, capture_output=True, text=True)
            store = json.loads((site / "stats" / "runs.json").read_text())
            run = store["runs"][0]
            dashboard = (site / "stats" / "index.html").read_text()

            self.assertEqual((run["total"], run["passed"], run["failed"], run["skipped"]), (5, 2, 1, 1))
            self.assertEqual((run["shell_passed"], run["shell_failed"], run["shell_skipped"]), (1, 1, 1))
            self.assertIn("failure detail", run["failed_tests"][0]["error"])
            self.assertIn("Test trends (last 30 days)", dashboard)
            self.assertIn("shell failure", run["shell_failed_tests"][0]["error"])

    def test_records_shell_failure_when_playwright_results_are_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            results = root / "results"
            results.mkdir()
            shell_xml = root / "shell.xml"
            shell_xml.write_text(
                '<testsuites><testsuite name="shell-tests" tests="2" failures="1">'
                '<testcase classname="other-test" name="passes"/>'
                '<testcase classname="scrape-csrf-extraction" '
                'name="scrape-csrf-extraction / current-csrf-meta-name">'
                '<failure message=\'expected "current123XYZ", got ""\'/>'
                '</testcase></testsuite></testsuites>'
            )
            site = root / "site"
            env = os.environ.copy()
            env.update({
                "RESULTS_DIR": str(results),
                "SITE_DIR": str(site),
                "SHELL_TESTS_XML": str(shell_xml),
                "GITHUB_RUN_NUMBER": "371",
                "GITHUB_RUN_ID": "run-371",
                "GITHUB_SERVER_URL": "https://github.com",
                "GITHUB_REPOSITORY": "owner/repo",
            })
            subprocess.run(["bash", str(SCRIPT)], check=True, env=env, capture_output=True, text=True)
            run = json.loads((site / "stats" / "runs.json").read_text())["runs"][0]
            dashboard = (site / "stats" / "index.html").read_text()

            self.assertEqual((run["total"], run["failed"]), (0, 0))
            self.assertEqual((run["shell_passed"], run["shell_failed"]), (1, 1))
            self.assertEqual(len(run["shell_failed_tests"]), 1)
            failure = run["shell_failed_tests"][0]
            self.assertEqual(failure["title"], "shell-tests > scrape-csrf-extraction / current-csrf-meta-name")
            self.assertEqual(failure["error"], 'expected "current123XYZ", got ""')
            self.assertIn("current-csrf-meta-name", dashboard)
            self.assertIn("current123XYZ", dashboard)
            self.assertIn("shell_failed_tests", dashboard)
            self.assertIn(
                '["shell-tests > scrape-csrf-extraction / current-csrf-meta-name", 1]',
                dashboard,
            )


if __name__ == "__main__":
    unittest.main()
