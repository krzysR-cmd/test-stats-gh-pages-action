import datetime as dt
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).parents[1] / "src" / "update-stats.sh"


class DetailedStatsTests(unittest.TestCase):
    def test_dashboard_shows_average_failures_and_flaky_tests_per_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            results = root / "results"
            results.mkdir()
            playwright = results / "playwright.json"
            site = root / "site"

            for number, unexpected, flaky in ((1, 3, 1), (2, 0, 2)):
                playwright.write_text(json.dumps({
                    "stats": {
                        "expected": 2,
                        "unexpected": unexpected,
                        "flaky": flaky,
                        "skipped": 0,
                        "duration": 1000,
                    },
                    "suites": [],
                }))
                env = os.environ.copy()
                env.update({
                    "RESULTS_DIR": str(results),
                    "SITE_DIR": str(site),
                    "GITHUB_RUN_NUMBER": str(number),
                    "GITHUB_RUN_ID": f"run-{number}",
                    "GITHUB_SERVER_URL": "https://github.com",
                    "GITHUB_REPOSITORY": "owner/repo",
                })
                subprocess.run(
                    ["bash", str(SCRIPT)],
                    check=True,
                    env=env,
                    capture_output=True,
                    text=True,
                )

            dashboard = (site / "stats" / "index.html").read_text()

            self.assertIn(
                '<div class="stat-box stat-fail"><div class="stat-val">1.5</div>'
                '<div class="stat-lbl">Avg failures/run</div></div>',
                dashboard,
            )
            self.assertIn(
                '<div class="stat-box stat-flaky"><div class="stat-val">1.5</div>'
                '<div class="stat-lbl">Avg flaky/run</div></div>',
                dashboard,
            )
            self.assertNotIn("Total failures", dashboard)
            self.assertNotIn("Total flaky", dashboard)

    def test_reads_vstest_trx_as_supplemental_test_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            results = root / "results"
            results.mkdir()
            trx = root / "Ocaramba.Tests.Features.xml"
            trx.write_text(
                '<TestRun xmlns="http://microsoft.com/schemas/VisualStudio/TeamTest/2010">'
                '<Results>'
                '<UnitTestResult testId="passed" testName="Tests.Pass" outcome="Passed" '
                'duration="00:00:00.1250000"/>'
                '<UnitTestResult testId="failed" testName="Tests.Fail" outcome="Failed" '
                'duration="00:00:01.2500000"><Output><ErrorInfo><Message>broken</Message>'
                '</ErrorInfo></Output></UnitTestResult>'
                '<UnitTestResult testId="skipped" testName="Tests.Skip" outcome="NotExecuted" '
                'duration="00:00:00"/></Results>'
                '<TestDefinitions><UnitTest id="failed"><TestMethod className="Tests" '
                'name="Fail"/></UnitTest></TestDefinitions></TestRun>'
            )
            site = root / "site"
            env = os.environ.copy()
            env.update({
                "RESULTS_DIR": str(results),
                "SITE_DIR": str(site),
                "SHELL_TESTS_XML": str(trx),
                "GITHUB_RUN_NUMBER": "8",
                "GITHUB_RUN_ID": "run-8",
                "GITHUB_SERVER_URL": "https://github.com",
                "GITHUB_REPOSITORY": "owner/repo",
            })

            subprocess.run(
                ["bash", str(SCRIPT)],
                check=True,
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
            )

            run = json.loads((site / "stats" / "runs.json").read_text())["runs"][0]
            tests = {test["title"]: test for test in run["tests"]}
            self.assertEqual(
                (run["shell_passed"], run["shell_failed"], run["shell_skipped"]),
                (1, 1, 1),
            )
            self.assertEqual(tests["Tests.Pass"]["source"], "VSTest")
            self.assertEqual(tests["Tests.Pass"]["duration_ms"], 125)
            self.assertEqual(run["shell_failed_tests"][0]["error"], "broken")

    def test_reads_nunit_and_xunit_xml_as_supplemental_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            results = root / "results"
            results.mkdir()
            (root / "nunit3.xml").write_text(
                '<test-run><test-case fullname="NUnit3.Pass" result="Passed" duration="0.125"/>'
                '<test-case fullname="NUnit3.Fail" result="Failed"><failure><message>nunit failure'
                '</message></failure></test-case><test-case fullname="NUnit3.Skip" result="Skipped"/>'
                '</test-run>'
            )
            (root / "nunit2.xml").write_text(
                '<test-results><test-suite><results><test-case name="NUnit2.Pass" '
                'success="True" executed="True" time="0.25"/><test-case name="NUnit2.Skip" '
                'success="False" executed="False" result="Ignored"/></results></test-suite></test-results>'
            )
            (root / "xunit.xml").write_text(
                '<assemblies><assembly name="Tests"><collection><test name="Xunit.Pass" '
                'result="Pass" time="0.5"/><test name="Xunit.Fail" result="Fail">'
                '<failure><message>xunit failure</message></failure></test>'
                '<test name="Xunit.Skip" result="Skip"/></collection></assembly></assemblies>'
            )
            site = root / "site"
            env = os.environ.copy()
            env.update({
                "RESULTS_DIR": str(results),
                "SITE_DIR": str(site),
                "SHELL_TESTS_XML": str(root / "*.xml"),
                "GITHUB_RUN_NUMBER": "9",
                "GITHUB_RUN_ID": "run-9",
                "GITHUB_SERVER_URL": "https://github.com",
                "GITHUB_REPOSITORY": "owner/repo",
            })

            subprocess.run(
                ["bash", str(SCRIPT)],
                check=True,
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
            )

            run = json.loads((site / "stats" / "runs.json").read_text())["runs"][0]
            tests = {test["title"]: test for test in run["tests"]}
            self.assertEqual(
                (run["shell_passed"], run["shell_failed"], run["shell_skipped"]),
                (3, 2, 3),
            )
            self.assertEqual(tests["NUnit3.Pass"]["source"], "NUnit")
            self.assertEqual(tests["Xunit.Pass"]["source"], "xUnit")
            self.assertEqual(
                {test["error"] for test in run["shell_failed_tests"]},
                {"nunit failure", "xunit failure"},
            )

    def test_expands_junit_glob_and_uses_report_name_in_dashboard_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for directory, name, cases in (
                (
                    "module-a",
                    "TEST-passing.xml",
                    "".join(f'<testcase name="pass-{index}"/>' for index in range(20)),
                ),
                (
                    "module-b",
                    "TEST-mixed.xml",
                    "".join(
                        f'<testcase name="fail-{index}"><failure message="failed"/></testcase>'
                        for index in range(9)
                    )
                    + '<testcase name="skipped"><skipped/></testcase>',
                ),
            ):
                junit_dir = root / "test-results" / directory / "junitreports"
                junit_dir.mkdir(parents=True)
                (junit_dir / name).write_text(f'<testsuite name="{directory}">{cases}</testsuite>')
            site = root / "site"
            env = os.environ.copy()
            env.update({
                "SITE_DIR": str(site),
                "SHELL_TESTS_XML": "test-results/**/TEST-*.xml",
                "REPORT_NAME": "DBTestCompare & tests",
                "GITHUB_RUN_NUMBER": "201",
                "GITHUB_RUN_ID": "run-201",
                "GITHUB_SERVER_URL": "https://github.com",
                "GITHUB_REPOSITORY": "owner/repo",
            })
            subprocess.run(
                ["bash", str(SCRIPT)],
                check=True,
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
            )

            run = json.loads((site / "stats" / "runs.json").read_text())["runs"][0]
            dashboard = (site / "stats" / "index.html").read_text()

            self.assertEqual(
                (run["shell_passed"], run["shell_failed"], run["shell_skipped"]),
                (20, 9, 1),
            )
            self.assertEqual(len(run["tests"]), 30)
            self.assertEqual(len(run["shell_failed_tests"]), 9)
            self.assertNotIn("Failed additional tests", dashboard)
            self.assertNotIn("Failed tests from JSON results", dashboard)
            self.assertIn(
                "<title>repo · DBTestCompare &amp; tests &middot; Test Statistics</title>",
                dashboard,
            )
            self.assertIn(
                "repo · DBTestCompare &amp; tests &middot; Test Statistics",
                dashboard,
            )
            self.assertNotIn("Failed tests from JSON results", dashboard)

    def test_uses_repository_name_for_dashboard_title_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            results = root / "results"
            results.mkdir()
            shell_xml = root / "shell.xml"
            shell_xml.write_text('<testsuite name="example"/>')
            site = root / "site"
            env = os.environ.copy()
            env.update({
                "RESULTS_DIR": str(results),
                "SITE_DIR": str(site),
                "SHELL_TESTS_XML": str(shell_xml),
                "GITHUB_RUN_NUMBER": "1",
                "GITHUB_RUN_ID": "run-1",
                "GITHUB_SERVER_URL": "https://github.com",
                "GITHUB_REPOSITORY": "Accenture/DBTestCompare",
            })
            env.pop("REPORT_NAME", None)
            subprocess.run(
                ["bash", str(SCRIPT)],
                check=True,
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
            )

            dashboard = (site / "stats" / "index.html").read_text()

            self.assertIn(
                "<title>DBTestCompare &middot; Test Statistics</title>",
                dashboard,
            )
            self.assertIn(
                "DBTestCompare &middot; Test Statistics</span>",
                dashboard,
            )

    def test_fails_when_configured_junit_glob_matches_no_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            site = root / "site"
            env = os.environ.copy()
            env.update({
                "SITE_DIR": str(site),
                "SHELL_TESTS_XML": "test-results/**/TEST-*.xml",
                "GITHUB_RUN_NUMBER": "201",
                "GITHUB_RUN_ID": "run-201",
                "GITHUB_SERVER_URL": "https://github.com",
                "GITHUB_REPOSITORY": "owner/repo",
            })

            result = subprocess.run(
                ["bash", str(SCRIPT)],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("No XML test-result files matched", result.stderr)

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
            self.assertIn('data-label="Execution time"', dashboard)
            self.assertIn("fmtTestDur(test.duration_ms)", dashboard)
            self.assertIn("function fmtTestDur(ms)", dashboard)

    def test_preserves_rolling_failure_flaky_runtime_and_shell_statistics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            results = root / "results"
            results.mkdir()
            (results / "playwright.json").write_text(json.dumps({
                "stats": {"expected": 2, "unexpected": 1, "flaky": 1, "skipped": 1, "duration": 900},
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
            self.assertNotIn("Slowest tests (this run)", dashboard)
            self.assertIn("900 ms", dashboard)
            self.assertEqual(
                dashboard.count(
                    "function fmtDur(ms){if(!ms)return '&mdash;';if(ms<1000)return Math.round(ms)+' ms'"
                ),
                2,
            )
            self.assertIn('"flaky": [["suite > retries", 1]]', dashboard)
            self.assertIn("else if(v==='flaky')", dashboard)
            self.assertIn("else if(v==='longest')", dashboard)
            self.assertIn("else if(v==='retried')", dashboard)
            self.assertIn("shell failure", run["shell_failed_tests"][0]["error"])
            self.assertIn("JSON test results", dashboard)
            self.assertNotIn("Additional test results", dashboard)
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
            self.assertIn("var sortColumn='priority';", dashboard)
            self.assertIn("var ranks={failed:0,flaky:1,passed:2,skipped:3};", dashboard)
            self.assertIn("return test.change==='new'?0:(test.change==='changed'?1:2);", dashboard)
            self.assertIn("currentTests=tests.slice().sort", dashboard)
            self.assertIn("data-sort=\"title\"", dashboard)
            self.assertIn("data-sort=\"source\"", dashboard)
            self.assertIn("data-sort=\"status\"", dashboard)
            self.assertIn("data-sort=\"duration\"", dashboard)
            self.assertIn("data-sort=\"change\"", dashboard)
            self.assertIn("sortDirection=column===sortColumn?-sortDirection:1;", dashboard)

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
            node = shutil.which("node")
            if node is None:
                self.skipTest("Node.js is required to exercise dashboard behavior")
            script_start = dashboard.index(
                "<script>\n(function(){\n  var sel=document.getElementById('agg-picker');"
            ) + len("<script>")
            script_end = dashboard.index("</script>", script_start)
            rows = [
                {"title": f"trends > failed-{index}", "status": "failed"}
                for index in range(1, 7)
            ] + [
                {"title": f"trends > flaky-{index}", "status": "flaky"}
                for index in range(1, 7)
            ]
            result = subprocess.run(
                [node, "-e", """
                    const { runInNewContext } = require('vm');
                    const input = JSON.parse(process.argv[1]);
                    const rows = input.rows.map(row => {
                      const classes = new Set();
                      return {
                        getAttribute(name) {
                          return name === 'data-test-title' ? row.title : row.status;
                        },
                        classList: {
                          toggle(name, enabled) {
                            if (enabled) classes.add(name);
                            else classes.delete(name);
                          }
                        },
                        classes
                      };
                    });
                    const picker = {
                      value: 'top',
                      addEventListener(name, callback) { this.listener = callback; }
                    };
                    const box = { innerHTML: '' };
                    const document = {
                      getElementById(name) { return name === 'agg-picker' ? picker : box; },
                      querySelectorAll() { return rows; }
                    };
                    runInNewContext(input.script, { document, AGG: input.trends });
                    const highlighted = () => rows
                      .filter(row => row.classes.has('test-trend-match'))
                      .map(row => row.getAttribute('data-test-title'));
                    const top = highlighted();
                    picker.value = 'flaky';
                    picker.listener.call(picker);
                    process.stdout.write(JSON.stringify({ top, flaky: highlighted() }));
                """, json.dumps({
                    "script": dashboard[script_start:script_end],
                    "trends": trends,
                    "rows": rows,
                })],
                check=True,
                capture_output=True,
                text=True,
            )
            highlights = json.loads(result.stdout)
            self.assertEqual(
                set(highlights["top"]),
                {f"trends > failed-{index}" for index in range(1, 7)},
            )
            self.assertEqual(
                set(highlights["flaky"]),
                {title for title, _ in trends["flaky"]},
            )

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
