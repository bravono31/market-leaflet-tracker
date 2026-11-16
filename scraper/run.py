"""Daily job: find new leaflets, extract prices, refresh online prices.

Usage: python -m scraper.run [--dry-run]
Env:   GEMINI_API_KEY (required for extraction), GEMINI_MODEL (optional),
       YAHOO_APP_ID (optional, online prices), MAX_LEAFLETS (default 12)
"""
import json
import os
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

from . import extract, netprice, stores

DATA = Path(__file__).resolve().parent.parent / "docs" / "data"
NET_REFRESH_DAYS = 7
NET_PER_RUN = 40


def load(name, default):
    path = DATA / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save(name, obj):
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / name).write_text(
        json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def discover(today, errors):
    found = []
    for store, fetch in stores.FETCHERS.items():
        try:
            found += fetch()
        except Exception as e:  # one site being down must not block the others
            traceback.print_exc()
            errors.append(f"{stores.STORES[store]['name']}: 取得失敗 ({e})")
    # Evergreen notices (e.g. a delivery ad valid until 2100) carry no prices.
    for leaf in found:
        if not leaf["start"]:
            leaf["start"], leaf["end"] = stores.period_from_title(leaf["title"], today)
    limit = (datetime.fromisoformat(today) + timedelta(days=365)).strftime("%Y-%m-%d")
    return [l for l in found if not (l["end"] and l["end"] > limit)]


def merge_pages(results):
    first = lambda k: next((r[k] for r in results if r.get(k)), None)
    return {"period_start": first("period_start"), "period_end": first("period_end"),
            "campaigns": [c for r in results for c in r.get("campaigns", [])],
            "items": [i for r in results for i in r.get("items", [])]}


def build_records(leaf, result, today):
    """Turn one Gemini result into (leaflet record, item records)."""
    start = leaf["start"] or result.get("period_start") or today
    end = leaf["end"] or result.get("period_end") or start
    record = {"id": leaf["id"], "store": leaf["store"], "title": leaf["title"],
              "source_url": leaf["source_url"], "start": start, "end": end,
              "fetched": today, "campaigns": result.get("campaigns", [])}
    items, seen = [], set()
    for it in result.get("items", []):
        if it.get("price") is None and it.get("price_tax_in") is None:
            continue
        # Split pages overlap, so the same product can be read twice.
        dup = (it["name"], it.get("price"), it.get("price_tax_in"), it.get("start"))
        if dup in seen:
            continue
        seen.add(dup)
        items.append({
            "leaflet": leaf["id"], "store": leaf["store"],
            "name": it["name"], "key": it["key"].strip(), "category": it["category"],
            "price": it.get("price"), "price_tax_in": it.get("price_tax_in"),
            "unit": it.get("unit"), "start": it.get("start") or start,
            "end": it.get("end") or it.get("start") or end,
            "note": it.get("note"), "packaged": bool(it.get("packaged"))})
    return record, items


def net_targets(items, net, today):
    """Packaged product keys whose online price is missing or stale, newest first."""
    stale = (datetime.fromisoformat(today) - timedelta(days=NET_REFRESH_DAYS)).strftime("%Y-%m-%d")
    seen, out = set(), []
    for it in sorted(items, key=lambda i: i["end"], reverse=True):
        key = it["key"]
        if it["packaged"] and key not in seen:
            seen.add(key)
            if net.get(key, {}).get("fetched", "") <= stale:
                out.append(key)
    return out[:NET_PER_RUN]


def main():
    dry = "--dry-run" in sys.argv
    today = datetime.now(stores.JST).strftime("%Y-%m-%d")
    leaflets = load("leaflets.json", [])
    items = load("items.json", [])
    net = load("net.json", {})
    errors = []

    done = {l["id"] for l in leaflets}
    new = [l for l in discover(today, errors) if l["id"] not in done]
    # Soonest-expiring first, so nothing vanishes from the site before we read it.
    new.sort(key=lambda l: l["end"] or "9")
    print(f"new leaflets: {len(new)}")
    for l in new:
        print(f"  {l['id']} [{len(l['pages'])}p] {l['title']}")
    if dry:
        return

    key = os.environ.get("GEMINI_API_KEY")
    pending = len(new)
    if not key:
        errors.append("GEMINI_API_KEY が未設定のため価格抽出をスキップしました")
    elif new:
        model = extract.pick_model(key)
        print("model:", model)
        for leaf in new[:int(os.environ.get("MAX_LEAFLETS", "12"))]:
            known = sorted({i["key"] for i in items})
            try:
                # One request per page: a whole leaflet in one go times out.
                result = merge_pages([
                    extract.extract(key, model, stores.STORES[leaf["store"]]["name"],
                                    leaf["title"], today, image, known)
                    for p in leaf["pages"] for image in stores.load_page(p)])
            except extract.QuotaExceeded as e:
                print("quota exceeded, the rest waits for the next run:", e)
                break
            except Exception as e:
                traceback.print_exc()
                errors.append(f"{leaf['id']}: 抽出失敗 ({e})")
                continue
            record, new_items = build_records(leaf, result, today)
            leaflets.append(record)
            items += new_items
            pending -= 1
            print(f"  {leaf['id']}: {len(new_items)} items")
            time.sleep(6)  # stay under the free tier's per-minute limit

    app_id = os.environ.get("YAHOO_APP_ID")
    if app_id:
        for k in net_targets(items, net, today):
            try:
                net[k] = {"fetched": today, "offers": netprice.search(app_id, k)}
            except Exception as e:
                errors.append(f"ネット価格取得失敗 ({k}): {e}")
                break
            time.sleep(1)

    save("leaflets.json", leaflets)
    save("items.json", items)
    save("net.json", net)
    save("status.json", {
        "updated": datetime.now(stores.JST).strftime("%Y-%m-%d %H:%M"),
        "pending": pending, "errors": errors,
        "stores": {k: v["name"] for k, v in stores.STORES.items()},
        "store_urls": {k: v["url"] for k, v in stores.STORES.items()}})
    print(f"leaflets={len(leaflets)} items={len(items)} pending={pending} errors={len(errors)}")


if __name__ == "__main__":
    main()
