#!/usr/bin/env python
"""Golden-image harness for the surface-rendering migration
(design/surface-rendering.md R0).

capture: screenshot the viewer canvas for fixtures x themes into an output
directory. compare: perceptual-diff two capture directories and report.

Usage:
  golden.py capture --url-base http://127.0.0.1:PORT --out DIR [--themes a,b]
  golden.py compare GOLDEN_DIR CANDIDATE_DIR [--threshold 0.02]

The viewer must already be serving the worktree's models/ directory.
Deterministic by construction: fixed viewport, auto-fit default camera,
fixed settle delay, canvas-only crop (UI chrome excluded).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

FIXTURES = {
    "planetary": "step/assemblies/planetary_gear_assembly.step.py",
    "turbofan": "step/assemblies/cutaway_turbofan_engine.step.py",
    "moonwatch": "renders/moonwatch/moonwatch.step.py",
}
THEMES = ["workbench-light", "workbench-dark", "cinematic", "vibrant",
          "blue", "pink", "clay-sunrise", "terminal"]


def capture(url_base: str, out_dir: Path, themes: list[str]) -> int:
    from playwright.sync_api import sync_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    failures = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=[
            "--enable-unsafe-webgpu", "--use-angle=metal", "--enable-gpu"])
        for fixture, rel in FIXTURES.items():
            for theme in themes:
                name = f"{fixture}--{theme}"
                url = f"{url_base}/?file={rel}"
                # Fresh page per shot: init scripts accumulate per page, and
                # the theme is viewer-persisted state, not a URL param
                # (persistence.js THEME_STORAGE_KEY, version 12).
                page = browser.new_page(
                    viewport={"width": 1200, "height": 900},
                    device_scale_factor=1)
                page.add_init_script(
                    "localStorage.setItem('cad-viewer:theme',"
                    f" JSON.stringify({{version: 12, themeId: {theme!r}}}))")
                try:
                    page.goto(url, timeout=60000)
                    page.wait_for_selector("canvas", timeout=60000)
                    time.sleep(8)  # model fetch + first render settle
                    canvas = page.query_selector("canvas")
                    canvas.screenshot(path=str(out_dir / f"{name}.png"))
                    print(f"captured {name}", flush=True)
                except Exception as exc:
                    failures += 1
                    print(f"FAILED {name}: {exc}", flush=True)
                finally:
                    page.close()
        browser.close()
    return failures


def compare(golden: Path, candidate: Path, threshold: float) -> int:
    from PIL import Image, ImageChops

    failures = 0
    goldens = sorted(golden.glob("*.png"))
    if not goldens:
        print(f"no goldens in {golden}")
        return 1
    for gold_path in goldens:
        cand_path = candidate / gold_path.name
        if not cand_path.is_file():
            print(f"MISSING {gold_path.name}")
            failures += 1
            continue
        a = Image.open(gold_path).convert("RGB")
        b = Image.open(cand_path).convert("RGB")
        if a.size != b.size:
            b = b.resize(a.size)
        diff = ImageChops.difference(a, b)
        histogram = diff.convert("L").histogram()
        total = sum(histogram)
        # a pixel "differs" when its max channel delta exceeds 12/255
        differing = sum(histogram[13:])
        fraction = differing / max(total, 1)
        status = "OK " if fraction <= threshold else "DIFF"
        if fraction > threshold:
            failures += 1
        print(f"{status} {gold_path.name}: {fraction*100:.2f}% pixels differ")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    cap = sub.add_parser("capture")
    cap.add_argument("--url-base", required=True)
    cap.add_argument("--out", required=True)
    cap.add_argument("--themes", default=",".join(THEMES))
    cmp_p = sub.add_parser("compare")
    cmp_p.add_argument("golden")
    cmp_p.add_argument("candidate")
    cmp_p.add_argument("--threshold", type=float, default=0.02)
    args = parser.parse_args()
    if args.cmd == "capture":
        return capture(args.url_base, Path(args.out),
                       [t for t in args.themes.split(",") if t])
    return compare(Path(args.golden), Path(args.candidate), args.threshold)


if __name__ == "__main__":
    sys.exit(main())
