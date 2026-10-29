#!/usr/bin/env python3
"""Polices du jeu (licence SIL Open Font License), converties en WOFF2 et réduites aux caractères latins.

Sortie : assets/fonts/<nom>.woff2 et la licence de chaque police (<nom>-OFL.txt).
"""
import os
import traceback

import requests
from fontTools import subset

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "fonts")
BASE = "https://raw.githubusercontent.com/google/fonts/main/ofl/"
FONTS = [
    ("anton", "anton/Anton-Regular.ttf", "Anton-Regular.woff2"),
    ("figtree", "figtree/Figtree%5Bwght%5D.ttf", "Figtree-Variable.woff2"),
]
UNICODES = ("U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+2000-206F,"
            "U+2074,U+20AC,U+2122,U+2190-2193,U+2212,U+2215,U+2248,U+FEFF,U+FFFD")
UA = {"User-Agent": "FlambeurFontFetcher/1.0 (https://github.com/lqkii111/lqkii111.github.io)"}


def main():
    os.makedirs(OUT, exist_ok=True)
    report = []
    for name, path, out in FONTS:
        try:
            r = requests.get(BASE + path, headers=UA, timeout=60)
            r.raise_for_status()
            src = f"/tmp/{name}.ttf"
            with open(src, "wb") as f:
                f.write(r.content)
            target = os.path.join(OUT, out)
            subset.main([src, f"--unicodes={UNICODES}", "--flavor=woff2", f"--output-file={target}",
                         "--layout-features=*", "--no-hinting"])
            lic = requests.get(BASE + path.split("/")[0] + "/OFL.txt", headers=UA, timeout=60)
            lic.raise_for_status()
            with open(os.path.join(OUT, f"{name}-OFL.txt"), "wb") as f:
                f.write(lic.content)
            report.append(f"{name} : OK {os.path.getsize(target) // 1024} Ko")
        except Exception:  # noqa: BLE001
            report.append(f"{name} : erreur\n{traceback.format_exc()}")
    with open(os.path.join(OUT, "report.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(report) + "\n")
    print("\n".join(report))


if __name__ == "__main__":
    main()
