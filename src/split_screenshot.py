#!/usr/bin/env python3

import sys
from pathlib import Path

from PIL import Image


MAX_SECTION_HEIGHT = 1800
SECTION_HEIGHT = 900


def split_screenshot(source: Path, output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    for old in output_dir.glob("stats-dashboard*.png"):
        old.unlink()

    with Image.open(source) as image:
        image.load()
        width, height = image.size
        if height <= MAX_SECTION_HEIGHT:
            destination = output_dir / "stats-dashboard.png"
            image.save(destination, "PNG")
            return [destination]

        destinations = []
        for index, top in enumerate(range(0, height, SECTION_HEIGHT), start=1):
            bottom = min(top + SECTION_HEIGHT, height)
            section = image.crop((0, top, width, bottom))
            destination = output_dir / f"stats-dashboard-{index}.png"
            section.save(destination, "PNG")
            destinations.append(destination)
        return destinations


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: split_screenshot.py SOURCE OUTPUT_DIRECTORY", file=sys.stderr)
        return 2

    source = Path(sys.argv[1])
    if not source.is_file():
        print(f"Screenshot not found: {source}", file=sys.stderr)
        return 1

    split_screenshot(source, Path(sys.argv[2]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
