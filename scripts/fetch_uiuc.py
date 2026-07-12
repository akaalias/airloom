#!/usr/bin/env python3
"""Re-download the cached UIUC propeller dataset (GWS Direct Drive 5x4.3).

The repo ships with these files already cached in data/uiuc/ so the loop runs
offline; this script only exists to refresh them from the source:
https://m-selig.ae.illinois.edu/props/propDB.html  (volume 2)
"""
from __future__ import annotations

import urllib.request
from pathlib import Path

BASE = "https://m-selig.ae.illinois.edu/props/volume-2/data"
FILES = [
    "gwsdd_5x4.3_static_0493rd.txt",
    "gwsdd_5x4.3_0511rd_4048.txt",
    "gwsdd_5x4.3_0512rd_6047.txt",
    "gwsdd_5x4.3_0513rd_8044.txt",
    "gwsdd_5x4.3_0514rd_8078.txt",
    "gwsdd_5x4.3_geom.txt",
]


def main() -> None:
    out = Path(__file__).resolve().parent.parent / "data" / "uiuc"
    out.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        url = f"{BASE}/{name}"
        dest = out / name
        print(f"fetching {url}")
        with urllib.request.urlopen(url, timeout=30) as resp:
            dest.write_bytes(resp.read())
        print(f"  -> {dest} ({dest.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
