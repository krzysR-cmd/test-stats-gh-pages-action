import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).parents[1] / "src" / "update-stats.sh"


class DetailedStatsTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
