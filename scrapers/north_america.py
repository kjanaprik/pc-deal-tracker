from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

try:
    from curl_cffi import requests as cffi_requests
except ImportError:
    cffi_requests = None

from scrapers.base import (
    DEFAULT_HEADERS,
    Product,
    StoreResult,
    compute_landed_isk,
    detect_target_gpu,
    extract_specs,
    fetch_rendered_html,
    is_desktop_pc,
    make_product_id,
    parse_price,
)

SEARCH_TERMS = ["RTX 5060 Ti 16GB", "RTX 5070 Ti", "RTX 5080"]


def _build_na_product(
    store: str,
    title: str,
    url: str,
    price_usd: float,
    fx_rates: dict[str, float],
    ships_to_iceland: str = "Forwarder Required",
    image_url: str = "",
    original_price_usd: Optional[float] = None,
    description: str = "",
    in_stock: bool = True,
    notes: str = "",
) -> Optional[Product]:
    gpu = detect_target_gpu(f"{title} {description}")
    if not gpu:
        return None
    if not is_desktop_pc(title, description):
        return None

    specs = extract_specs(title, description, store=store)
    sticker_isk, landed_isk = compute_landed_isk(
        price_original=price_usd,
        currency="USD",
        region="USA/Canada",
        fx_rates=fx_rates,
        local_vat_deducted=0.0,
    )
    orig_isk = None
    discount_pct = 0.0
    if original_price_usd and original_price_usd > price_usd:
        orig_isk = int(round(original_price_usd * fx_rates.get("USD", 138.0)))
        discount_pct = round(((original_price_usd - price_usd) / original_price_usd) * 100, 1)

    return Product(
        id=make_product_id(store, url),
        title=title.strip(),
        store=store,
        region="USA/Canada",
        ships_to_iceland=ships_to_iceland,
        url=url,
        image_url=image_url,
        price_original=round(price_usd, 2),
        currency="USD",
        price_isk=sticker_isk,
        estimated_landed_isk=landed_isk,
        gpu=gpu,
        cpu=specs["cpu"],
        cpu_brand=specs["cpu_brand"],
        ram_gb=specs["ram_gb"],
        storage_gb=specs["storage_gb"],
        storage_label=specs["storage_label"],
        brand=specs["brand"],
        original_price=round(original_price_usd, 2) if original_price_usd else None,
        original_price_isk=orig_isk,
        discount_pct=discount_pct,
        on_sale=discount_pct >= 1.0,
        in_stock=in_stock,
        notes=notes,
    )


def scrape_bestbuy(fx_rates: dict[str, float]) -> tuple[list[Product], StoreResult]:
    """Best Buy (bestbuy.com) - Uses BESTBUY_API_KEY if set, else falls back to web/Cloudflare/ScraperAPI."""
    store = "Best Buy"
    t0 = time.monotonic()
    api_key = os.getenv("BESTBUY_API_KEY", "").strip()
    if not api_key:
        return _scrape_via_scraperapi_or_direct(
            store=store,
            urls=[
                "https://www.bestbuy.com/site/searchpage.jsp?st=gaming+desktop+rtx+5070+ti",
                "https://www.bestbuy.com/site/searchpage.jsp?st=gaming+desktop+rtx+5080",
                "https://www.bestbuy.com/site/searchpage.jsp?st=gaming+desktop+rtx+5060+ti",
            ],
            base_url="https://www.bestbuy.com",
            ships_to_iceland="Forwarder Required",
            fx_rates=fx_rates,
            notes="US/CA domestic; requires freight forwarder (e.g. MyUS/ShopUSA)",
        )

    products: dict[str, Product] = {}
    try:
        for gpu_q in ("5060", "5070", "5080"):
            api_url = (
                f"https://api.bestbuy.com/v1/products((search=gaming&search=desktop&search={gpu_q})"
                f"&categoryPath.id=pcmcat287600050002)"
            )
            r = requests.get(
                api_url,
                params={
                    "apiKey": api_key,
                    "format": "json",
                    "pageSize": 25,
                    "show": "sku,name,salePrice,regularPrice,onSale,url,image,onlineAvailability,shortDescription",
                },
                timeout=15,
            )
            r.raise_for_status()
            for item in r.json().get("products", []):
                price = item.get("salePrice") or item.get("regularPrice")
                if not price:
                    continue
                reg_price = item.get("regularPrice")
                prod = _build_na_product(
                    store=store,
                    title=item.get("name", ""),
                    url=item.get("url", "https://www.bestbuy.com"),
                    price_usd=float(price),
                    fx_rates=fx_rates,
                    ships_to_iceland="Forwarder Required",
                    image_url=item.get("image", "") or "",
                    original_price_usd=float(reg_price) if reg_price and float(reg_price) > float(price) else None,
                    description=item.get("shortDescription", "") or "",
                    in_stock=bool(item.get("onlineAvailability", True)),
                    notes="US/CA domestic; requires freight forwarder (e.g. MyUS/ShopUSA)",
                )
                if prod:
                    products[prod.id] = prod

        return list(products.values()), StoreResult(
            store=store, region="USA/Canada", ships_to_iceland="Forwarder Required",
            status="ok", count=len(products), duration_ms=int((time.monotonic() - t0) * 1000)
        )
    except Exception as exc:
        return [], StoreResult(
            store=store, region="USA/Canada", ships_to_iceland="Forwarder Required",
            status="error", count=0, error=str(exc),
            duration_ms=int((time.monotonic() - t0) * 1000),
        )


def scrape_amazon_us(fx_rates: dict[str, float]) -> tuple[list[Product], StoreResult]:
    """Amazon.com - Uses RAINFOREST_API_KEY if set, else direct HTML on self-hosted runner."""
    store = "Amazon.com"
    t0 = time.monotonic()
    rainforest_key = os.getenv("RAINFOREST_API_KEY", "").strip()
    products: dict[str, Product] = {}
    if rainforest_key:
        try:
            for term in SEARCH_TERMS:
                r = requests.get(
                    "https://api.rainforestapi.com/request",
                    params={
                        "api_key": rainforest_key,
                        "type": "search",
                        "amazon_domain": "amazon.com",
                        "search_term": f"Gaming Desktop PC {term}",
                    },
                    timeout=25,
                )
                r.raise_for_status()
                for item in r.json().get("search_results", []):
                    price_info = item.get("price") or {}
                    price_val = price_info.get("value")
                    if not price_val or float(price_val) < 500:
                        continue
                    prod = _build_na_product(
                        store=store,
                        title=item.get("title", ""),
                        url=item.get("link", "https://www.amazon.com"),
                        price_usd=float(price_val),
                        fx_rates=fx_rates,
                        ships_to_iceland="Direct (Amazon Global)",
                        image_url=item.get("image", ""),
                        notes="Amazon Global calculates Icelandic VAT/import fees at checkout",
                    )
                    if prod:
                        products[prod.id] = prod
            return list(products.values()), StoreResult(
                store=store, region="USA/Canada", ships_to_iceland="Direct (Amazon Global)",
                status="ok", count=len(products), duration_ms=int((time.monotonic() - t0) * 1000)
            )
        except Exception as exc:
            return [], StoreResult(
                store=store, region="USA/Canada", ships_to_iceland="Direct (Amazon Global)",
                status="error", count=0, error=str(exc),
                duration_ms=int((time.monotonic() - t0) * 1000),
            )

    blocked = False
    fetcher = cffi_requests if cffi_requests else requests
    try:
        for term in ("gaming desktop rtx 5060 ti", "gaming desktop rtx 5070", "gaming desktop rtx 5080"):
            if cffi_requests:
                r = fetcher.get(
                    "https://www.amazon.com/s",
                    params={"k": term},
                    impersonate="chrome",
                    timeout=15,
                )
            else:
                r = fetcher.get(
                    "https://www.amazon.com/s",
                    params={"k": term},
                    headers=DEFAULT_HEADERS,
                    timeout=15,
                )
            if r.status_code in (202, 403, 503) or len(r.text) < 20000:
                blocked = True
                continue
            soup = BeautifulSoup(r.text, "lxml")
            for card in soup.select('[data-component-type="s-search-result"]'):
                title_el = card.select_one('[data-cy="title-recipe"] a span, h2 a span, h2 span, h2')
                link_el = card.select_one('[data-cy="title-recipe"] a[href], h2 a[href], a.a-link-normal[href*="/dp/"]')
                price_el = card.select_one(".a-price .a-offscreen")
                if not (title_el and link_el and price_el):
                    continue
                title = title_el.get_text(" ", strip=True)
                price_val = parse_price(price_el.get_text(strip=True), "USD")
                if not price_val or price_val < 500:
                    continue
                full_url = urljoin("https://www.amazon.com", link_el.get("href", "").split("ref=")[0])
                img_el = card.select_one("img.s-image")
                img_url = img_el.get("src", "") if img_el else ""
                old_el = card.select_one(".a-text-price .a-offscreen")
                old_val = parse_price(old_el.get_text(strip=True), "USD") if old_el else None

                prod = _build_na_product(
                    store=store,
                    title=title,
                    url=full_url,
                    price_usd=price_val,
                    fx_rates=fx_rates,
                    ships_to_iceland="Direct (Amazon Global)",
                    image_url=img_url,
                    original_price_usd=old_val,
                    notes="Amazon Global calculates Icelandic VAT/import fees at checkout",
                )
                if prod:
                    products[prod.id] = prod
            time.sleep(1.0)

        if blocked and not products:
            return [], StoreResult(
                store=store, region="USA/Canada", ships_to_iceland="Direct (Amazon Global)",
                status="blocked", count=0,
                error="Amazon.com bot challenge (set RAINFOREST_API_KEY to bypass)",
                duration_ms=int((time.monotonic() - t0) * 1000),
            )
        return list(products.values()), StoreResult(
            store=store, region="USA/Canada", ships_to_iceland="Direct (Amazon Global)",
            status="ok", count=len(products), duration_ms=int((time.monotonic() - t0) * 1000)
        )
    except Exception as exc:
        return list(products.values()), StoreResult(
            store=store, region="USA/Canada", ships_to_iceland="Direct (Amazon Global)",
            status="error", count=len(products), error=str(exc),
            duration_ms=int((time.monotonic() - t0) * 1000),
        )


def _scrape_via_scraperapi_or_direct(
    store: str,
    urls: list[str],
    base_url: str,
    ships_to_iceland: str,
    fx_rates: dict[str, float],
    notes: str,
    use_browser_fallback: bool = False,
) -> tuple[list[Product], StoreResult]:
    t0 = time.monotonic()
    scraper_api_key = os.getenv("SCRAPERAPI_KEY", "").strip()
    products: dict[str, Product] = {}
    blocked = False
    try:
        for url in urls:
            if scraper_api_key:
                resp = requests.get(
                    f"https://api.scraperapi.com?api_key={scraper_api_key}&url={url}&render=true",
                    timeout=35,
                )
            else:
                resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=12)

            html = None
            if resp.status_code in (403, 429, 503):
                if use_browser_fallback:
                    html = fetch_rendered_html(url)
                if not html:
                    blocked = True
                    continue
            elif resp.status_code == 200:
                html = resp.text
                if len(html) < 25000 and use_browser_fallback:
                    rendered = fetch_rendered_html(url)
                    if rendered:
                        html = rendered
            else:
                continue

            soup = BeautifulSoup(html, "lxml")
            for card in soup.select(".item-cell, .product-tile, [data-selenium='miniProductPage'], .product"):
                link_el = card.select_one("a[href]")
                if not link_el:
                    continue
                full_url = urljoin(base_url, link_el.get("href", ""))
                title_el = card.select_one(".item-title, .description, [data-selenium='miniProductPageProductName'], h2, h3") or link_el
                title = title_el.get_text(" ", strip=True)
                price_el = card.select_one(".price-current, .price, [data-selenium='uppedDecimalPriceFirst']")
                price_val = parse_price(price_el.get_text(" ", strip=True) if price_el else "", "USD")
                if not price_val or price_val < 500:
                    continue
                img_el = card.select_one("img")
                img_url = img_el.get("src", "") if img_el else ""
                prod = _build_na_product(
                    store=store, title=title, url=full_url, price_usd=price_val,
                    fx_rates=fx_rates, ships_to_iceland=ships_to_iceland,
                    image_url=img_url, description=card.get_text(" ", strip=True),
                    notes=notes,
                )
                if prod:
                    products[prod.id] = prod
            time.sleep(0.5)

        if blocked and not products:
            return [], StoreResult(
                store=store, region="USA/Canada", ships_to_iceland=ships_to_iceland,
                status="blocked", count=0,
                error="Bot protection active (set SCRAPERAPI_KEY or run via self-hosted Mac runner)",
                duration_ms=int((time.monotonic() - t0) * 1000),
            )
        return list(products.values()), StoreResult(
            store=store, region="USA/Canada", ships_to_iceland=ships_to_iceland,
            status="ok", count=len(products), duration_ms=int((time.monotonic() - t0) * 1000)
        )
    except Exception as exc:
        return list(products.values()), StoreResult(
            store=store, region="USA/Canada", ships_to_iceland=ships_to_iceland,
            status="error", count=len(products), error=str(exc),
            duration_ms=int((time.monotonic() - t0) * 1000),
        )


def scrape_xoticpc(fx_rates: dict[str, float]) -> tuple[list[Product], StoreResult]:
    """XOTIC PC (xoticpc.com) - Shopify JSON API."""
    store = "XOTIC PC"
    t0 = time.monotonic()
    products: dict[str, Product] = {}
    try:
        for page in (1, 2):
            r = requests.get(
                f"https://xoticpc.com/products.json?limit=250&page={page}",
                headers=DEFAULT_HEADERS,
                timeout=15,
            )
            if r.status_code != 200:
                break
            items = r.json().get("products", [])
            if not items:
                break
            for item in items:
                title = item.get("title", "")
                slug = item.get("handle", "")
                p_url = f"https://xoticpc.com/products/{slug}" if slug else "https://xoticpc.com"
                variants = item.get("variants") or []
                v0 = variants[0] if variants else {}
                price_val = parse_price(str(v0.get("price") or ""), "USD")
                if not price_val or price_val < 500:
                    continue
                compare_val = parse_price(str(v0.get("compare_at_price") or ""), "USD")
                images = item.get("images") or []
                img_url = images[0].get("src", "") if images else ""
                body_text = BeautifulSoup(item.get("body_html") or "", "lxml").get_text(" ", strip=True)
                in_stock = any(bool(v.get("available", True)) for v in variants) if variants else True

                prod = _build_na_product(
                    store=store,
                    title=title,
                    url=p_url,
                    price_usd=price_val,
                    fx_rates=fx_rates,
                    ships_to_iceland="Quote Required",
                    image_url=img_url,
                    original_price_usd=compare_val if compare_val and compare_val > price_val else None,
                    description=body_text,
                    in_stock=in_stock,
                    notes="Ships internationally to Iceland via custom quote (sales@xoticpc.com)",
                )
                if prod:
                    products[prod.id] = prod

        return list(products.values()), StoreResult(
            store=store, region="USA/Canada", ships_to_iceland="Quote Required",
            status="ok", count=len(products), duration_ms=int((time.monotonic() - t0) * 1000)
        )
    except Exception as exc:
        return list(products.values()), StoreResult(
            store=store, region="USA/Canada", ships_to_iceland="Quote Required",
            status="error", count=len(products), error=str(exc),
            duration_ms=int((time.monotonic() - t0) * 1000),
        )


def scrape_cyberpowerpc(fx_rates: dict[str, float]) -> tuple[list[Product], StoreResult]:
    """CyberPowerPC (cyberpowerpc.com) - .system__info cards."""
    store = "CyberPowerPC"
    t0 = time.monotonic()
    products: dict[str, Product] = {}
    try:
        r = requests.get("https://www.cyberpowerpc.com/category/gaming-pcs/", headers=DEFAULT_HEADERS, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        for card in soup.select(".system__info"):
            link_el = card.select_one("a[href*='/system/']")
            if not link_el:
                continue
            full_url = urljoin("https://www.cyberpowerpc.com", link_el.get("href", ""))
            title = link_el.get_text(" ", strip=True)
            if not title:
                continue
            card_text = card.get_text(" ", strip=True)
            import re as _re
            prices = [_parse_usd(m) for m in _re.findall(r"\$[\d,]+(?:\.\d{2})?", card_text)]
            prices = [p for p in prices if p and p >= 500]
            if not prices:
                continue
            price_val = min(prices)
            orig_val = max(prices) if len(prices) > 1 and max(prices) > price_val else None

            prod = _build_na_product(
                store=store,
                title=title,
                url=full_url,
                price_usd=price_val,
                fx_rates=fx_rates,
                ships_to_iceland="Forwarder Required",
                original_price_usd=orig_val,
                description=card_text,
                notes="US/CA only; requires freight forwarder (UK branch ships EU on request)",
            )
            if prod:
                products[prod.id] = prod

        return list(products.values()), StoreResult(
            store=store, region="USA/Canada", ships_to_iceland="Forwarder Required",
            status="ok", count=len(products), duration_ms=int((time.monotonic() - t0) * 1000)
        )
    except Exception as exc:
        return list(products.values()), StoreResult(
            store=store, region="USA/Canada", ships_to_iceland="Forwarder Required",
            status="error", count=len(products), error=str(exc),
            duration_ms=int((time.monotonic() - t0) * 1000),
        )


SERPAPI_STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "serpapi_state.json"

BHPHOTO_SERPAPI_QUERIES = [
    ("RTX 5080 16GB", "Desktop Computer RTX 5080"),
    ("RTX 5070 Ti 16GB", "Desktop Computer RTX 5070 Ti"),
    ("RTX 5060 Ti 16GB", "Desktop Computer RTX 5060 Ti 16GB"),
]

# B&H Photo-Video-Audio Google Merchant Center ID (from Google Shopping mid:)
BHPHOTO_MERCHANT_TBS = "mr:1,merchagg:m576462829555096145"


def _extract_bh_shoprs(data: dict) -> str:
    """Extract Google Shopping's Seller filter `shoprs` token for B&H Photo if present."""
    for group in data.get("filters") or []:
        for opt in group.get("options") or []:
            text = str(opt.get("text") or "").lower()
            if "b&h" in text and opt.get("shoprs"):
                return str(opt["shoprs"])
    return ""


def _load_serpapi_state() -> dict:
    if SERPAPI_STATE_PATH.exists():
        try:
            return json.loads(SERPAPI_STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_serpapi_state(state: dict) -> None:
    SERPAPI_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SERPAPI_STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def scrape_bhphoto(fx_rates: dict[str, float]) -> tuple[list[Product], StoreResult]:
    """B&H Photo (bhphotovideo.com) via SerpApi Google Shopping index.

    Uses a quota-friendly cooldown (12h normally, 4h during Black Friday Nov 26-30)
    so 3 queries/refresh stays comfortably within SerpApi's 250 free searches/month.
    Cached B&H listings are preserved by scrape_all.py during cooldown windows.
    """
    store = "B&H Photo"
    t0 = time.monotonic()
    serpapi_key = os.getenv("SERPAPI_KEY", "").strip()
    if not serpapi_key:
        return [], StoreResult(
            store=store,
            region="USA/Canada",
            ships_to_iceland="Direct",
            status="blocked",
            count=0,
            error="Set SERPAPI_KEY secret to enable automated B&H Photo Google Shopping tracking",
            duration_ms=int((time.monotonic() - t0) * 1000),
        )

    now = datetime.now(timezone.utc)
    now_ts = now.timestamp()
    force = os.getenv("FORCE_SERPAPI", "").strip().lower() in ("1", "true", "yes")
    is_bf_window = now.month == 11 and 26 <= now.day <= 30
    default_interval = 4.0 if is_bf_window else 12.0
    try:
        interval_hours = float(os.getenv("SERPAPI_INTERVAL_HOURS", "").strip() or default_interval)
    except ValueError:
        interval_hours = default_interval

    state = _load_serpapi_state()
    last_ts = float(state.get("bhphoto_last_run_ts", 0.0) or 0.0)
    elapsed_hours = (now_ts - last_ts) / 3600.0 if last_ts else 9999.0

    if not force and elapsed_hours < interval_hours:
        remaining = max(0.1, interval_hours - elapsed_hours)
        return [], StoreResult(
            store=store,
            region="USA/Canada",
            ships_to_iceland="Direct",
            status="ok",
            count=0,
            error=f"SerpApi quota cooldown ({remaining:.1f}h until next B&H refresh)",
            duration_ms=int((time.monotonic() - t0) * 1000),
        )

    products: dict[str, Product] = {}
    bh_shoprs = str(state.get("bh_shoprs") or "").strip()
    try:
        for expected_gpu, base_query in BHPHOTO_SERPAPI_QUERIES:
            params = {
                "engine": "google_shopping",
                "q": base_query if bh_shoprs else f"B&H Photo {base_query}",
                "gl": "us",
                "hl": "en",
                "num": "40",
                "direct_link": "true",
                "api_key": serpapi_key,
            }
            if bh_shoprs:
                params["shoprs"] = bh_shoprs
            else:
                params["tbs"] = BHPHOTO_MERCHANT_TBS

            r = requests.get("https://serpapi.com/search.json", params=params, timeout=25)
            r.raise_for_status()
            data = r.json()
            if data.get("error"):
                raise RuntimeError(f"SerpApi error: {data['error']}")

            # If tbs merchant filter returned 0 results, fall back to un-filtered B&H query
            if not data.get("shopping_results") and "tbs" in params:
                params.pop("tbs", None)
                r = requests.get("https://serpapi.com/search.json", params=params, timeout=25)
                r.raise_for_status()
                data = r.json()
                if data.get("error"):
                    raise RuntimeError(f"SerpApi error: {data['error']}")

            # Discover and cache Google Shopping's native B&H Seller filter token
            discovered_shoprs = _extract_bh_shoprs(data)
            if discovered_shoprs and not bh_shoprs:
                bh_shoprs = discovered_shoprs
                state["bh_shoprs"] = bh_shoprs
                print(f"[B&H SerpApi] Discovered B&H shoprs filter token: {bh_shoprs[:24]}...")

            results_list = data.get("shopping_results", [])
            bh_seen = 0
            bh_kept = 0
            bh_rejected = []
            for item in results_list:
                source = str(item.get("source") or "")
                link = str(item.get("link") or item.get("product_link") or "")
                if "b&h" not in source.lower() and "bhphotovideo.com" not in link.lower():
                    continue
                bh_seen += 1

                title = str(item.get("title") or "").strip()
                if not title or not link:
                    continue

                price_val = item.get("extracted_price")
                if price_val is None:
                    price_val = parse_price(str(item.get("price") or ""), "USD")
                else:
                    try:
                        price_val = float(price_val)
                    except (TypeError, ValueError):
                        price_val = None
                if not price_val or price_val < 500:
                    continue

                old_val = item.get("extracted_old_price")
                if old_val is None and item.get("old_price"):
                    old_val = parse_price(str(item.get("old_price")), "USD")
                elif old_val is not None:
                    try:
                        old_val = float(old_val)
                    except (TypeError, ValueError):
                        old_val = None

                extensions = item.get("extensions") or []
                ext_text = " ".join(str(x) for x in extensions if x)
                snippet = str(item.get("snippet") or "")
                tag = str(item.get("tag") or "")
                delivery = str(item.get("delivery") or "")
                description = " ".join(part for part in (snippet, ext_text, tag) if part)

                in_stock = not any(
                    oos in f"{ext_text} {delivery}".lower()
                    for oos in ("out of stock", "sold out", "temporarily out of stock")
                )

                # B&H Google Shopping titles often omit the GPU (e.g. "CyberPowerPC Gamer Supreme R7 9850X3D 32GB"),
                # AND Google Shopping mixes 12GB RTX 5070 / 8GB 5060 Ti builds into "RTX 5070 Ti" results.
                # Only apply the expected_gpu fallback for verified 16GB B&H builds/CPUs so 12GB 5070s never trigger false alerts.
                combined_text = f"{title} {description}"
                c_low = combined_text.lower()
                if "slc10200cpgv19" in c_low or "8700f" in c_low:
                    continue
                verified_bh_16gb_hints = (
                    "270k", "9800x3d", "9850x3d", "9900x3d", "9950x3d", "9900x",
                    "90ya0016us", "legion tower 5i", "dact1250", "aurora",
                    "slc11020", "slc10220", "slcai10600", "slcai8800",
                )
                if (
                    expected_gpu != "RTX 5060 Ti 16GB"
                    and not detect_target_gpu(combined_text)
                    and is_desktop_pc(title, description)
                    and any(h in c_low for h in verified_bh_16gb_hints)
                ):
                    import re as _re
                    other_gpu = _re.search(
                        r"\b(?:rtx\s*(?:20|30|40|50)\d{2}(?:\s*(?:ti|super))?|rx\s*\d{4}(?:\s*xt)?|8\s*gb\s*(?:gddr|vram)|12\s*gb\s*(?:gddr|vram))\b",
                        combined_text,
                        _re.IGNORECASE,
                    )
                    if not other_gpu:
                        description = f"{description} {expected_gpu}".strip()

                prod = _build_na_product(
                    store=store,
                    title=title,
                    url=link,
                    price_usd=price_val,
                    fx_rates=fx_rates,
                    ships_to_iceland="Direct",
                    image_url=str(item.get("thumbnail") or ""),
                    original_price_usd=old_val if old_val and old_val > price_val else None,
                    description=description,
                    in_stock=in_stock,
                    notes="Ships direct to Iceland via DHL Express (via Google Shopping / SerpApi)",
                )
                if prod:
                    # Google Shopping URLs share the base path /search?..., so key by unique product_id or title
                    gshop_pid = str(item.get("product_id") or "").strip()
                    if "google.com/search" in link.lower():
                        prod.id = make_product_id(store, f"https://bhphotovideo.com/gshop/{gshop_pid or title}")
                    products[prod.id] = prod
                    bh_kept += 1
                elif len(bh_rejected) < 5:
                    bh_rejected.append(f"${price_val:.0f} {title[:55]}")

            print(
                f"[B&H SerpApi] q={params['q']!r} (shoprs={'yes' if 'shoprs' in params else 'no'}) -> "
                f"total={len(results_list)}, bh_seen={bh_seen}, bh_kept={bh_kept}"
                + (f", rejected={bh_rejected}" if bh_rejected else "")
            )

        state["bhphoto_last_run_ts"] = now_ts
        state["bhphoto_last_run_iso"] = now.isoformat()
        state["bhphoto_last_count"] = len(products)
        _save_serpapi_state(state)

        return list(products.values()), StoreResult(
            store=store,
            region="USA/Canada",
            ships_to_iceland="Direct",
            status="ok",
            count=len(products),
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
    except Exception as exc:
        return list(products.values()), StoreResult(
            store=store,
            region="USA/Canada",
            ships_to_iceland="Direct",
            status="error",
            count=len(products),
            error=str(exc),
            duration_ms=int((time.monotonic() - t0) * 1000),
        )


def scrape_reddit_buildapcsales(fx_rates: dict[str, float]) -> tuple[list[Product], StoreResult]:
    """r/buildapcsales community Prebuilt deals via Arctic Shift public Reddit mirror."""
    import re as _re
    from urllib.parse import urlparse

    store = "r/buildapcsales"
    t0 = time.monotonic()
    products: dict[str, Product] = {}
    now_ts = time.time()
    cutoff_ts = now_ts - (7 * 86400)  # Last 7 days of deals

    try:
        before_ts = None
        for _page in range(2):  # Scan up to 100 latest posts
            params: dict[str, object] = {
                "subreddit": "buildapcsales",
                "limit": 50,
                "sort": "desc",
            }
            if before_ts is not None:
                params["before"] = int(before_ts)

            r = requests.get(
                "https://arctic-shift.photon-reddit.com/api/posts/search",
                params=params,
                headers={"User-Agent": "pc-deal-tracker/1.0"},
                timeout=15,
            )
            r.raise_for_status()
            posts = r.json().get("data") or []
            if not posts:
                break

            oldest_in_page = None
            for post in posts:
                created = float(post.get("created_utc") or 0)
                if created:
                    oldest_in_page = created if oldest_in_page is None else min(oldest_in_page, created)
                if created and created < cutoff_ts:
                    continue

                flair = str(post.get("link_flair_text") or "").lower()
                title = str(post.get("title") or "").strip()
                t_lower = title.lower()
                if not title:
                    continue
                if not any(tag in flair or tag in t_lower for tag in ("prebuilt", "[prebuilt]", "[desktop]", "gaming desktop", "gaming pc")):
                    continue
                if "expired" in flair or "out of stock" in flair:
                    continue

                # Extract USD price from title (e.g. $2,649 or $1899.99)
                m_price = _re.search(r"\$\s*([1-9],?\d{3}(?:\.\d{2})?|[6-9]\d{2}(?:\.\d{2})?)", title)
                if not m_price:
                    continue
                price_val = parse_price(m_price.group(1), "USD")
                if not price_val or price_val < 600:
                    continue

                permalink = str(post.get("permalink") or "").strip()
                reddit_url = f"https://www.reddit.com{permalink}" if permalink else str(post.get("url") or "")
                deal_url = str(post.get("url") or "")
                domain = urlparse(deal_url).netloc.replace("www.", "") if deal_url else "reddit.com"

                # Clean leading "[Prebuilt]" tag for readability
                clean_title = _re.sub(r"^\s*\[(?:prebuilt|desktop|pc)\]\s*", "", title, flags=_re.IGNORECASE).strip()
                selftext = str(post.get("selftext") or "")[:400]
                thumb = str(post.get("thumbnail") or "")
                if not thumb.startswith("http"):
                    thumb = ""

                prod = _build_na_product(
                    store=store,
                    title=clean_title,
                    url=reddit_url,
                    price_usd=price_val,
                    fx_rates=fx_rates,
                    ships_to_iceland="Direct" if "bhphotovideo.com" in domain else "Forwarder Required",
                    image_url=thumb,
                    description=selftext,
                    in_stock=True,
                    notes=f"Posted on r/buildapcsales ({domain}) — check thread for coupon/stock",
                )
                if prod:
                    products[prod.id] = prod

            if oldest_in_page is None or oldest_in_page < cutoff_ts:
                break
            before_ts = oldest_in_page

        return list(products.values()), StoreResult(
            store=store,
            region="USA/Canada",
            ships_to_iceland="Forwarder Required",
            status="ok",
            count=len(products),
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
    except Exception as exc:
        return list(products.values()), StoreResult(
            store=store,
            region="USA/Canada",
            ships_to_iceland="Forwarder Required",
            status="error",
            count=len(products),
            error=str(exc),
            duration_ms=int((time.monotonic() - t0) * 1000),
        )


def scrape_reddit_prebuilts(fx_rates: dict[str, float]) -> tuple[list[Product], StoreResult]:
    """r/Prebuilts community deals via Arctic Shift public Reddit mirror."""
    import re as _re
    from urllib.parse import urlparse

    store = "r/Prebuilts"
    t0 = time.monotonic()
    products: dict[str, Product] = {}
    now_ts = time.time()
    cutoff_ts = now_ts - (7 * 86400)

    try:
        before_ts = None
        for _page in range(2):  # Scan up to 100 latest posts
            params: dict[str, object] = {
                "subreddit": "Prebuilts",
                "limit": 50,
                "sort": "desc",
            }
            if before_ts is not None:
                params["before"] = int(before_ts)

            r = requests.get(
                "https://arctic-shift.photon-reddit.com/api/posts/search",
                params=params,
                headers={"User-Agent": "pc-deal-tracker/1.0"},
                timeout=15,
            )
            r.raise_for_status()
            posts = r.json().get("data") or []
            if not posts:
                break

            oldest_in_page = None
            for post in posts:
                created = float(post.get("created_utc") or 0)
                if created:
                    oldest_in_page = created if oldest_in_page is None else min(oldest_in_page, created)
                if created and created < cutoff_ts:
                    continue

                title = str(post.get("title") or "").strip()
                selftext = str(post.get("selftext") or "")[:500]
                if not title:
                    continue
                t_lower = title.lower()
                # Skip pure recommendation/help threads without a specific priced build
                if any(q in t_lower for q in ("what's the best", "whats the best", "help me", "recommend", "looking for")):
                    continue

                combined = f"{title} {selftext}"
                if not detect_target_gpu(combined):
                    continue

                m_price = _re.search(r"\$\s*([1-9],?\d{3}(?:\.\d{2})?|[6-9]\d{2}(?:\.\d{2})?)", combined)
                if not m_price:
                    continue
                price_val = parse_price(m_price.group(1), "USD")
                if not price_val or price_val < 600:
                    continue

                permalink = str(post.get("permalink") or "").strip()
                reddit_url = f"https://www.reddit.com{permalink}" if permalink else str(post.get("url") or "")
                deal_url = str(post.get("url") or "")
                domain = urlparse(deal_url).netloc.replace("www.", "") if deal_url else "reddit.com"
                thumb = str(post.get("thumbnail") or "")
                if not thumb.startswith("http"):
                    thumb = ""

                # Ensure desktop context for r/Prebuilts posts whose title is brief
                desc = f"Prebuilt Desktop PC {selftext}".strip()
                prod = _build_na_product(
                    store=store,
                    title=title,
                    url=reddit_url,
                    price_usd=price_val,
                    fx_rates=fx_rates,
                    ships_to_iceland="Direct" if "bhphotovideo.com" in domain else "Forwarder Required",
                    image_url=thumb,
                    description=desc,
                    in_stock=True,
                    notes=f"Posted on r/Prebuilts ({domain})",
                )
                if prod:
                    products[prod.id] = prod

            if oldest_in_page is None or oldest_in_page < cutoff_ts:
                break
            before_ts = oldest_in_page

        return list(products.values()), StoreResult(
            store=store,
            region="USA/Canada",
            ships_to_iceland="Forwarder Required",
            status="ok",
            count=len(products),
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
    except Exception as exc:
        return list(products.values()), StoreResult(
            store=store,
            region="USA/Canada",
            ships_to_iceland="Forwarder Required",
            status="error",
            count=len(products),
            error=str(exc),
            duration_ms=int((time.monotonic() - t0) * 1000),
        )


BH_PRICEMATCH_TARGETS = [
    {
        "mpn": "SLC11020CPGV4",
        "bh_price": 2749.99,
        "gpu": "RTX 5070 Ti 16GB",
        "specs": "CyberPowerPC Gamer Supreme (Ryzen 7 9800X3D, 32GB DDR5, 2TB NVMe, RTX 5070 Ti 16GB)",
    },
    {
        "mpn": "SLC10220CPGV22",
        "bh_price": 2599.99,
        "gpu": "RTX 5070 Ti 16GB",
        "specs": "CyberPowerPC Gamer Supreme (Core Ultra 7 270K Plus, 32GB DDR5, 2TB NVMe, RTX 5070 Ti 16GB)",
    },
    {
        "mpn": "DACT1250-9216BLU-PUS",
        "bh_price": 2799.00,
        "gpu": "RTX 5070 Ti 16GB",
        "specs": "Dell Alienware Aurora (Core Ultra 9 285, 32GB DDR5, 1TB NVMe, RTX 5070 Ti 16GB)",
    },
    {
        "mpn": "SLCAI10600CPG",
        "bh_price": 3079.99,
        "gpu": "RTX 5070 Ti 16GB",
        "specs": "CyberPowerPC Gamer Supreme (Ryzen 7 9850X3D, 32GB DDR5, 2TB NVMe, RTX 5070 Ti 16GB)",
    },
]


def scrape_bh_pricematch_targets(fx_rates: dict[str, float]) -> tuple[list[Product], StoreResult]:
    """Monitor exact B&H Photo MFR model numbers across US competitors for price-match opportunities."""
    store = "B&H Price Match"
    t0 = time.monotonic()
    serpapi_key = os.getenv("SERPAPI_KEY", "").strip()
    if not serpapi_key:
        return [], StoreResult(
            store=store,
            region="USA/Canada",
            ships_to_iceland="Direct",
            status="blocked",
            count=0,
            error="Set SERPAPI_KEY secret to monitor B&H competitor price-match targets",
            duration_ms=int((time.monotonic() - t0) * 1000),
        )

    now = datetime.now(timezone.utc)
    now_ts = now.timestamp()
    force = os.getenv("FORCE_SERPAPI", "").strip().lower() in ("1", "true", "yes")
    is_bf_window = now.month == 11 and 26 <= now.day <= 30
    interval_hours = 6.0 if is_bf_window else 12.0

    state = _load_serpapi_state()
    last_ts = float(state.get("bh_pm_last_run_ts", 0.0) or 0.0)
    elapsed_hours = (now_ts - last_ts) / 3600.0 if last_ts else 9999.0
    if not force and elapsed_hours < interval_hours:
        remaining = max(0.1, interval_hours - elapsed_hours)
        return [], StoreResult(
            store=store,
            region="USA/Canada",
            ships_to_iceland="Direct",
            status="ok",
            count=0,
            error=f"Price-match cooldown ({remaining:.1f}h until next competitor scan)",
            duration_ms=int((time.monotonic() - t0) * 1000),
        )

    products: dict[str, Product] = {}
    try:
        for target in BH_PRICEMATCH_TARGETS:
            mpn = target["mpn"]
            bh_price = float(target["bh_price"])
            r = requests.get(
                "https://serpapi.com/search.json",
                params={
                    "engine": "google_shopping",
                    "q": mpn,
                    "gl": "us",
                    "hl": "en",
                    "num": "20",
                    "direct_link": "true",
                    "api_key": serpapi_key,
                },
                timeout=25,
            )
            r.raise_for_status()
            data = r.json()
            if data.get("error"):
                raise RuntimeError(f"SerpApi error: {data['error']}")

            results_list = data.get("shopping_results", [])
            matched = 0
            for item in results_list:
                source = str(item.get("source") or "").strip()
                src_low = source.lower()
                # Skip B&H itself and used/auction marketplaces B&H never matches
                if not source or "b&h" in src_low or any(bad in src_low for bad in ("ebay", "mercari", "poshmark", "stockx")):
                    continue
                if item.get("second_hand_condition"):
                    continue

                price_val = item.get("extracted_price")
                if price_val is None:
                    price_val = parse_price(str(item.get("price") or ""), "USD")
                else:
                    try:
                        price_val = float(price_val)
                    except (TypeError, ValueError):
                        price_val = None
                # Only keep genuine price-match candidates strictly cheaper than B&H (and realistic >= $1,500)
                if not price_val or price_val < 1500 or price_val >= bh_price - 10:
                    continue

                link = str(item.get("link") or item.get("product_link") or "").strip()
                if not link:
                    continue

                extensions = item.get("extensions") or []
                ext_text = " ".join(str(x) for x in extensions if x)
                delivery = str(item.get("delivery") or "")
                if any(oos in f"{ext_text} {delivery}".lower() for oos in ("out of stock", "sold out", "backorder", "refurbished", "used")):
                    continue

                savings = round(bh_price - price_val, 2)
                title = f"[PM vs B&H -${savings:,.0f}] {mpn} @ {source} — {target['specs']}"
                prod = _build_na_product(
                    store=store,
                    title=title,
                    url=link,
                    price_usd=price_val,
                    fx_rates=fx_rates,
                    ships_to_iceland="Direct",
                    image_url=str(item.get("thumbnail") or ""),
                    original_price_usd=bh_price,
                    description=f"Desktop PC {target['specs']} {ext_text}",
                    in_stock=True,
                    notes=f"Exact B&H MFR {mpn} cheaper at {source} (${price_val:,.2f} vs B&H ${bh_price:,.2f}) — request B&H Price Match!",
                )
                if prod:
                    prod.id = make_product_id(store, f"https://bh-pm.local/{mpn}/{src_low}")
                    products[prod.id] = prod
                    matched += 1

            print(f"[B&H PM Monitor] mpn={mpn} (B&H=${bh_price:,.2f}) -> total={len(results_list)}, cheaper_competitors={matched}")

        state["bh_pm_last_run_ts"] = now_ts
        state["bh_pm_last_run_iso"] = now.isoformat()
        state["bh_pm_last_count"] = len(products)
        _save_serpapi_state(state)

        return list(products.values()), StoreResult(
            store=store,
            region="USA/Canada",
            ships_to_iceland="Direct",
            status="ok",
            count=len(products),
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
    except Exception as exc:
        return list(products.values()), StoreResult(
            store=store,
            region="USA/Canada",
            ships_to_iceland="Direct",
            status="error",
            count=len(products),
            error=str(exc),
            duration_ms=int((time.monotonic() - t0) * 1000),
        )


def _parse_usd(s: str) -> Optional[float]:
    return parse_price(s, "USD")


def scrape_all_north_america(fx_rates: dict[str, float]) -> tuple[list[Product], list[StoreResult]]:
    all_products: list[Product] = []
    results: list[StoreResult] = []

    jobs = [
        scrape_bestbuy(fx_rates),
        scrape_amazon_us(fx_rates),
        scrape_bhphoto(fx_rates),
        scrape_bh_pricematch_targets(fx_rates),
        scrape_reddit_buildapcsales(fx_rates),
        scrape_reddit_prebuilts(fx_rates),
        _scrape_via_scraperapi_or_direct(
            store="Newegg",
            urls=[
                "https://www.newegg.com/p/pl?N=601468633%20601470140%20601470139%20601483613%20100897483%208000",
                "https://www.newegg.com/p/pl?N=601468633%20601470140%20601470139%20601483613%20100897483%208000&d=9800x3d+prebuilt",
            ],
            base_url="https://www.newegg.com",
            ships_to_iceland="Forwarder Required",
            fx_rates=fx_rates,
            notes="US/CA domestic; requires freight forwarder",
        ),
        _scrape_via_scraperapi_or_direct(
            store="Costco",
            urls=["https://www.costco.com/gaming-computers.html"],
            base_url="https://www.costco.com",
            ships_to_iceland="Forwarder Required",
            fx_rates=fx_rates,
            notes="US/CA membership + freight forwarder required",
        ),
        _scrape_via_scraperapi_or_direct(
            store="ORIGIN PC",
            urls=["https://www.originpc.com/gaming/desktops/"],
            base_url="https://www.originpc.com",
            ships_to_iceland="Quote Required",
            fx_rates=fx_rates,
            notes="Ships internationally to Iceland via custom freight quote",
        ),
        scrape_xoticpc(fx_rates),
        _scrape_via_scraperapi_or_direct(
            store="iBUYPOWER",
            urls=["https://www.ibuypower.com/gaming-pcs"],
            base_url="https://www.ibuypower.com",
            ships_to_iceland="Forwarder Required",
            fx_rates=fx_rates,
            notes="US/CA only; requires freight forwarder",
        ),
        scrape_cyberpowerpc(fx_rates),
    ]

    for prods, res in jobs:
        all_products.extend(prods)
        results.append(res)
    return all_products, results
