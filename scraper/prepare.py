"""Step 1 of the Claude routine: download new leaflets as readable image tiles.

Usage: python -m scraper.prepare [--max N]
Writes work/manifest.json, work/known_keys.txt and work/<leaflet id>/*.jpg.
"""
import io
import json
import math
import shutil
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image

from . import run, stores

WORK = Path(__file__).resolve().parent.parent / "work"
MAX_WIDTH = 3100   # leaflet text stays legible at this width
TILE_W, TILE_H, PAD = 1100, 1150, 60


def tile_boxes(w, h):
    """Grid of overlapping crops, each small enough to be read at full resolution."""
    cols, rows = math.ceil(w / TILE_W), math.ceil(h / TILE_H)
    return [(max(0, c * w // cols - PAD), max(0, r * h // rows - PAD),
             min(w, (c + 1) * w // cols + PAD), min(h, (r + 1) * h // rows + PAD))
            for r in range(rows) for c in range(cols)]


def page_image(page):
    if page["kind"] == "tiles":
        image = stores.stitch_tiles(page)
    else:
        image = Image.open(io.BytesIO(stores.http_get(page["url"]))).convert("RGB")
    if image.width > MAX_WIDTH:
        image = image.resize((MAX_WIDTH, round(image.height * MAX_WIDTH / image.width)))
    return image


def main():
    limit = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else 8
    today = datetime.now(stores.JST).strftime("%Y-%m-%d")
    errors = []
    done = {l["id"] for l in run.load("leaflets.json", [])}
    new = [l for l in run.discover(today, errors) if l["id"] not in done]
    new.sort(key=lambda l: l["end"] or "9")

    shutil.rmtree(WORK, ignore_errors=True)
    (WORK / "results").mkdir(parents=True)
    manifest = {"today": today, "total_new": len(new), "errors": errors, "leaflets": []}
    for leaf in new[:limit]:
        folder = WORK / leaf["id"]
        folder.mkdir()
        images = []
        try:
            for p, page in enumerate(leaf["pages"], 1):
                image = page_image(page)
                for t, box in enumerate(tile_boxes(*image.size), 1):
                    path = folder / f"p{p}_t{t}.jpg"
                    image.crop(box).save(path, "JPEG", quality=85)
                    images.append(str(path.relative_to(WORK.parent)))
        except Exception as e:
            errors.append(f"{leaf['id']}: 画像取得失敗 ({e})")
            continue
        manifest["leaflets"].append({
            **{k: leaf[k] for k in ("id", "store", "title", "source_url", "start", "end")},
            "store_name": stores.STORES[leaf["store"]]["name"],
            "images": images, "result": f"work/results/{leaf['id']}.json"})
    (WORK / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    keys = sorted({i["key"] for i in run.load("items.json", [])})
    (WORK / "known_keys.txt").write_text("\n".join(keys), encoding="utf-8")
    print(f"today={today} new={len(new)} prepared={len(manifest['leaflets'])} errors={len(errors)}")
    for l in manifest["leaflets"]:
        print(f"  {l['id']} {len(l['images'])} images  {l['title']}")


if __name__ == "__main__":
    main()
