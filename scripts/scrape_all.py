#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scrapers.base import fetch_fx_rates
from scrapers.north_america import scrape_bh_pricematch_targets

DATA_DIR = ROOT / "data"
DEALS_PATH = DATA_DIR / "deals.json"
HISTORY_PATH = DATA_DIR / "history.json"


def load_json(path: Path, default: object) -> object:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    now_iso = datetime.now(timezone.utc).isoformat()
    fx_rates = fetch_fx_rates()

    # Post-purchase mode: monitor ONLY SLC10220CPGV22 on B&H Photo + authorized US competitors
    pm_prods, pm_res = scrape_bh_pricematch_targets(fx_rates)
    all_products = pm_prods
    all_results = [pm_res]

    # Load previous deals & history
    prev_deals_data = load_json(DEALS_PATH, {"products": []})
    prev_by_id = {p["id"]: p for p in prev_deals_data.get("products", [])}
    prev_by_store: dict[str, list[dict]] = {}
    for p in prev_deals_data.get("products", []):
        prev_by_store.setdefault(p["store"], []).append(p)
    history: dict[str, list[dict]] = load_json(HISTORY_PATH, {})

    enriched_products: list[dict] = []
    seen_ids: set[str] = set()
    active_stores_this_run: set[str] = set()

    for prod in all_products:
        if prod.id in seen_ids:
            continue
        seen_ids.add(prod.id)
        active_stores_this_run.add(prod.store)
        d = prod.to_dict()

        # Compare against last recorded price in history (survives transient 0-item runs)
        pts = history.get(prod.id, [])
        prev = prev_by_id.get(prod.id)
        last_known_isk = pts[-1].get("price_isk") if pts else (prev.get("price_isk") if prev else d["price_isk"])
        if d["price_isk"] < last_known_isk:
            drop_isk = last_known_isk - d["price_isk"]
            drop_pct = round((drop_isk / last_known_isk) * 100, 1)
            d["prev_price_isk"] = last_known_isk
            d["price_drop_isk"] = drop_isk
            d["price_drop_pct"] = drop_pct
        else:
            d["prev_price_isk"] = last_known_isk
            d["price_drop_isk"] = 0
            d["price_drop_pct"] = 0.0

        # Update price history (append if price changed or first seen)
        if not pts or pts[-1].get("price_isk") != d["price_isk"]:
            pts.append({
                "ts": now_iso,
                "price_isk": d["price_isk"],
                "landed_isk": d["estimated_landed_isk"],
            })
        history[prod.id] = pts[-90:]

        # Compute all-time low from history
        d["lowest_isk"] = min(p["price_isk"] for p in history[prod.id])
        enriched_products.append(d)

    # Preserve last-known products for stores that had a transient 0-item block/timeout
    for res in all_results:
        if res.count == 0 and res.store in prev_by_store and res.store not in active_stores_this_run:
            cached = prev_by_store[res.store]
            for old_p in cached:
                if old_p["id"] not in seen_ids:
                    seen_ids.add(old_p["id"])
                    old_copy = dict(old_p)
                    old_copy["price_drop_isk"] = 0
                    old_copy["price_drop_pct"] = 0.0
                    enriched_products.append(old_copy)
            res.count = len(cached)
            res.error = (res.error + " | " if res.error else "") + f"Showing {len(cached)} cached items from last successful scrape"

    enriched_products.sort(key=lambda x: x["estimated_landed_isk"])

    payload = {
        "updated_at": now_iso,
        "fx_rates": fx_rates,
        "fx_source": "Íslandsbanki Mastercard (+2.60% card markup)",
        "total_count": len(enriched_products),
        "stores": [r.to_dict() for r in all_results],
        "products": enriched_products,
    }

    DEALS_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    HISTORY_PATH.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Scraped {len(enriched_products)} matching desktop PCs across {len(all_results)} stores.")
    for r in all_results:
        print(f"  [{r.status.upper():7}] {r.store:18} ({r.region}): {r.count} items" + (f" - {r.error}" if r.error else ""))


if __name__ == "__main__":
    main()
