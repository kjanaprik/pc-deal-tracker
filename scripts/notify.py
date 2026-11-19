#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DEALS_PATH = ROOT / "data" / "deals.json"
WATCHLIST_PATH = ROOT / "watchlist.json"
NOTIFIED_PATH = ROOT / "data" / "notified.json"


def load_json(path: Path, default: object) -> object:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default


def format_isk(val: int) -> str:
    return f"{val:,}".replace(",", ".") + " ISK"


def find_alerts(deals: dict, watchlist: dict, notified: dict) -> list[dict]:
    watched_ids = set(watchlist.get("watched_ids", []))
    rules = watchlist.get("rules", [])
    notify_on_sale = bool(watchlist.get("notify_on_any_watched_sale", True))
    notify_on_any_drop = bool(watchlist.get("notify_on_any_price_drop", True))
    global_min_drop_pct = float(watchlist.get("global_min_drop_pct", 5.0))
    global_min_drop_isk = int(watchlist.get("global_min_drop_isk", 15000))
    min_drop_pct = float(watchlist.get("min_price_drop_pct", 3.0))

    alerts: list[dict] = []

    for p in deals.get("products", []):
        pid = p["id"]
        reasons: list[str] = []

        # 1. Direct watched product check
        if pid in watched_ids:
            if p.get("price_drop_pct", 0.0) >= min_drop_pct:
                reasons.append(f"Watched PC dropped {p['price_drop_pct']}% (-{format_isk(p['price_drop_isk'])})")
            elif notify_on_sale and p.get("on_sale"):
                reasons.append(f"Watched PC is on sale ({p['discount_pct']}% off)")

        # 2. Global price cut check (any tracked PC dropping >= 5% or >= 15,000 ISK)
        if notify_on_any_drop and not reasons:
            drop_pct = float(p.get("price_drop_pct", 0.0))
            drop_isk = int(p.get("price_drop_isk", 0))
            if drop_pct >= global_min_drop_pct or drop_isk >= global_min_drop_isk:
                reasons.append(f"Price cut detected: -{drop_pct}% (-{format_isk(drop_isk)})")

        # 3. Spec / price threshold rules
        for rule in rules:
            if rule.get("gpu") and p.get("gpu") != rule["gpu"]:
                continue
            if rule.get("max_landed_isk") and p.get("estimated_landed_isk", 10**9) > rule["max_landed_isk"]:
                continue
            if rule.get("only_on_sale") and not p.get("on_sale"):
                continue
            if rule.get("region") and p.get("region") != rule["region"]:
                continue
            reasons.append(f"Matches rule: {rule.get('name', 'Price Alert')}")

        if not reasons:
            continue

        # Deduplicate: only notify if we haven't notified for this (id, price_isk) before
        last_notified_price = notified.get(pid)
        if last_notified_price is not None and last_notified_price <= p["price_isk"]:
            continue

        alerts.append({"product": p, "reasons": reasons})
        notified[pid] = p["price_isk"]

    return alerts


def build_email_html(alerts: list[dict]) -> str:
    rows = []
    for a in alerts:
        p = a["product"]
        reason_str = "<br>".join(a["reasons"])
        rows.append(
            f"""
            <tr>
              <td style="padding:12px;border-bottom:1px solid #2a2f3a;">
                <strong><a href="{p['url']}" style="color:#60a5fa;text-decoration:none;">{p['title']}</a></strong><br>
                <span style="color:#9ca3af;font-size:12px;">{p['store']} ({p['region']}) • {p['gpu']} • {p['cpu']} • {p.get('ram_gb') or '?'}GB RAM • {p['storage_label']}</span>
              </td>
              <td style="padding:12px;border-bottom:1px solid #2a2f3a;white-space:nowrap;">
                <strong style="color:#34d399;font-size:15px;">{format_isk(p['estimated_landed_isk'])}</strong><br>
                <span style="color:#9ca3af;font-size:11px;">Sticker: {p['price_original']} {p['currency']}</span>
              </td>
              <td style="padding:12px;border-bottom:1px solid #2a2f3a;color:#fbbf24;font-size:12px;">
                {reason_str}
              </td>
            </tr>
            """
        )

    return f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;background:#0f172a;color:#f8fafc;padding:24px;border-radius:12px;">
      <h2 style="margin-top:0;color:#f8fafc;">Gaming PC Deal Alert ({len(alerts)} match{'es' if len(alerts) != 1 else ''})</h2>
      <p style="color:#94a3b8;font-size:14px;">Price drops and deal matches for RTX 5060 Ti 16GB / 5070 Ti 16GB / 5080 16GB desktops:</p>
      <table style="width:100%;border-collapse:collapse;background:#1e293b;border-radius:8px;overflow:hidden;">
        <thead>
          <tr style="background:#334155;text-align:left;font-size:12px;color:#cbd5e1;">
            <th style="padding:10px 12px;">PC &amp; Specs</th>
            <th style="padding:10px 12px;">Est. Landed (ISK)</th>
            <th style="padding:10px 12px;">Alert Reason</th>
          </tr>
        </thead>
        <tbody>
          {''.join(rows)}
        </tbody>
      </table>
    </div>
    """


def send_email(subject: str, html_body: str) -> bool:
    to_email = os.getenv("NOTIFY_EMAIL", "").strip()
    resend_key = os.getenv("RESEND_API_KEY", "").strip()

    if resend_key and to_email:
        from_email = os.getenv("RESEND_FROM", "PC Deal Tracker <onboarding@resend.dev>")
        r = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {resend_key}", "Content-Type": "application/json"},
            json={"from": from_email, "to": [to_email], "subject": subject, "html": html_body},
            timeout=15,
        )
        r.raise_for_status()
        print(f"Sent alert email via Resend to {to_email}")
        return True

    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_port = int((os.getenv("SMTP_PORT") or "587").strip() or "587")
    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_pass = os.getenv("SMTP_PASS", "").strip()

    if smtp_host and smtp_user and smtp_pass and to_email:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = smtp_user
        msg["To"] = to_email
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, [to_email], msg.as_string())
        print(f"Sent alert email via SMTP to {to_email}")
        return True

    print("Email secrets not configured (RESEND_API_KEY or SMTP_* + NOTIFY_EMAIL). Skipping send.")
    return False


def send_ntfy(alerts: list[dict]) -> bool:
    topic = os.getenv("NTFY_TOPIC", "").strip()
    if not topic:
        return False

    url = topic if topic.startswith("http://") or topic.startswith("https://") else f"https://ntfy.sh/{topic.lstrip('/')}"

    if len(alerts) == 1:
        p = alerts[0]["product"]
        ex_vsk = int(round(p["estimated_landed_isk"] / 1.24)) if p.get("region") == "Iceland" else int(round((p["estimated_landed_isk"] - 2500) / 1.24 + 2500))
        title = f"{p['gpu']} Deal @ {p['store']}"
        body = (
            f"{p['title']}\n"
            f"Landed: {format_isk(p['estimated_landed_isk'])} | Ex-VSK: {format_isk(ex_vsk)}\n"
            f"Store: {p['price_original']} {p['currency']}\n"
            f"{' · '.join(alerts[0]['reasons'])}"
        )
        click_url = p["url"]
    else:
        title = f"{len(alerts)} RTX 50-Series PC Deals Found!"
        lines = []
        for a in alerts[:5]:
            p = a["product"]
            ex_vsk = int(round(p["estimated_landed_isk"] / 1.24)) if p.get("region") == "Iceland" else int(round((p["estimated_landed_isk"] - 2500) / 1.24 + 2500))
            lines.append(f"• {p['gpu']} ({p['store']}): {format_isk(ex_vsk)} ex-VSK — {a['reasons'][0]}")
        if len(alerts) > 5:
            lines.append(f"...and {len(alerts) - 5} more deals")
        body = "\n".join(lines)
        click_url = "https://kjanaprik.github.io/pc-deal-tracker/"

    r = requests.post(
        url,
        data=body.encode("utf-8"),
        headers={
            "Title": title.encode("ascii", "ignore").decode("ascii") or "PC Deal Alert",
            "Priority": "high",
            "Tags": "computer,money_with_wings",
            "Click": click_url,
        },
        timeout=15,
    )
    r.raise_for_status()
    print("Sent push notification via ntfy.")
    return True


def main() -> None:
    if os.getenv("TEST_NTFY", "").strip() == "1":
        topic = os.getenv("NTFY_TOPIC", "").strip()
        if topic:
            url = topic if topic.startswith("http") else f"https://ntfy.sh/{topic.lstrip('/')}"
            r = requests.post(
                url,
                data="ntfy push alerts are connected! You will get pinged here whenever a watched RTX 5060 Ti 16GB / 5070 Ti 16GB / 5080 16GB PC drops in price.".encode("utf-8"),
                headers={
                    "Title": "PC Deal Tracker: Alerts Active",
                    "Priority": "default",
                    "Tags": "white_check_mark,computer",
                    "Click": "https://kjanaprik.github.io/pc-deal-tracker/",
                },
                timeout=15,
            )
            r.raise_for_status()
            print("Sent test ntfy push notification.")
        return

    deals = load_json(DEALS_PATH, {})
    watchlist = load_json(WATCHLIST_PATH, {})
    notified = load_json(NOTIFIED_PATH, {})

    alerts = find_alerts(deals, watchlist, notified)
    if not alerts:
        print("No new deal alerts triggered.")
        return

    subject = f"[PC Deal Alert] {len(alerts)} RTX 50-series Gaming PC deal(s) found!"
    html_body = build_email_html(alerts)
    sent_email = send_email(subject, html_body)
    sent_ntfy = send_ntfy(alerts)
    if sent_email or sent_ntfy:
        NOTIFIED_PATH.write_text(json.dumps(notified, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
