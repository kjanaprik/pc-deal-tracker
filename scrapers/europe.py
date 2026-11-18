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


def _build_eu_product(
    store: str,
    title: str,
    url: str,
    price: float,
    currency: str,
    fx_rates: dict[str, float],
    local_vat: float = 0.19,
    ships_to_iceland: str = "Direct",
    image_url: str = "",
    original_price: Optional[float] = None,
    description: str = "",
    notes: str = "",
) -> Optional[Product]:
    gpu = detect_target_gpu(f"{title} {description}")
    if not gpu:
        return None
    if not is_desktop_pc(title, description):
        return None

    specs = extract_specs(title, description, store=store)
    sticker_isk, landed_isk = compute_landed_isk(
        price_original=price,
        currency=currency,
        region="Europe",
        fx_rates=fx_rates,
        local_vat_deducted=local_vat,
    )
    orig_isk = None
    discount_pct = 0.0
    if original_price and original_price > price:
        orig_isk = int(round(original_price * fx_rates.get(currency, 150.0)))
        discount_pct = round(((original_price - price) / original_price) * 100, 1)

    return Product(
        id=make_product_id(store, url),
        title=title.strip(),
        store=store,
        region="Europe",
        ships_to_iceland=ships_to_iceland,
        url=url,
        image_url=image_url,
        price_original=round(price, 2),
        currency=currency,
        price_isk=sticker_isk,
        estimated_landed_isk=landed_isk,
        gpu=gpu,
        cpu=specs["cpu"],
        cpu_brand=specs["cpu_brand"],
        ram_gb=specs["ram_gb"],
        storage_gb=specs["storage_gb"],
        storage_label=specs["storage_label"],
        brand=specs["brand"],
        original_price=round(original_price, 2) if original_price else None,
        original_price_isk=orig_isk,
        discount_pct=discount_pct,
        on_sale=discount_pct >= 1.0,
        in_stock=True,
        notes=notes,
    )


def _fetch_with_optional_proxy(url: str) -> requests.Response:
    scraper_api_key = os.getenv("SCRAPERAPI_KEY", "").strip()
    if scraper_api_key:
        proxy_url = f"https://api.scraperapi.com?api_key={scraper_api_key}&url={url}"
        return requests.get(proxy_url, timeout=30)
    return requests.get(url, headers=DEFAULT_HEADERS, timeout=15)


def scrape_memorypc(fx_rates: dict[str, float]) -> tuple[list[Product], StoreResult]:
    """Memory PC (memorypc.de) - Ships internationally; 19% German VAT deducted."""
    store = "Memory PC"
    t0 = time.monotonic()
    products: dict[str, Product] = {}
    try:
        for url in [
            "https://www.memorypc.de/gaming-pc/",
            "https://www.memorypc.de/search?search=5070",
            "https://www.memorypc.de/search?search=5080",
            "https://www.memorypc.de/search?search=5060",
        ]:
            resp = _fetch_with_optional_proxy(url)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "lxml")
            for card in soup.select(".card.product-box, .product-box"):
                link_el = card.select_one("a.product-name, a.product-image-link, a[href]")
                if not link_el:
                    continue
                full_url = urljoin("https://www.memorypc.de", link_el.get("href", ""))
                title = link_el.get("title") or link_el.get_text(" ", strip=True)
                price_el = card.select_one(".product-price, .price")
                price_val = parse_price(price_el.get_text(" ", strip=True) if price_el else "", "EUR")
                if not price_val or price_val < 500:
                    continue
                old_el = card.select_one(".list-price-price, .list-price, .product-price-old, del")
                old_val = parse_price(old_el.get_text(" ", strip=True), "EUR") if old_el else None
                img_el = card.select_one("img")
                img_url = img_el.get("src", "") if img_el else ""

                prod = _build_eu_product(
                    store=store,
                    title=title,
                    url=full_url,
                    price=price_val,
                    currency="EUR",
                    fx_rates=fx_rates,
                    local_vat=0.19,
                    ships_to_iceland="Direct",
                    image_url=img_url,
                    original_price=old_val,
                    description=card.get_text(" ", strip=True),
                    notes="19% DE VAT deducted at export; +24% IS VAT on import",
                )
                if prod:
                    products[prod.id] = prod
            time.sleep(0.5)

        return list(products.values()), StoreResult(
            store=store, region="Europe", ships_to_iceland="Direct",
            status="ok", count=len(products), duration_ms=int((time.monotonic() - t0) * 1000)
        )
    except Exception as exc:
        return list(products.values()), StoreResult(
            store=store, region="Europe", ships_to_iceland="Direct",
            status="error", count=len(products), error=str(exc),
            duration_ms=int((time.monotonic() - t0) * 1000),
        )


def scrape_overclockers_uk(fx_rates: dict[str, float]) -> tuple[list[Product], StoreResult]:
    """Overclockers UK (overclockers.co.uk) - Ships to Iceland via DHL Worldwide Express."""
    store = "Overclockers UK"
    t0 = time.monotonic()
    products: dict[str, Product] = {}
    try:
        for url in [
            "https://www.overclockers.co.uk/pc-systems/gaming-pcs",
            "https://www.overclockers.co.uk/pc-systems/gaming-pcs?page=2",
            "https://www.overclockers.co.uk/search?sSearch=RTX+5070+Ti+PC",
            "https://www.overclockers.co.uk/search?sSearch=RTX+5080+PC",
            "https://www.overclockers.co.uk/search?sSearch=RTX+5060+Ti+PC",
        ]:
            resp = _fetch_with_optional_proxy(url)
            if resp.status_code == 403:
                return [], StoreResult(
                    store=store, region="Europe", ships_to_iceland="Direct",
                    status="blocked", count=0, error="403 Forbidden (bot protection; set SCRAPERAPI_KEY or run locally)",
                    duration_ms=int((time.monotonic() - t0) * 1000),
                )
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "lxml")
            for card in soup.select(".product-tile, .product-box, .product-card, .js-product-card, article[data-product-id]"):
                link_el = card.select_one("a.link.d-block, a[href*='.html'], a[href]")
                if not link_el:
                    continue
                full_url = urljoin("https://www.overclockers.co.uk", link_el.get("href", ""))
                title_el = card.select_one("a.link.d-block, h2, h3, .product-title, .h6, [data-qa='product-title']")
                title = title_el.get_text(" ", strip=True) if title_el else ""
                if not title:
                    for a in card.select("a[href]"):
                        txt = a.get_text(" ", strip=True)
                        if len(txt) > 10:
                            title = txt
                            break
                if not title:
                    continue
                price_el = card.select_one(".price, [data-qa='product-price'], [class*='price']")
                price_val = parse_price(price_el.get_text(" ", strip=True) if price_el else card.get_text(" "), "GBP")
                if not price_val or price_val < 500:
                    continue
                img_el = card.select_one("img")
                img_url = img_el.get("src", "") if img_el else ""
                prod = _build_eu_product(
                    store=store,
                    title=title,
                    url=full_url,
                    price=price_val,
                    currency="GBP",
                    fx_rates=fx_rates,
                    local_vat=0.20,
                    ships_to_iceland="Direct",
                    image_url=img_url,
                    description=card.get_text(" ", strip=True),
                    notes="Ships to Iceland via DHL (20% UK VAT removed); verify live checkout as OCUK occasionally pauses non-UK shipping",
                )
                if prod:
                    products[prod.id] = prod
            time.sleep(0.5)

        return list(products.values()), StoreResult(
            store=store, region="Europe", ships_to_iceland="Direct",
            status="ok", count=len(products), duration_ms=int((time.monotonic() - t0) * 1000)
        )
    except Exception as exc:
        return list(products.values()), StoreResult(
            store=store, region="Europe", ships_to_iceland="Direct",
            status="error", count=len(products), error=str(exc),
            duration_ms=int((time.monotonic() - t0) * 1000),
        )


def _scrape_generic_eu_site(
    store: str,
    urls: list[str],
    base_url: str,
    currency: str,
    local_vat: float,
    fx_rates: dict[str, float],
    notes: str,
) -> tuple[list[Product], StoreResult]:
    t0 = time.monotonic()
    products: dict[str, Product] = {}
    blocked = False
    try:
        for url in urls:
            html = None
            resp = _fetch_with_optional_proxy(url)
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
            for card in soup.select(".product, .product-box, .product-card, article"):
                link_el = card.select_one("a[href]")
                if not link_el:
                    continue
                full_url = urljoin(base_url, link_el.get("href", ""))
                title_el = card.select_one("h2, h3, .product-title, .title") or link_el
                title = title_el.get_text(" ", strip=True)
                price_el = card.select_one(".price, .product-price")
                price_val = parse_price(price_el.get_text(" ", strip=True) if price_el else "", currency)
                if not price_val or price_val < 500:
                    continue
                prod = _build_eu_product(
                    store=store, title=title, url=full_url, price=price_val,
                    currency=currency, fx_rates=fx_rates, local_vat=local_vat,
                    ships_to_iceland="Direct", description=card.get_text(" ", strip=True),
                    notes=notes,
                )
                if prod:
                    products[prod.id] = prod
            time.sleep(0.5)

        if blocked and not products:
            return [], StoreResult(
                store=store, region="Europe", ships_to_iceland="Direct",
                status="blocked", count=0,
                error="Cloudflare/bot protection (set SCRAPERAPI_KEY or use self-hosted runner)",
                duration_ms=int((time.monotonic() - t0) * 1000),
            )
        return list(products.values()), StoreResult(
            store=store, region="Europe", ships_to_iceland="Direct",
            status="ok", count=len(products), duration_ms=int((time.monotonic() - t0) * 1000)
        )
    except Exception as exc:
        return list(products.values()), StoreResult(
            store=store, region="Europe", ships_to_iceland="Direct",
            status="error", count=len(products), error=str(exc),
            duration_ms=int((time.monotonic() - t0) * 1000),
        )


def _scrape_amazon_eu(
    store: str,
    domain: str,
    currency: str,
    local_vat: float,
    fx_rates: dict[str, float],
) -> tuple[list[Product], StoreResult]:
    """Amazon.de / Amazon.co.uk - Uses Rainforest API if set, else direct HTML on self-hosted runner."""
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
                        "amazon_domain": domain,
                        "search_term": f"Gaming Desktop PC {term}",
                    },
                    timeout=25,
                )
                r.raise_for_status()
                for item in r.json().get("search_results", []):
                    title = item.get("title", "")
                    price_info = item.get("price") or {}
                    price_val = price_info.get("value")
                    if not price_val or float(price_val) < 500:
                        continue
                    prod = _build_eu_product(
                        store=store,
                        title=title,
                        url=item.get("link", f"https://www.{domain}"),
                        price=float(price_val),
                        currency=currency,
                        fx_rates=fx_rates,
                        local_vat=local_vat,
                        ships_to_iceland="Direct (Amazon Global)",
                        image_url=item.get("image", ""),
                        notes="Amazon Global calculates Icelandic import fees at checkout",
                    )
                    if prod:
                        products[prod.id] = prod
            return list(products.values()), StoreResult(
                store=store, region="Europe", ships_to_iceland="Direct",
                status="ok", count=len(products), duration_ms=int((time.monotonic() - t0) * 1000)
            )
        except Exception as exc:
            return [], StoreResult(
                store=store, region="Europe", ships_to_iceland="Direct",
                status="error", count=0, error=str(exc),
                duration_ms=int((time.monotonic() - t0) * 1000),
            )

    # Direct HTML scraping (works from residential self-hosted runner)
    blocked = False
    try:
        for term in ("gaming desktop rtx 5060 ti", "gaming desktop rtx 5070", "gaming desktop rtx 5080"):
            r = requests.get(
                f"https://www.{domain}/s",
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
                price_txt = price_el.get_text(strip=True)
                card_cur = "USD" if ("USD" in price_txt or "$" in price_txt) else ("GBP" if "£" in price_txt else currency)
                price_val = parse_price(price_txt, card_cur)
                if not price_val or price_val < 500:
                    continue
                full_url = urljoin(f"https://www.{domain}", link_el.get("href", "").split("ref=")[0])
                img_el = card.select_one("img.s-image")
                img_url = img_el.get("src", "") if img_el else ""
                old_el = card.select_one(".a-text-price .a-offscreen")
                old_val = parse_price(old_el.get_text(strip=True), card_cur) if old_el else None

                prod = _build_eu_product(
                    store=store,
                    title=title,
                    url=full_url,
                    price=price_val,
                    currency=card_cur,
                    fx_rates=fx_rates,
                    local_vat=0.0 if card_cur == "USD" else local_vat,
                    ships_to_iceland="Direct (Amazon Global)",
                    image_url=img_url,
                    original_price=old_val,
                    notes="Amazon Global calculates Icelandic VAT/import fees at checkout",
                )
                if prod:
                    products[prod.id] = prod
            time.sleep(1.0)

        if blocked and not products:
            return [], StoreResult(
                store=store, region="Europe", ships_to_iceland="Direct",
                status="blocked", count=0,
                error="Amazon bot challenge (set RAINFOREST_API_KEY to bypass)",
                duration_ms=int((time.monotonic() - t0) * 1000),
            )
        return list(products.values()), StoreResult(
            store=store, region="Europe", ships_to_iceland="Direct",
            status="ok", count=len(products), duration_ms=int((time.monotonic() - t0) * 1000)
        )
    except Exception as exc:
        return list(products.values()), StoreResult(
            store=store, region="Europe", ships_to_iceland="Direct",
            status="error", count=len(products), error=str(exc),
            duration_ms=int((time.monotonic() - t0) * 1000),
        )


def scrape_all_europe(fx_rates: dict[str, float]) -> tuple[list[Product], list[StoreResult]]:
    all_products: list[Product] = []
    results: list[StoreResult] = []

    jobs = [
        scrape_memorypc(fx_rates),
        scrape_overclockers_uk(fx_rates),
        _scrape_generic_eu_site(
            store="Caseking",
            urls=["https://www.caseking.de/en/pc-systems/gaming-pcs"],
            base_url="https://www.caseking.de",
            currency="EUR",
            local_vat=0.19,
            fx_rates=fx_rates,
            notes="Ships to Iceland; 19% DE VAT deducted",
        ),
        _scrape_generic_eu_site(
            store="Computeruniverse",
            urls=["https://www.computeruniverse.net/en/c/hardware-components/gaming-pcs"],
            base_url="https://www.computeruniverse.net",
            currency="EUR",
            local_vat=0.19,
            fx_rates=fx_rates,
            notes="Ships to Iceland; 19% DE VAT deducted",
        ),
        _scrape_generic_eu_site(
            store="PCSpecialist",
            urls=["https://www.pcspecialist.co.uk/desktop-pcs/"],
            base_url="https://www.pcspecialist.co.uk",
            currency="GBP",
            local_vat=0.20,
            fx_rates=fx_rates,
            notes="Custom EU/UK builder shipping to Iceland",
        ),
        _scrape_generic_eu_site(
            store="CSL Computer",
            urls=["https://www.csl-computer.com/en/gaming-pcs"],
            base_url="https://www.csl-computer.com",
            currency="EUR",
            local_vat=0.19,
            fx_rates=fx_rates,
            notes="German builder with European shipping",
        ),
        _scrape_generic_eu_site(
            store="Alternate.de",
            urls=["https://www.alternate.de/Gaming-PC"],
            base_url="https://www.alternate.de",
            currency="EUR",
            local_vat=0.0,
            fx_rates=fx_rates,
            notes="Germany domestic; requires parcel forwarder (e.g. Mailboxde / ShipGerman)",
        ),
        _scrape_generic_eu_site(
            store="Cyberport.de",
            urls=["https://www.cyberport.de/pc-und-zubehoer/pc-systeme/gaming-pc.html"],
            base_url="https://www.cyberport.de",
            currency="EUR",
            local_vat=0.0,
            fx_rates=fx_rates,
            notes="DE/AT domestic; requires parcel forwarder (e.g. Mailboxde / ShipGerman)",
        ),
        _scrape_amazon_eu("Amazon.de", "amazon.de", "EUR", 0.19, fx_rates),
        _scrape_amazon_eu("Amazon.co.uk", "amazon.co.uk", "GBP", 0.20, fx_rates),
    ]

    for prods, res in jobs:
        all_products.extend(prods)
        results.append(res)
    return all_products, results
