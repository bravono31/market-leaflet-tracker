"""Step 3 of the Claude routine: merge work/results/*.json into docs/data.

Usage: python -m scraper.ingest
"""
import json
from datetime import datetime

from . import extract, run, stores
from .prepare import WORK


def validate(result):
    """Raise ValueError unless `result` has the shape described in ROUTINE.md."""
    if not isinstance(result.get("items"), list) or not isinstance(result.get("campaigns", []), list):
        raise ValueError("items / campaigns must be lists")
    for it in result["items"]:
        for field in ("name", "key", "category"):
            if not isinstance(it.get(field), str) or not it[field].strip():
                raise ValueError(f"item without {field}: {it}")
        if it["category"] not in extract.CATEGORIES:
            raise ValueError(f"unknown category: {it['category']}")
        for field in ("price", "price_tax_in"):
            if it.get(field) is not None and not isinstance(it[field], (int, float)):
                raise ValueError(f"{field} must be a number: {it}")
        for field in ("start", "end"):
            if it.get(field):
                datetime.strptime(it[field], "%Y-%m-%d")
    for c in result.get("campaigns", []):
        if not isinstance(c.get("name"), str):
            raise ValueError(f"campaign without name: {c}")


def main():
    manifest = json.loads((WORK / "manifest.json").read_text(encoding="utf-8"))
    leaflets = run.load("leaflets.json", [])
    items = run.load("items.json", [])
    done = {l["id"] for l in leaflets}
    errors = list(manifest["errors"])
    added = 0
    for leaf in manifest["leaflets"]:
        path = WORK / "results" / f"{leaf['id']}.json"
        if leaf["id"] in done or not path.exists():
            continue
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
            validate(result)
        except Exception as e:
            errors.append(f"{leaf['id']}: 読み取り結果が不正 ({e})")
            continue
        record, new_items = run.build_records(leaf, result, manifest["today"])
        leaflets.append(record)
        items += new_items
        added += 1
        print(f"  {leaf['id']}: {len(new_items)} items")

    run.save("leaflets.json", leaflets)
    run.save("items.json", items)
    run.save("status.json", {
        "updated": datetime.now(stores.JST).strftime("%Y-%m-%d %H:%M"),
        "pending": manifest["total_new"] - added, "errors": errors,
        "stores": {k: v["name"] for k, v in stores.STORES.items()},
        "store_urls": {k: v["url"] for k, v in stores.STORES.items()}})
    print(f"added={added} leaflets={len(leaflets)} items={len(items)} "
          f"pending={manifest['total_new'] - added} errors={len(errors)}")


if __name__ == "__main__":
    main()
