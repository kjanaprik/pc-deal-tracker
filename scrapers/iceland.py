from __future__ import annotations

import json
import re
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

SEARCH_TERMS = ["5060", "5070", "5080"]


def _build_iceland_product(
    store: str,
    title: str,
    url: str,
    price_isk: float,
    image_url: str = "",
    original_price_isk: Optional[float] = None,
    description: str = "",
    in_stock: bool = True,
    fx_rates: Optional[dict[str, float]] = None,
) -> Optional[Product]:
    gpu = detect_target_gpu(f"{title} {description}")
    if not gpu:
        return None
    if not is_desktop_pc(title, description):
        return None

    specs = extract_specs(title, description)
    price_int = int(round(price_isk))
    orig_int = int(round(original_price_isk)) if original_price_isk and original_price_isk > price_isk else None
    discount_pct = round(((orig_int - price_int) / orig_int) * 100, 1) if orig_int else 0.0

    return Product(
        id=make_product_id(store, url),
        title=title.strip(),
        store=store,
        region="Iceland",
        ships_to_iceland="Local",
        url=url,
        image_url=image_url,
        price_original=float(price_int),
        currency="ISK",
        price_isk=price_int,
        estimated_landed_isk=price_int,
        gpu=gpu,
        cpu=specs["cpu"],
        cpu_brand=specs["cpu_brand"],
        ram_gb=specs["ram_gb"],
        storage_gb=specs["storage_gb"],
        storage_label=specs["storage_label"],
        brand=specs["brand"],
        original_price=float(orig_int) if orig_int else None,
        original_price_isk=orig_int,
        discount_pct=discount_pct,
        on_sale=bool(orig_int and discount_pct >= 1.0),
        in_stock=in_stock,
    )


def scrape_tolvutek(fx_rates: dict[str, float]) -> tuple[list[Product], StoreResult]:
    """Tölvutek (tolvutek.is) - Odoo eCommerce."""
    store = "Tölvutek"
    t0 = time.monotonic()
    products: dict[str, Product] = {}
    try:
        for term in ("leikjaturn", "rtx 5070 ti", "rtx 5080", "rtx 5060 ti"):
            url = f"https://tolvutek.is/shop?search={term.replace(' ', '+')}"
            resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")

            for card in soup.select(".oe_product_cart, .o_wsale_product_grid_wrapper, form[action*='/shop/cart']"):
                links = [a for a in card.select("a[href*='/shop/']") if "/shop/cart" not in a.get("href", "")]
                if not links:
                    continue
                href = links[0].get("href", "")
                full_url = urljoin("https://tolvutek.is", href)

                title_el = card.select_one("h6 a, .o_wsale_products_item_title a, [itemprop='name']")
                title = title_el.get_text(" ", strip=True) if title_el else ""
                if not title:
                    for a in links:
                        if a.get_text(strip=True):
                            title = a.get_text(" ", strip=True)
                            break
                if not title:
                    img_el = card.select_one("img[alt]")
                    title = img_el.get("alt", "").strip() if img_el else ""
                if not title:
                    continue

                price_el = card.select_one(".oe_currency_value, [itemprop='price'], .product_price span")
                price_val = parse_price(price_el.get_text(" ", strip=True) if price_el else "", "ISK")
                if not price_val or price_val < 50000:
                    continue

                old_el = card.select_one("del .oe_currency_value, .text-danger del")
                old_val = parse_price(old_el.get_text(" ", strip=True), "ISK") if old_el else None

                img_el = card.select_one("img")
                img_url = urljoin("https://tolvutek.is", img_el.get("src", "")) if img_el and img_el.get("src") else ""

                prod = _build_iceland_product(
                    store=store,
                    title=title,
                    url=full_url,
                    price_isk=price_val,
                    image_url=img_url,
                    original_price_isk=old_val,
                    fx_rates=fx_rates,
                )
                if prod:
                    products[prod.id] = prod
            time.sleep(0.5)

        return list(products.values()), StoreResult(
            store=store, region="Iceland", ships_to_iceland="Local",
            status="ok", count=len(products), duration_ms=int((time.monotonic() - t0) * 1000)
        )
    except Exception as exc:
        return list(products.values()), StoreResult(
            store=store, region="Iceland", ships_to_iceland="Local",
            status="error", count=len(products), error=str(exc),
            duration_ms=int((time.monotonic() - t0) * 1000),
        )


def scrape_tolvutaekni(fx_rates: dict[str, float]) -> tuple[list[Product], StoreResult]:
    """Tölvutækni (tolvutaekni.is) - Shopify collections + predictive search."""
    store = "Tölvutækni"
    t0 = time.monotonic()
    products: dict[str, Product] = {}
    try:
        # 1. Collection JSON (gets all desktop gaming PCs reliably)
        for handle in ("bordtolvur", "leikjatolvur"):
            col_url = f"https://tolvutaekni.is/collections/{handle}/products.json?limit=250"
            r = requests.get(col_url, headers=DEFAULT_HEADERS, timeout=15)
            if r.status_code != 200:
                continue
            for item in r.json().get("products", []):
                title = item.get("title", "")
                slug = item.get("handle", "")
                p_url = f"https://tolvutaekni.is/products/{slug}" if slug else "https://tolvutaekni.is"
                variants = item.get("variants") or []
                v0 = variants[0] if variants else {}
                price_val = parse_price(str(v0.get("price", "")), "ISK")
                if not price_val or price_val < 50000:
                    continue
                compare_val = parse_price(str(v0.get("compare_at_price") or ""), "ISK")
                images = item.get("images") or []
                img_url = images[0].get("src", "") if images else ""
                body_text = BeautifulSoup(item.get("body_html") or "", "lxml").get_text(" ", strip=True)
                in_stock = any(bool(v.get("available", True)) for v in variants) if variants else True

                prod = _build_iceland_product(
                    store=store,
                    title=title,
                    url=p_url,
                    price_isk=price_val,
                    image_url=img_url,
                    original_price_isk=compare_val,
                    description=body_text,
                    in_stock=in_stock,
                    fx_rates=fx_rates,
                )
                if prod:
                    products[prod.id] = prod
            time.sleep(0.5)

        return list(products.values()), StoreResult(
            store=store, region="Iceland", ships_to_iceland="Local",
            status="ok", count=len(products), duration_ms=int((time.monotonic() - t0) * 1000)
        )
    except Exception as exc:
        return list(products.values()), StoreResult(
            store=store, region="Iceland", ships_to_iceland="Local",
            status="error", count=len(products), error=str(exc),
            duration_ms=int((time.monotonic() - t0) * 1000),
        )


def scrape_computer_is(fx_rates: dict[str, float]) -> tuple[list[Product], StoreResult]:
    """Computer.is (computer.is) - Category & search HTML scraper."""
    store = "Computer.is"
    t0 = time.monotonic()
    products: dict[str, Product] = {}
    urls = [
        "https://computer.is/is/products/leikjatolvur",
        "https://computer.is/is/products/bordtolvur",
    ] + [f"https://computer.is/is/search?q={t}" for t in SEARCH_TERMS]

    try:
        for u in urls:
            resp = requests.get(u, headers=DEFAULT_HEADERS, timeout=15)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "lxml")
            for card in soup.select(".product-card, .product-item, .product, article, [class*='ProductCard']"):
                link_el = card.select_one("a[href*='/is/product']") or card.select_one("a[href]")
                if not link_el:
                    continue
                full_url = urljoin("https://computer.is", link_el.get("href", ""))
                title_el = card.select_one("h2, h3, h4, .product-title, .title") or link_el
                title = title_el.get_text(" ", strip=True)
                price_el = card.select_one(".price, [class*='price']")
                price_val = parse_price(price_el.get_text(" ", strip=True) if price_el else card.get_text(" "), "ISK")
                if not price_val or price_val < 50000:
                    continue
                img_el = card.select_one("img")
                img_url = urljoin("https://computer.is", img_el.get("src", "")) if img_el and img_el.get("src") else ""
                prod = _build_iceland_product(
                    store=store,
                    title=title,
                    url=full_url,
                    price_isk=price_val,
                    image_url=img_url,
                    fx_rates=fx_rates,
                )
                if prod:
                    products[prod.id] = prod
            time.sleep(0.5)

        return list(products.values()), StoreResult(
            store=store, region="Iceland", ships_to_iceland="Local",
            status="ok", count=len(products), duration_ms=int((time.monotonic() - t0) * 1000)
        )
    except Exception as exc:
        return list(products.values()), StoreResult(
            store=store, region="Iceland", ships_to_iceland="Local",
            status="error", count=len(products), error=str(exc),
            duration_ms=int((time.monotonic() - t0) * 1000),
        )


def scrape_elko(fx_rates: dict[str, float]) -> tuple[list[Product], StoreResult]:
    """Elko (elko.is) - Next.js / Algolia prod_elko_products."""
    store = "Elko"
    t0 = time.monotonic()
    products: dict[str, Product] = {}
    try:
        resp = requests.get("https://elko.is/leit?q=5070", headers=DEFAULT_HEADERS, timeout=15)
        resp.raise_for_status()
        html = resp.text

        app_id_m = re.search(r'"algoliaApplicationId":"([^"]+)"', html)
        api_key_m = re.search(r'"algoliaApiKey":"([^"]+)"', html)
        prefix_m = re.search(r'"algoliaEnvPrefix":"([^"]+)"', html)

        app_id = app_id_m.group(1) if app_id_m else "9LGLXP4YCH"
        api_key = api_key_m.group(1) if api_key_m else "dfdb7b6d367c3580a1465cc307b31cfd"
        index_name = f"{prefix_m.group(1)}_products" if prefix_m else "prod_elko_products"

        alg_url = f"https://{app_id}-dsn.algolia.net/1/indexes/*/queries"
        alg_headers = {
            "X-Algolia-Application-Id": app_id,
            "X-Algolia-API-Key": api_key,
            "Content-Type": "application/json",
        }
        for term in ("5060", "5070", "5080", "leikjaturn"):
            payload = {"requests": [{"indexName": index_name, "params": f"query={term}&hitsPerPage=40"}]}
            r = requests.post(alg_url, headers=alg_headers, json=payload, timeout=10)
            if r.status_code != 200:
                continue
            for res in r.json().get("results", []):
                for hit in res.get("hits", []):
                    p_obj = hit.get("product") or {}
                    title = hit.get("name") or p_obj.get("name") or ""
                    slug = p_obj.get("slug") or hit.get("slug") or ""
                    p_url = f"https://elko.is/vorur/{slug}" if slug else "https://elko.is"

                    price_obj = (hit.get("listings") or {}).get("webshop", {}).get("price", {})
                    reg_price = price_obj.get("price")
                    disc_price = price_obj.get("discountedPrice")
                    active_price = disc_price if disc_price else reg_price
                    if not active_price:
                        continue

                    img_obj = hit.get("firstImage") or {}
                    img_url = img_obj.get("url", "") if isinstance(img_obj, dict) else ""

                    prod = _build_iceland_product(
                        store=store,
                        title=title,
                        url=p_url,
                        price_isk=float(active_price),
                        image_url=img_url,
                        original_price_isk=float(reg_price) if disc_price and reg_price and float(reg_price) > float(disc_price) else None,
                        description=str(p_obj.get("shortDescription", "")),
                        in_stock=bool(hit.get("inStock", True)),
                        fx_rates=fx_rates,
                    )
                    if prod:
                        products[prod.id] = prod

        return list(products.values()), StoreResult(
            store=store, region="Iceland", ships_to_iceland="Local",
            status="ok", count=len(products), duration_ms=int((time.monotonic() - t0) * 1000)
        )
    except Exception as exc:
        return list(products.values()), StoreResult(
            store=store, region="Iceland", ships_to_iceland="Local",
            status="error", count=len(products), error=str(exc),
            duration_ms=int((time.monotonic() - t0) * 1000),
        )


def scrape_tl(fx_rates: dict[str, float]) -> tuple[list[Product], StoreResult]:
    """Tölvulistinn (tl.is) - Next.js / Magento."""
    store = "Tölvulistinn"
    t0 = time.monotonic()
    products: dict[str, Product] = {}
    try:
        for term in SEARCH_TERMS:
            resp = requests.get(f"https://tl.is/leit?q={term}", headers=DEFAULT_HEADERS, timeout=15)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "lxml")
            next_data = soup.find("script", id="__NEXT_DATA__")
            if next_data and next_data.string:
                raw_text = next_data.string
                # Walk JSON for product objects if present
                try:
                    data = json.loads(raw_text)
                    _walk_json_products(data, store, "https://tl.is", products, fx_rates)
                except Exception:
                    pass
            time.sleep(0.5)

        return list(products.values()), StoreResult(
            store=store, region="Iceland", ships_to_iceland="Local",
            status="ok", count=len(products), duration_ms=int((time.monotonic() - t0) * 1000)
        )
    except Exception as exc:
        return list(products.values()), StoreResult(
            store=store, region="Iceland", ships_to_iceland="Local",
            status="error", count=len(products), error=str(exc),
            duration_ms=int((time.monotonic() - t0) * 1000),
        )


def scrape_kisildalur(fx_rates: dict[str, float]) -> tuple[list[Product], StoreResult]:
    """Kísildalur (kd.is) - SPA / HTML scraper."""
    store = "Kísildalur"
    t0 = time.monotonic()
    products: dict[str, Product] = {}
    try:
        for url in [
            "https://kd.is/vorur/tolvur/bordtolvur/leikjatolvur",
            "https://kd.is/vorur/tolvur/bordtolvur",
        ]:
            html = fetch_rendered_html(url)
            if not html:
                resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)
                if resp.status_code != 200:
                    continue
                html = resp.text
            soup = BeautifulSoup(html, "lxml")
            for card in soup.select(".product, .product-card, article"):
                link_el = card.select_one("a[href]")
                if not link_el:
                    continue
                full_url = urljoin("https://kd.is", link_el.get("href", ""))
                title = card.get_text(" ", strip=True)
                price_val = parse_price(title, "ISK")
                if not price_val or price_val < 50000:
                    continue
                prod = _build_iceland_product(
                    store=store, title=title[:140], url=full_url,
                    price_isk=price_val, fx_rates=fx_rates,
                )
                if prod:
                    products[prod.id] = prod

        return list(products.values()), StoreResult(
            store=store, region="Iceland", ships_to_iceland="Local",
            status="ok", count=len(products), duration_ms=int((time.monotonic() - t0) * 1000)
        )
    except Exception as exc:
        return list(products.values()), StoreResult(
            store=store, region="Iceland", ships_to_iceland="Local",
            status="error", count=len(products), error=str(exc),
            duration_ms=int((time.monotonic() - t0) * 1000),
        )


def _walk_json_products(
    obj: object,
    store: str,
    base_url: str,
    out: dict[str, Product],
    fx_rates: dict[str, float],
) -> None:
    if isinstance(obj, dict):
        name = obj.get("name") or obj.get("title")
        price = obj.get("price") or obj.get("final_price")
        if isinstance(name, str) and isinstance(price, (int, float)) and price > 50000:
            slug = obj.get("url_key") or obj.get("slug") or obj.get("url") or ""
            full_url = urljoin(base_url, str(slug))
            prod = _build_iceland_product(
                store=store,
                title=name,
                url=full_url,
                price_isk=float(price),
                image_url=str(obj.get("image", "")),
                fx_rates=fx_rates,
            )
            if prod:
                out[prod.id] = prod
        for v in obj.values():
            _walk_json_products(v, store, base_url, out, fx_rates)
    elif isinstance(obj, list):
        for item in obj:
            _walk_json_products(item, store, base_url, out, fx_rates)


def scrape_all_iceland(fx_rates: dict[str, float]) -> tuple[list[Product], list[StoreResult]]:
    all_products: list[Product] = []
    results: list[StoreResult] = []
    for fn in (
        scrape_tolvutek,
        scrape_tolvutaekni,
        scrape_computer_is,
        scrape_elko,
        scrape_tl,
        scrape_kisildalur,
    ):
        prods, res = fn(fx_rates)
        all_products.extend(prods)
        results.append(res)
    return all_products, results
