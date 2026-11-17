# Test statistics for GitHub Pages

Composite GitHub Action for parsing test-result files, writing a GitHub Actions
step summary, and updating a rolling test-statistics site in a caller-provided
directory. It does not deploy Pages; the caller can combine its output with
other site content and perform one deployment.

## Usage

```yaml
- name: Collect test statistics
  id: stats
  uses: raczeja/test-stats-gh-pages-action@v1
  with:
    result-files: |
      test-results/junit.xml
      shell-tests.xml
    format: auto
    site-directory: site
    stats-subdirectory: reusable-stats
    history-days: 30
    report-name: CI tests
    detailed-statistics: "true"
```

The action currently supports JUnit XML (`.xml`) and Playwright JSON (`.json`)
with `stats` and `suites` objects. `format: auto` selects by extension. To add a
format, implement a parser adapter that emits the existing normalized counts
and preserve `stats/runs.json` as the storage contract.

The statistics action requires Python 3 on the runner. `result-files` accepts
newline-separated paths or glob patterns. Missing matches and malformed files
fail the action rather than producing success-shaped empty data.

It creates/updates:

- `<stats-subdirectory>/runs.json` — normalized run history, pruned to the
  configured rolling window and deduplicated by GitHub run number.
- `<stats-subdirectory>/index.html` — a small static recent-run table.
- `$GITHUB_STEP_SUMMARY` and action outputs `total`, `passed`, `failed`,
  `skipped`, and `stats-file`.
- `stats/runs.json` and `stats/index.html` — the detailed rolling 30-day
  Playwright failure, flakiness, runtime, and shell-test dashboard. Detailed
  statistics are enabled by default and can be disabled with
  `detailed-statistics: "false"`.

The `passed` count includes Playwright tests that passed after retries; these
are also exposed separately as `flaky_count` in the normalized run record.
JUnit failures and Playwright unexpected tests count as failed. The detailed
dashboard uses Playwright JSON and the optional `shell-test-results` JUnit
file. Other JUnit result files contribute to the normalized results and
summary.

## Permissions and deployment

The action itself uses only local files and does not request a token or modify a
branch. Set the workflow's `contents: write` permission only on the separate
deployment job that publishes the assembled site. Pin the action to a reviewed
release tag or commit SHA.

## Local tests

```sh
python3 -m unittest discover -s test -v
```
