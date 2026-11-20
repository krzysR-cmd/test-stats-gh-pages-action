#!/usr/bin/env python3

import sys
from pathlib import Path


START_MARKER = "<!-- stats-dashboard-screenshots:start -->"
END_MARKER = "<!-- stats-dashboard-screenshots:end -->"
DASHBOARD_URL = "https://raczeja.github.io/test-stats-gh-pages-action/stats/"


def update_readme(readme: Path, screenshot_dir: Path) -> None:
    def screenshot_sort_key(path: Path) -> tuple[int, int, str]:
        if path.name == "stats-dashboard.png":
            return (0, 0, path.name)
        stem = path.stem
        suffix = stem.rsplit("-", 1)[-1]
        try:
            part = int(suffix)
        except ValueError:
            part = 0
        return (1, part, path.name)

    screenshots = sorted(
        (path for path in screenshot_dir.glob("stats-dashboard*.png") if path.is_file()),
        key=screenshot_sort_key,
    )
    if not screenshots:
        raise RuntimeError(f"No dashboard screenshots found in {screenshot_dir}")

    lines = []
    for index, screenshot in enumerate(screenshots, start=1):
        screenshot_path = screenshot.as_posix()
        if screenshot_dir.as_posix().startswith("./"):
            screenshot_path = screenshot.as_posix()[2:]
        label = "Test statistics dashboard" if len(screenshots) == 1 else (
            f"Test statistics dashboard part {index}"
        )
        lines.append(f"[![{label}]({screenshot_path})]({DASHBOARD_URL})")

    content = readme.read_text(encoding="utf-8")
    if START_MARKER not in content or END_MARKER not in content:
        raise RuntimeError("README screenshot markers are missing")

    start = content.index(START_MARKER)
    end = content.index(END_MARKER, start) + len(END_MARKER)
    replacement = "\n".join([START_MARKER, *lines, END_MARKER])
    readme.write_text(
        content[:start] + replacement + content[end:],
        encoding="utf-8",
    )


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: update_readme_screenshots.py README SCREENSHOT_DIRECTORY", file=sys.stderr)
        return 2

    try:
        update_readme(Path(sys.argv[1]), Path(sys.argv[2]))
    except (OSError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
