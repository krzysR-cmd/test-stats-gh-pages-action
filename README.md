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
  Playwright and optional shell-test dashboard. It lists all tests captured by
  the detailed-statistics step, marks new tests and status changes against the
  previous run, and highlights tests included in the selected Test trends view.
  Detailed statistics are enabled by default and can be disabled with
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

## Set up GitHub Pages in your project

Add a workflow to your project that runs your tests, generates a result file,
updates the site with this action, and publishes the `site` directory:

```yaml
name: Test report

on:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Restore the existing Pages site
        uses: actions/checkout@v4
        with:
          ref: gh-pages
          path: site

      - name: Run tests
        run: npm test -- --reporter=junit

      - name: Update test statistics
        uses: raczeja/test-stats-gh-pages-action@v1
        with:
          result-files: test-results/junit.xml
          site-directory: site

      - uses: actions/upload-artifact@v4
        with:
          name: pages-site
          path: site

  publish:
    needs: build
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: pages-site
          path: site

      - name: Publish site
        uses: peaceiris/actions-gh-pages@v4
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: site
          force_orphan: true
```

Replace the test command and `result-files` path with the ones used by your
project. The first workflow run can create the `gh-pages` branch when it
publishes, so you do not need to create the branch manually. After that run
succeeds, open **Settings → Pages**, choose **Deploy from a branch**, then
select `gh-pages` and the root (`/`) folder.

With `force_orphan: true`, each deployment replaces the `gh-pages` branch with
a new root commit. **The branch's previous commit history is not kept.** The
source branch (for example, `main`) is unaffected.

## This repository's dashboard

The `.github/workflows/test-statistics-pages.yml` workflow runs the test suite
and publishes its JUnit results to this repository's `gh-pages` branch on
pushes to `main` and manual runs from `main`. Pull requests build the dashboard
but do not publish it. The first successful workflow run on `main` creates
`gh-pages`; you do not need to create it manually. Then enable Pages in
**Settings → Pages** with `gh-pages` and the root (`/`) folder; the dashboard
is available at the site root and `/stats/`. The root page redirects to the
dashboard. The workflow restores the existing Pages files
before each build so rolling test history is preserved, even though the
branch's Git commit history is not.

## Local tests

```sh
python3 -m unittest discover -s test -v
```
