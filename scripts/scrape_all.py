#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scrapers.base import fetch_fx_rates
from scrapers.europe import scrape_all_europe
from scrapers.iceland import scrape_all_iceland
from scrapers.north_america import scrape_all_north_america

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

    iceland_prods, iceland_res = scrape_all_iceland(fx_rates)
    europe_prods, europe_res = scrape_all_europe(fx_rates)
    na_prods, na_res = scrape_all_north_america(fx_rates)

    all_products = iceland_prods + europe_prods + na_prods
    all_results = iceland_res + europe_res + na_res

    # Load previous deals & history
    prev_deals_data = load_json(DEALS_PATH, {"products": []})
    prev_by_id = {p["id"]: p for p in prev_deals_data.get("products", [])}
    history: dict[str, list[dict]] = load_json(HISTORY_PATH, {})

    enriched_products: list[dict] = []
    seen_ids: set[str] = set()

    for prod in all_products:
        if prod.id in seen_ids:
            continue
        seen_ids.add(prod.id)
        d = prod.to_dict()

        prev = prev_by_id.get(prod.id)
        if prev:
            prev_isk = prev.get("price_isk", d["price_isk"])
            if d["price_isk"] < prev_isk:
                drop_isk = prev_isk - d["price_isk"]
                drop_pct = round((drop_isk / prev_isk) * 100, 1)
                d["prev_price_isk"] = prev_isk
                d["price_drop_isk"] = drop_isk
                d["price_drop_pct"] = drop_pct
            else:
                d["prev_price_isk"] = prev_isk
                d["price_drop_isk"] = 0
                d["price_drop_pct"] = 0.0
        else:
            d["prev_price_isk"] = d["price_isk"]
            d["price_drop_isk"] = 0
            d["price_drop_pct"] = 0.0

        # Update price history (append if price changed or >12h since last point)
        pts = history.get(prod.id, [])
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

    enriched_products.sort(key=lambda x: x["estimated_landed_isk"])

    payload = {
        "updated_at": now_iso,
        "fx_rates": fx_rates,
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
