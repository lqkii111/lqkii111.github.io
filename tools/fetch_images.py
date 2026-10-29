#!/usr/bin/env python3
"""Photos de la boutique Flambeur, depuis Wikimedia Commons (licences libres uniquement).

tools/images.json liste les objets de la boutique :
- un objet avec "file" reçoit sa photo finale (img/<id>.webp) et son crédit (tools/credits.json) ;
- un objet avec seulement "q" reçoit une rangée de photos candidates numérotées
  sur une planche de choix (tools/review/sheet-XX.jpg, détail dans candidates.json).
Le rapport de chaque passage est écrit dans tools/fetch-report.txt.
"""
import html
import io
import json
import os
import re
import time
import traceback

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

API = "https://commons.wikimedia.org/w/api.php"
UA = "FlambeurImageFetcher/1.0 (https://github.com/lqkii111/lqkii111.github.io)"
LICENSE_OK = re.compile(r"^(cc0( 1\.0)?|public domain|pd|cc[ -]by(-sa)?[ -]\d\.\d( [a-z-]+)?)$", re.I)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FINAL_WIDTH = 800

session = requests.Session()
session.headers["User-Agent"] = UA
report = []


def log(msg):
    print(msg, flush=True)
    report.append(msg)


def get(url, params=None, tries=4, post=False):
    for k in range(tries):
        try:
            r = session.post(url, data=params, timeout=40) if post else session.get(url, params=params, timeout=40)
            if r.status_code == 200:
                return r
            log(f"  HTTP {r.status_code} : {r.url[:160]}")
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(4 * (k + 1))
                continue
            return None
        except requests.RequestException as e:
            log(f"  erreur réseau : {e}")
            time.sleep(4 * (k + 1))
    return None


def api(**params):
    params.update(action="query", format="json", formatversion="2")
    for k in range(3):
        r = get(API, params, post=True)
        data = r.json() if r else {}
        if "error" not in data:
            return data
        log(f"  erreur API : {data['error'].get('code')} {data['error'].get('info', '')[:120]}")
        time.sleep(5 * (k + 1))
    return {}


def clean(text, limit=90):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def infos(titles, width):
    out = {}
    for i in range(0, len(titles), 40):
        chunk = titles[i:i + 40]
        data = api(titles="|".join(chunk), prop="imageinfo",
                   iiprop="url|size|mime|extmetadata", iiurlwidth=str(width))
        for page in data.get("query", {}).get("pages", []):
            ii = (page.get("imageinfo") or [None])[0]
            if not ii:
                continue
            meta = ii.get("extmetadata", {})

            def val(k):
                return (meta.get(k) or {}).get("value", "")

            out[page["title"]] = {
                "title": page["title"],
                "thumb": ii.get("thumburl") or ii.get("url"),
                "w": ii.get("width", 0),
                "h": ii.get("height", 0),
                "mime": ii.get("mime", ""),
                "license": clean(val("LicenseShortName"), 40),
                "license_url": clean(val("LicenseUrl"), 200),
                "author": clean(val("Artist")) or clean(val("Credit")) or "Auteur inconnu",
                "source": ii.get("descriptionurl", ""),
            }
    return out


def fetch_image(url):
    r = get(url)
    if not r:
        return None
    try:
        im = Image.open(io.BytesIO(r.content))
        return ImageOps.exif_transpose(im).convert("RGB")
    except Exception as e:  # noqa: BLE001
        log(f"  image illisible : {e}")
        return None


def load_font(size):
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def final_photo(it, credits, width):
    iid = it["id"]
    title = it["file"] if it["file"].startswith("File:") else "File:" + it["file"]
    target = os.path.join(ROOT, "img", iid + ".webp")
    old = credits.get(iid)
    if old and old.get("title") == title and os.path.exists(target):
        log(f"{iid} : déjà à jour")
        return
    found = list(infos([title], width).values())
    if not found:
        log(f"{iid} : fichier introuvable ({title})")
        return
    info = found[0]
    if not LICENSE_OK.match(info["license"]):
        log(f"{iid} : licence refusée « {info['license']} » ({title})")
        return
    im = fetch_image(info["thumb"])
    if im is None:
        log(f"{iid} : téléchargement impossible ({title})")
        return
    if im.width > FINAL_WIDTH:
        im = im.resize((FINAL_WIDTH, round(im.height * FINAL_WIDTH / im.width)), Image.LANCZOS)
    im.save(target, "WEBP", quality=78, method=6)
    credits[iid] = {k: info[k] for k in ("title", "author", "license", "license_url", "source")}
    log(f"{iid} : OK {im.width}×{im.height}, {os.path.getsize(target) // 1024} Ko, {info['license']}, {info['author']}")
    time.sleep(0.5)


def candidates(it):
    queries = it["q"] if isinstance(it["q"], list) else [it["q"]]
    per_query = max(2, 6 // len(queries))
    picked, seen = [], set()
    for q in queries:
        data = api(list="search", srnamespace="6", srsearch=q + " filetype:bitmap", srlimit="40")
        titles = [r["title"] for r in data.get("query", {}).get("search", [])]
        meta = infos(titles, 330)
        found = 0
        for t in titles:
            m = meta.get(t) or meta.get(t.replace("_", " "))
            if not m or m["title"] in seen or m["mime"] not in ("image/jpeg", "image/png", "image/webp"):
                continue
            if m["w"] < 1000 or m["h"] < 560 or not (1.2 <= m["w"] / max(1, m["h"]) <= 2.1):
                continue
            if not LICENSE_OK.match(m["license"]):
                continue
            picked.append(m)
            seen.add(m["title"])
            found += 1
            if found >= per_query or len(picked) >= 6:
                break
        log(f"{it['id']} : {found} candidates pour « {q} » ({len(titles)} résultats)")
        if len(picked) >= 6:
            break
    return picked[:6]


def review_sheets(rows):
    rdir = os.path.join(ROOT, "tools", "review")
    os.makedirs(rdir, exist_ok=True)
    font, small = load_font(22), load_font(15)
    TW, TH, LBL, GAP = 300, 200, 230, 8
    listing = {}
    for s in range(0, len(rows), 4):
        group = rows[s:s + 4]
        sheet = Image.new("RGB", (LBL + 6 * (TW + GAP), len(group) * (TH + 30 + GAP) + GAP), (20, 24, 22))
        d = ImageDraw.Draw(sheet)
        for row, (it, cands) in enumerate(group):
            y = GAP + row * (TH + 30 + GAP)
            d.text((10, y + 8), it["id"], fill=(246, 213, 142), font=font)
            q = " / ".join(it["q"]) if isinstance(it["q"], list) else it["q"]
            for k in range(0, min(len(q), 88), 22):
                d.text((10, y + 42 + k), q[k:k + 22], fill=(205, 205, 205), font=small)
            listing[it["id"]] = []
            for n, m in enumerate(cands, 1):
                x = LBL + (n - 1) * (TW + GAP)
                im = fetch_image(m["thumb"])
                if im is not None:
                    sheet.paste(ImageOps.fit(im, (TW, TH), Image.LANCZOS), (x, y))
                d.rectangle([x, y, x + 34, y + 30], fill=(0, 0, 0))
                d.text((x + 9, y + 3), str(n), fill=(255, 255, 255), font=font)
                d.text((x, y + TH + 5), f"{m['license']} · {m['w']}×{m['h']}", fill=(170, 190, 180), font=small)
                listing[it["id"]].append({"n": n, "title": m["title"], "license": m["license"], "author": m["author"]})
                time.sleep(0.3)
        sheet.save(os.path.join(rdir, f"sheet-{s // 4 + 1:02d}.jpg"), "JPEG", quality=82)
    with open(os.path.join(rdir, "candidates.json"), "w", encoding="utf-8") as f:
        json.dump(listing, f, ensure_ascii=False, indent=1)


def main():
    with open(os.path.join(ROOT, "tools", "images.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    os.makedirs(os.path.join(ROOT, "img"), exist_ok=True)
    cred_path = os.path.join(ROOT, "tools", "credits.json")
    credits = {}
    if os.path.exists(cred_path):
        with open(cred_path, encoding="utf-8") as f:
            credits = json.load(f)
    rdir = os.path.join(ROOT, "tools", "review")
    if os.path.isdir(rdir):
        for name in os.listdir(rdir):
            os.remove(os.path.join(rdir, name))
    rows = []
    for it in cfg["items"]:
        try:
            if it.get("file"):
                final_photo(it, credits, cfg.get("width", 960))
            elif it.get("q"):
                rows.append((it, candidates(it)))
        except Exception:  # noqa: BLE001
            log(f"{it.get('id')} : erreur\n{traceback.format_exc()}")
    if rows:
        review_sheets(rows)
    with open(cred_path, "w", encoding="utf-8") as f:
        json.dump(credits, f, ensure_ascii=False, indent=1, sort_keys=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001
        log("ERREUR GÉNÉRALE\n" + traceback.format_exc())
    finally:
        with open(os.path.join(ROOT, "tools", "fetch-report.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(report) + "\n")
