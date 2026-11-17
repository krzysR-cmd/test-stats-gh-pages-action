import datetime as dt
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

            self.assertIn("@media(max-width:640px)", dashboard)
            self.assertIn(".stats-row,.selected-run-stats,.duration-stats", dashboard)
            self.assertIn(".table-scroll{max-width:100%;overflow-x:auto}", dashboard)
            self.assertIn(
                '<div class="table-scroll"><table class="all-tests">',
                dashboard,
            )
            self.assertEqual(len(latest["tests"]), 4)
            self.assertNotIn("change", tests[("Playwright", "suite > stable")])
            self.assertEqual(tests[("Playwright", "suite > added")]["change"], "new")
            self.assertEqual(tests[("Playwright", "suite > changes")]["previous_status"], "passed")
            self.assertEqual(tests[("Playwright", "suite > changes")]["status"], "failed")
            self.assertEqual(tests[("JUnit", "shell > check")]["change"], "changed")
            self.assertEqual(tests[("Playwright", "suite > changes")]["duration_ms"], 0)
            self.assertEqual(tests[("JUnit", "shell > check")]["duration_ms"], 0)
            self.assertIn('"compared_with_run_id": "1"', dashboard)
            self.assertIn("New</span>", dashboard)
            self.assertIn("&rarr; '+esc(status)", dashboard)
            self.assertIn("test-trend-match", dashboard)
            self.assertIn(
                '"flaky": [["shell > check", 1], ["suite > changes", 1]]',
                dashboard,
            )
            self.assertIn("else if(v==='flaky')", dashboard)
            self.assertIn("else if(v==='longest')", dashboard)
            self.assertIn("else if(v==='retried')", dashboard)
            self.assertIn('<option value="1" selected>', dashboard)
            self.assertLess(
                dashboard.index('id="run-picker"'),
                dashboard.index('<h2 class="card-title">Last 30 days'),
            )
            self.assertIn(
                "picker.addEventListener('change',function(){renderRun(RUNS[parseInt(this.value,10)]);});",
                dashboard,
            )
            self.assertIn("<th>Execution time</th>", dashboard)
            self.assertIn("fmtTestDur(test.duration_ms)", dashboard)
            self.assertIn("function fmtTestDur(ms)", dashboard)

    def test_preserves_rolling_failure_flaky_runtime_and_shell_statistics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            results = root / "results"
            results.mkdir()
            (results / "playwright.json").write_text(json.dumps({
                "stats": {"expected": 2, "unexpected": 1, "flaky": 1, "skipped": 1, "duration": 1200},
                "suites": [{
                    "title": "suite",
                    "specs": [
                        {
                            "title": "fails",
                            "file": "tests/example.spec.js",
                            "tests": [{
                                "status": "unexpected",
                                "results": [{"duration": 300, "errors": [{"message": "failure detail"}]}],
                            }],
                        },
                        {
                            "title": "retries",
                            "file": "tests/example.spec.js",
                            "tests": [{"status": "flaky", "results": [{"duration": 500}, {"duration": 400}]}],
                        },
                        {
                            "title": "passes",
                            "file": "tests/example.spec.js",
                            "tests": [{"status": "expected"}, {"status": "expected"}],
                        },
                        {
                            "title": "skips",
                            "file": "tests/example.spec.js",
                            "tests": [{"status": "skipped"}],
                        },
                    ],
                }],
            }))
            shell_xml = root / "shell.xml"
            shell_xml.write_text(
                '<testsuites><testsuite name="syntax">'
                '<testcase classname="sh" name="pass" time="0.125"/>'
                '<testcase classname="sh" name="fail" time="0.5"><failure message="shell failure"/></testcase>'
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
            playwright_tests = {test["title"]: test for test in run["tests"] if test["source"] == "Playwright"}
            self.assertEqual(playwright_tests["suite > fails"]["duration_ms"], 300)
            self.assertEqual(playwright_tests["suite > retries"]["duration_ms"], 900)
            junit_tests = {test["title"]: test for test in run["tests"] if test["source"] == "JUnit"}
            self.assertEqual(junit_tests["syntax > pass"]["duration_ms"], 125)
            self.assertEqual(junit_tests["syntax > fail"]["duration_ms"], 500)
            self.assertEqual(junit_tests["syntax > skip"]["duration_ms"], 0)
            self.assertIn("Test trends (last 30 days)", dashboard)
            self.assertIn('"flaky": [["suite > retries", 1]]', dashboard)
            self.assertIn("else if(v==='flaky')", dashboard)
            self.assertIn("else if(v==='longest')", dashboard)
            self.assertIn("else if(v==='retried')", dashboard)
            self.assertIn("shell failure", run["shell_failed_tests"][0]["error"])
            self.assertIn("JSON test results", dashboard)
            self.assertIn("Additional test results", dashboard)
            self.assertNotIn("JUnit-format test results", dashboard)
            self.assertNotIn("Failed shell tests", dashboard)

    def test_paginates_selected_run_tests_and_allows_page_size_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            results = root / "results"
            results.mkdir()
            tests = [{
                "title": f"test-{index}",
                "file": "tests/pagination.spec.js",
                "tests": [{"status": "expected", "results": []}],
            } for index in range(65)]
            (results / "playwright.json").write_text(json.dumps({
                "stats": {"expected": len(tests), "unexpected": 0, "flaky": 0, "skipped": 0, "duration": 0},
                "suites": [{"title": "pagination", "specs": tests}],
            }))
            shell_xml = root / "shell.xml"
            shell_xml.write_text('<testsuite name="shell"/>')
            site = root / "site"
            env = os.environ.copy()
            env.update({
                "RESULTS_DIR": str(results),
                "SITE_DIR": str(site),
                "SHELL_TESTS_XML": str(shell_xml),
                "GITHUB_RUN_NUMBER": "1",
                "GITHUB_RUN_ID": "run-1",
                "GITHUB_SERVER_URL": "https://github.com",
                "GITHUB_REPOSITORY": "owner/repo",
            })
            subprocess.run(["bash", str(SCRIPT)], check=True, env=env, capture_output=True, text=True)
            dashboard = (site / "stats" / "index.html").read_text()

            self.assertIn("var testsPerPage=30;", dashboard)
            self.assertIn("Math.ceil(currentTests.length/testsPerPage)", dashboard)
            self.assertIn("Showing '+(currentTests.length?start+1:0)+'-'+end+' of '+currentTests.length+' tests'", dashboard)
            self.assertIn("Page '+(currentPage+1)+' of '+pageCount", dashboard)
            self.assertIn('aria-label="Previous test page">Prev', dashboard)
            self.assertIn('aria-label="Next test page">Next', dashboard)
            self.assertIn('<option value="30" selected>30</option><option value="50">50</option><option value="100">100</option>', dashboard)
            self.assertIn("currentPage--;renderTestPage()", dashboard)
            self.assertIn("currentPage++;renderTestPage()", dashboard)
            self.assertIn("testsPerPage=parseInt(this.value,10)", dashboard)
            self.assertIn("var start=currentPage*testsPerPage,end=Math.min(start+testsPerPage,currentTests.length)", dashboard)
            self.assertIn('"title": "pagination > test-64"', dashboard)

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

    def test_shows_aggregate_counts_for_historical_runs_without_test_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            results = root / "results"
            results.mkdir()
            shell_xml = root / "shell.xml"
            shell_xml.write_text('<testsuite name="current"><testcase name="passes"/></testsuite>')
            site = root / "site"
            stats_dir = site / "stats"
            stats_dir.mkdir(parents=True)
            old_timestamp = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
            legacy_run = {
                "run_id": "371",
                "run_url": "https://github.com/owner/repo/actions/runs/371",
                "timestamp": old_timestamp,
                "total": 0,
                "passed": 0,
                "failed": 0,
                "skipped": 0,
                "flaky_count": 0,
                "shell_passed": 220,
                "shell_failed": 1,
                "shell_skipped": 0,
                "shell_failed_tests": [],
            }
            (stats_dir / "runs.json").write_text(json.dumps({"runs": [legacy_run]}))
            env = os.environ.copy()
            env.update({
                "RESULTS_DIR": str(results),
                "SITE_DIR": str(site),
                "SHELL_TESTS_XML": str(shell_xml),
                "GITHUB_RUN_NUMBER": "372",
                "GITHUB_RUN_ID": "run-372",
                "GITHUB_SERVER_URL": "https://github.com",
                "GITHUB_REPOSITORY": "owner/repo",
            })
            subprocess.run(["bash", str(SCRIPT)], check=True, env=env, capture_output=True, text=True)
            dashboard = (stats_dir / "index.html").read_text()

            self.assertIn('"shell_passed": 220', dashboard)
            self.assertIn("counts.total=(run.total||0)+(run.shell_passed||0)", dashboard)
            self.assertIn("counts.failed=(run.failed||0)+(run.shell_failed||0)", dashboard)
            self.assertIn(
                "Individual test results were not saved for this run; showing available aggregate counts.",
                dashboard,
            )
            self.assertIn(
                "run.shell_failed+' failure(s); individual test details were not saved for this run.",
                dashboard,
            )

    def test_longest_tests_trend_shows_only_five_slowest_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            results = root / "results"
            results.mkdir()
            test_cases = [{
                "title": f"test-{index}",
                "file": "tests/timing.spec.js",
                "tests": [{
                    "status": "expected",
                    "results": [{"duration": index * 1000}],
                }],
            } for index in range(1, 7)]
            (results / "playwright.json").write_text(json.dumps({
                "stats": {"expected": 6, "unexpected": 0, "flaky": 0, "skipped": 0, "duration": 21000},
                "suites": [{"title": "timing", "specs": test_cases}],
            }))
            shell_xml = root / "shell.xml"
            shell_xml.write_text('<testsuite name="shell"/>')
            site = root / "site"
            env = os.environ.copy()
            env.update({
                "RESULTS_DIR": str(results),
                "SITE_DIR": str(site),
                "SHELL_TESTS_XML": str(shell_xml),
                "GITHUB_RUN_NUMBER": "1",
                "GITHUB_RUN_ID": "run-1",
                "GITHUB_SERVER_URL": "https://github.com",
                "GITHUB_REPOSITORY": "owner/repo",
            })
            subprocess.run(["bash", str(SCRIPT)], check=True, env=env, capture_output=True, text=True)
            dashboard = (site / "stats" / "index.html").read_text()
            payload_start = dashboard.index("var AGG=") + len("var AGG=")
            payload_end = dashboard.index(";</script>", payload_start)
            trends = json.loads(dashboard[payload_start:payload_end])

            self.assertEqual(len(trends["slow"]), 5)
            self.assertEqual(
                trends["slow"],
                [[f"timing > test-{index}", index * 1000] for index in range(6, 1, -1)],
            )

    def test_other_trend_selections_show_at_most_five_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            results = root / "results"
            results.mkdir()
            failed_specs = [{
                "title": f"failed-{index}",
                "file": "tests/trends.spec.js",
                "tests": [{
                    "status": "unexpected",
                    "results": [{"duration": index * 1000, "errors": [{"message": "failure"}]}],
                }],
            } for index in range(1, 7)]
            flaky_specs = [{
                "title": f"flaky-{index}",
                "file": "tests/trends.spec.js",
                "tests": [{
                    "status": "flaky",
                    "results": [{"duration": index * 1000} for _ in range(index)],
                }],
            } for index in range(1, 7)]
            (results / "playwright.json").write_text(json.dumps({
                "stats": {"expected": 1, "unexpected": 6, "flaky": 6, "skipped": 0, "duration": 21000},
                "suites": [{"title": "trends", "specs": failed_specs + flaky_specs}],
            }))
            shell_xml = root / "shell.xml"
            shell_xml.write_text('<testsuite name="shell"/>')
            site = root / "site"
            env = os.environ.copy()
            env.update({
                "RESULTS_DIR": str(results),
                "SITE_DIR": str(site),
                "SHELL_TESTS_XML": str(shell_xml),
                "GITHUB_RUN_NUMBER": "1",
                "GITHUB_RUN_ID": "run-1",
                "GITHUB_SERVER_URL": "https://github.com",
                "GITHUB_REPOSITORY": "owner/repo",
            })
            subprocess.run(["bash", str(SCRIPT)], check=True, env=env, capture_output=True, text=True)
            dashboard = (site / "stats" / "index.html").read_text()
            payload_start = dashboard.index("var AGG=") + len("var AGG=")
            payload_end = dashboard.index(";</script>", payload_start)
            trends = json.loads(dashboard[payload_start:payload_end])

            self.assertEqual(len(trends["top"]), 5)
            self.assertEqual(len(trends["flaky"]), 5)
            self.assertEqual(len(trends["retried"]), 5)

    def test_longest_tests_trend_includes_timed_junit_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            results = root / "results"
            results.mkdir()
            shell_xml = root / "shell.xml"
            shell_xml.write_text(
                '<testsuite name="timing">'
                + "".join(
                    f'<testcase classname="timing" name="test-{index}" time="{index}"/>'
                    for index in range(1, 7)
                )
                + '</testsuite>'
            )
            site = root / "site"
            env = os.environ.copy()
            env.update({
                "RESULTS_DIR": str(results),
                "SITE_DIR": str(site),
                "SHELL_TESTS_XML": str(shell_xml),
                "GITHUB_RUN_NUMBER": "1",
                "GITHUB_RUN_ID": "run-1",
                "GITHUB_SERVER_URL": "https://github.com",
                "GITHUB_REPOSITORY": "owner/repo",
            })
            subprocess.run(["bash", str(SCRIPT)], check=True, env=env, capture_output=True, text=True)
            dashboard = (site / "stats" / "index.html").read_text()
            payload_start = dashboard.index("var AGG=") + len("var AGG=")
            payload_end = dashboard.index(";</script>", payload_start)
            trends = json.loads(dashboard[payload_start:payload_end])

            self.assertEqual(
                trends["slow"],
                [[f"timing > test-{index}", index * 1000] for index in range(6, 1, -1)],
            )


if __name__ == "__main__":
    unittest.main()
