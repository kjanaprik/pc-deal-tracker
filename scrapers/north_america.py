from __future__ import annotations

import os
import time
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

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

    specs = extract_specs(title, description)
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
    """Amazon.com - Uses RAINFOREST_API_KEY if configured."""
    store = "Amazon.com"
    t0 = time.monotonic()
    rainforest_key = os.getenv("RAINFOREST_API_KEY", "").strip()
    if not rainforest_key:
        return [], StoreResult(
            store=store,
            region="USA/Canada",
            ships_to_iceland="Direct (Amazon Global)",
            status="skipped",
            count=0,
            error="Set RAINFOREST_API_KEY in GitHub Secrets to scrape Amazon.com",
            duration_ms=int((time.monotonic() - t0) * 1000),
        )

    products: dict[str, Product] = {}
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


def _scrape_via_scraperapi_or_direct(
    store: str,
    urls: list[str],
    base_url: str,
    ships_to_iceland: str,
    fx_rates: dict[str, float],
    notes: str,
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
                resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)

            html = None
            if resp.status_code in (403, 429, 503):
                html = fetch_rendered_html(url)
                if not html:
                    blocked = True
                    continue
            elif resp.status_code == 200:
                html = resp.text
                if len(html) < 25000:
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


def scrape_all_north_america(fx_rates: dict[str, float]) -> tuple[list[Product], list[StoreResult]]:
    all_products: list[Product] = []
    results: list[StoreResult] = []

    jobs = [
        scrape_bestbuy(fx_rates),
        scrape_amazon_us(fx_rates),
        _scrape_via_scraperapi_or_direct(
            store="B&H Photo",
            urls=[
                "https://www.bhphotovideo.com/c/search?q=gaming+desktop+rtx+5070+ti",
                "https://www.bhphotovideo.com/c/search?q=gaming+desktop+rtx+5080",
                "https://www.bhphotovideo.com/c/search?q=gaming+desktop+rtx+5060+ti",
            ],
            base_url="https://www.bhphotovideo.com",
            ships_to_iceland="Direct",
            fx_rates=fx_rates,
            notes="Ships direct to Iceland via DHL Express (Effortless Pre-Pay customs on most items)",
        ),
        _scrape_via_scraperapi_or_direct(
            store="Newegg",
            urls=[
                "https://www.newegg.com/p/pl?d=gaming+desktop+rtx+5070+ti",
                "https://www.newegg.com/p/pl?d=gaming+desktop+rtx+5080",
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
        _scrape_via_scraperapi_or_direct(
            store="XOTIC PC",
            urls=["https://xoticpc.com/collections/desktops"],
            base_url="https://xoticpc.com",
            ships_to_iceland="Quote Required",
            fx_rates=fx_rates,
            notes="Ships internationally to Iceland via custom quote (sales@xoticpc.com)",
        ),
        _scrape_via_scraperapi_or_direct(
            store="iBUYPOWER",
            urls=["https://www.ibuypower.com/gaming-pcs"],
            base_url="https://www.ibuypower.com",
            ships_to_iceland="Forwarder Required",
            fx_rates=fx_rates,
            notes="US/CA only; requires freight forwarder",
        ),
        _scrape_via_scraperapi_or_direct(
            store="CyberPowerPC",
            urls=["https://www.cyberpowerpc.com/category/gaming-pcs/"],
            base_url="https://www.cyberpowerpc.com",
            ships_to_iceland="Forwarder Required",
            fx_rates=fx_rates,
            notes="US/CA only; requires freight forwarder (UK branch ships EU on request)",
        ),
    ]

    for prods, res in jobs:
        all_products.extend(prods)
        results.append(res)
    return all_products, results
