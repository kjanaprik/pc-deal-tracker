from __future__ import annotations

import hashlib
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import requests

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,is;q=0.8",
}

# Fallback rates (ISK per 1 unit of foreign currency) if live FX API is unreachable
FALLBACK_ISK_PER_UNIT = {
    "ISK": 1.0,
    "USD": 138.0,
    "EUR": 149.0,
    "GBP": 176.0,
    "CAD": 99.0,
}

# Estimated international shipping for a ~15-18kg desktop PC + customs clearance fee (ISK)
EST_SHIPPING_ISK = {
    "Iceland": 0,
    "Europe": 18000,       # ~120 EUR DHL/courier freight for heavy PC
    "USA/Canada": 32000,   # ~230 USD air freight / forwarder for heavy PC
}
CLEARANCE_FEE_ISK = 2500


@dataclass
class Product:
    id: str
    title: str
    store: str
    region: str                # "Iceland", "Europe", "USA/Canada"
    ships_to_iceland: str      # "Local", "Direct", "Forwarder Required", "Quote Required"
    url: str
    image_url: str
    price_original: float
    currency: str
    price_isk: int
    estimated_landed_isk: int
    gpu: str                   # "RTX 5060 Ti 16GB" | "RTX 5070 Ti 16GB" | "RTX 5080 16GB"
    cpu: str = "Unknown"
    cpu_brand: str = "Other"   # "AMD" | "Intel" | "Other"
    ram_gb: Optional[int] = None
    storage_gb: Optional[int] = None
    storage_label: str = "Unknown"
    brand: str = "Custom / Prebuilt"
    original_price: Optional[float] = None
    original_price_isk: Optional[int] = None
    discount_pct: float = 0.0
    on_sale: bool = False
    in_stock: bool = True
    notes: str = ""
    last_seen: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StoreResult:
    store: str
    region: str
    ships_to_iceland: str
    status: str                # "ok" | "blocked" | "error" | "skipped"
    count: int = 0
    error: str = ""
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def make_product_id(store: str, url: str) -> str:
    clean_url = url.split("?")[0].rstrip("/").lower()
    raw = f"{store.lower()}::{clean_url}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def fetch_rendered_html(url: str, wait_ms: int = 2500) -> Optional[str]:
    """
    Fetch JS-rendered HTML using Cloudflare Browser Rendering REST API
    when CF_ACCOUNT_ID and CF_API_TOKEN are set.
    """
    cf_account = os.getenv("CF_ACCOUNT_ID", "").strip()
    cf_token = os.getenv("CF_API_TOKEN", "").strip()
    if not (cf_account and cf_token):
        return None
    try:
        endpoint = f"https://api.cloudflare.com/client/v4/accounts/{cf_account}/browser-rendering/content"
        resp = requests.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {cf_token}",
                "Content-Type": "application/json",
            },
            json={
                "url": url,
                "gotoOptions": {"waitUntil": "networkidle2", "timeout": 25000},
                "waitForTimeout": wait_ms,
            },
            timeout=35,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("result") or None
    except Exception:
        pass
    return None


# Íslandsbanki Mastercard foreign currency markup (2.60% over wholesale/mid rate)
ISLANDSBANKI_MC_MARKUP = 1.026


def fetch_fx_rates(apply_iceland_card_markup: bool = True) -> dict[str, float]:
    """
    Return ISK per 1 unit of currency (e.g. {'USD': 138.5, 'EUR': 149.2, ...}).
    When apply_iceland_card_markup is True, applies Íslandsbanki's 2.60% Mastercard markup.
    """
    mult = ISLANDSBANKI_MC_MARKUP if apply_iceland_card_markup else 1.0
    try:
        resp = requests.get("https://open.er-api.com/v6/latest/ISK", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        rates = data.get("rates", {})
        result = {"ISK": 1.0}
        for cur in ("USD", "EUR", "GBP", "CAD"):
            val = rates.get(cur)
            if val and val > 0:
                result[cur] = round((1.0 / float(val)) * mult, 2)
            else:
                result[cur] = round(FALLBACK_ISK_PER_UNIT[cur] * mult, 2)
        return result
    except Exception:
        return {k: (1.0 if k == "ISK" else round(v * mult, 2)) for k, v in FALLBACK_ISK_PER_UNIT.items()}


def compute_landed_isk(
    price_original: float,
    currency: str,
    region: str,
    fx_rates: dict[str, float],
    local_vat_deducted: float = 0.0,
) -> tuple[int, int]:
    """Return (sticker_price_isk, estimated_landed_isk_with_iceland_vat)."""
    rate = fx_rates.get(currency, FALLBACK_ISK_PER_UNIT.get(currency, 140.0))
    sticker_isk = int(round(price_original * rate))
    if region == "Iceland":
        return sticker_isk, sticker_isk

    ex_vat_isk = sticker_isk / (1.0 + local_vat_deducted) if local_vat_deducted > 0 else sticker_isk
    shipping_isk = EST_SHIPPING_ISK.get(region, 25000)
    # Icelandic customs charges 24% VAT on (goods + shipping) + clearance fee
    landed = int(round((ex_vat_isk + shipping_isk) * 1.24 + CLEARANCE_FEE_ISK))
    return sticker_isk, landed


def parse_price(text: str, currency_hint: str = "ISK") -> Optional[float]:
    """Parse localized price strings like '399.990 kr.', '1.899,00 €', '$1,999.99'."""
    if not text:
        return None
    cleaned = re.sub(r"[^\d.,]", "", text.strip())
    if not cleaned:
        return None

    if currency_hint == "ISK":
        # Icelandic prices have no decimals; dots/commas are thousands separators
        digits = re.sub(r"[.,]", "", cleaned)
        return float(digits) if digits else None

    # EU/US format detection
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            # 1.899,00 -> 1899.00
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            # 1,899.00 -> 1899.00
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        parts = cleaned.split(",")
        if len(parts[-1]) == 2:
            cleaned = cleaned.replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "." in cleaned:
        parts = cleaned.split(".")
        if len(parts[-1]) == 3 and len(parts) > 1:
            cleaned = cleaned.replace(".", "")

    try:
        return float(cleaned)
    except ValueError:
        return None


def detect_target_gpu(text: str) -> Optional[str]:
    """Match RTX 5060 Ti 16GB, RTX 5070 Ti 16GB, or RTX 5080 16GB."""
    t_norm = re.sub(r"[™®]", "", text.lower())
    t_norm = re.sub(r"[\s\-_,]+", " ", t_norm)

    if re.search(r"(?:rtx|geforce)\s*5080\b", t_norm):
        return "RTX 5080 16GB"

    if re.search(r"(?:rtx|geforce)\s*5070\s*ti\b", t_norm):
        return "RTX 5070 Ti 16GB"

    if re.search(r"(?:rtx|geforce)\s*5070\b", t_norm):
        return "RTX 5070 12GB"

    if re.search(r"(?:rtx|geforce)\s*5060\s*ti\b", t_norm):
        # Reject 8GB 5060 Ti variants (don't let '16 GB DDR4/DDR5' fool this check)
        if re.search(r"5060\s*ti\s*8\s*gb\b", t_norm) or re.search(r"8\s*gb\s*gddr", t_norm):
            return None
        if re.search(r"5060\s*ti\s*16\s*gb\b|5060\s*ti\s*16g\b|16\s*gb\s*gddr", t_norm):
            return "RTX 5060 Ti 16GB"
        # If neither 8GB nor 16GB VRAM is specified, exclude if 8GB appears anywhere near GPU
        if re.search(r"\b8\s*gb\b", t_norm):
            return None
        return "RTX 5060 Ti 16GB"

    return None


NON_DESKTOP_KEYWORDS = (
    "fartölva", "leikjafartölva", "leikjafartolva", "laptop", "notebook", "ultrabook",
    "skjákort", "skjakort", "graphics card", "video card", "gpu only", "waterblock",
    "water block", "skjár", "monitor", "aflgjafi", "power supply",
    "móðurborð", "motherboard", "vinnsluminni", "kæling", "cooler",
    "rog strix g16", "rog strix g18", "rog zephyrus", "legion pro 5",
    "legion pro 7", "msi katana", "msi vector", "msi raider", "msi stealth",
    "razer blade", "alienware m16", "alienware m18", "omen 16", "omen 17",
    "tuf gaming a16", "tuf gaming f16", "predator helios", "nitro 16",
)


def is_desktop_pc(title: str, extra_text: str = "") -> bool:
    """Return True if the listing is a desktop gaming PC rather than a laptop or standalone GPU."""
    title_lower = title.lower()
    for bad in NON_DESKTOP_KEYWORDS:
        if bad in title_lower:
            return False

    combined = f"{title} {extra_text}".lower()
    # Standalone GPU titles usually start with brand + GeForce RTX 50xx without any CPU/RAM/SSD
    has_cpu = bool(re.search(r"(ryzen|core\s*ultra|i[579][-\s]\d|intel|amd|r[579][-\s]\d{4})", combined))
    has_ram_or_ssd = bool(re.search(r"(\b(?:16|32|64|128)\s*gb\s*(?:ddr|ram|vinnslu)|\b[124]\s*tb\s*(?:ssd|nvme|m\.2)|\bpc\b|\bleikjatölva\b|\bleikjaturn\b|\bborðtölva\b|\bdesktop\b|\btower\b)", combined))
    return has_cpu or has_ram_or_ssd


def extract_specs(title: str, description: str = "", store: str = "") -> dict[str, Any]:
    """Extract CPU, RAM, Storage, and Brand from product title + description."""
    text = re.sub(r"[™®]", "", f"{title} {description}")
    t_lower = text.lower()

    # CPU extraction
    cpu = "Unknown"
    cpu_brand = "Other"
    cpu_patterns = [
        r"(Ryzen\s*Threadripper(?:\s*PRO)?\s*\d{4}W?X)",
        r"(Ryzen\s*[579]\s*\d{4}X3D)",
        r"(Ryzen\s*[579]\s*\d{4}[XF]{0,2})",
        r"(Ryzen\s*\d{4}X3D)",
        r"(Ryzen\s*\d{4}[XF]{0,2})",
        r"(R[579][-\s]\d{4}X3D)",
        r"(R[579][-\s]\d{4}[XF]?)(?!\s*MHz)",
        r"(Core\s*Ultra\s*[579]\s*(?:Processor\s*)?\d{3}[A-Z]{0,2})",
        r"(Core\s*i[579][-\s]*(?:Processor\s*)?\d{5}[A-Z]{0,2})",
        r"(i[579][-\s]\d{5}[A-Z]{0,2})",
        r"\b(U[579])(?:/|\s+\d)",
    ]
    for pat in cpu_patterns:
        m = re.search(pat, text, re.I)
        if m:
            raw_cpu = re.sub(r"\bProcessor\b", "", m.group(1), flags=re.I)
            cpu = re.sub(r"[\s\-]+", " ", raw_cpu).strip()
            if cpu.upper() in ("U5", "U7", "U9"):
                cpu = f"Core Ultra {cpu[1]}"
            elif re.match(r"^R([579])\s+(\d{4}.*)$", cpu, re.I):
                rm = re.match(r"^R([579])\s+(\d{4}.*)$", cpu, re.I)
                cpu = f"Ryzen {rm.group(1)} {rm.group(2).upper()}"
            elif re.match(r"^Ryzen\s+7500X3D$", cpu, re.I):
                cpu = "Ryzen 5 7500X3D"
            elif re.match(r"^Ryzen\s+(7800X3D|9800X3D|9850X3D)$", cpu, re.I):
                cpu = f"Ryzen 7 {cpu.split()[-1].upper()}"
            elif re.match(r"^i([579])\s+(\d{5}.*)$", cpu, re.I):
                im = re.match(r"^i([579])\s+(\d{5}.*)$", cpu, re.I)
                cpu = f"Core i{im.group(1)} {im.group(2).upper()}"
            break

    if "ryzen" in t_lower or "threadripper" in t_lower or cpu.lower().startswith("r"):
        cpu_brand = "AMD"
    elif "intel" in t_lower or "core" in t_lower or cpu.lower().startswith("i"):
        cpu_brand = "Intel"

    # RAM extraction (avoid matching 16GB VRAM by looking for DDR4/DDR5/RAM or RAM: label)
    ram_gb: Optional[int] = None
    ram_match = re.search(r"RAM\s*:\s*(16|24|32|48|64|96|128)\s*GB", text, re.I)
    if not ram_match:
        ram_match = re.search(r"\b(16|24|32|48|64|96|128)\s*GB\s*(?:(?:\(\d+GBx\d+\)\s*)?DDR[45]|RAM|vinnsluminni)", text, re.I)
    if not ram_match:
        ram_match = re.search(r"\b(32|48|64|96|128)\s*GB\b(?!\s*(?:GDDR|VRAM|RTX))", text, re.I)
    if not ram_match:
        # Elko shorthand e.g. U7/16/1TB or R7/32/2TB
        ram_match = re.search(r"/(16|24|32|48|64)/(?:500|512|1|2|4)T?B", text, re.I)
    if ram_match:
        ram_gb = int(ram_match.group(1))

    # Storage extraction
    storage_gb: Optional[int] = None
    storage_label = "Unknown"
    ssd_tb_match = re.search(r"SSD\s*:\s*([1248])\s*TB", text, re.I) or re.search(r"\b([1248])\s*TB\b", text, re.I)
    if ssd_tb_match:
        tb = int(ssd_tb_match.group(1))
        storage_gb = tb * 1000
        storage_label = f"{tb}TB NVMe" if "nvme" in t_lower or "m.2" in t_lower else f"{tb}TB SSD"
    else:
        gb_match = (
            re.search(r"SSD\s*:\s*(500|512|1000|1024|2000|2048|4000)\s*GB", text, re.I)
            or re.search(r"\b(500|512|1000|1024|2000|2048|4000)\s*GB\s*(?:SSD|NVMe|M\.2)", text, re.I)
        )
        if gb_match:
            val = int(gb_match.group(1))
            storage_gb = val
            storage_label = f"{val // 1000}TB NVMe" if val >= 1000 and val % 1000 == 0 else f"{val}GB SSD"

    # Brand extraction
    brand = "Custom / Prebuilt"
    for b in (
        "Lenovo", "ASUS", "ROG", "MSI", "HP", "OMEN", "Acer", "Predator",
        "Alienware", "Corsair", "NZXT", "iBUYPOWER", "CyberPowerPC",
        "Skytech", "ABS", "XOTIC PC", "Xotic PC", "Memory PC", "Caseking", "PCSpecialist",
        "Overclockers", "OcUK", "ORIGIN PC", "Kísildalur", "Tölvutek", "Tölvutækni", "Computer.is",
    ):
        if b.lower() in t_lower:
            if b in ("Overclockers", "OcUK"):
                brand = "Overclockers"
            elif b.lower() == "xotic pc":
                brand = "XOTIC PC"
            elif b.upper() == "MSI":
                brand = "MSI"
            else:
                brand = b
            break
    if brand == "Custom / Prebuilt" and store:
        if store in ("Memory PC", "Overclockers UK", "Caseking", "PCSpecialist", "CSL Computer", "XOTIC PC", "CyberPowerPC", "Tölvutækni"):
            brand = "Overclockers" if store == "Overclockers UK" else store

    return {
        "cpu": cpu,
        "cpu_brand": cpu_brand,
        "ram_gb": ram_gb,
        "storage_gb": storage_gb,
        "storage_label": storage_label,
        "brand": brand,
    }
