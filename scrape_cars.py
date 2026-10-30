"""Daily price check for auto24.ee listings.

Reads cars.json, visits each listing, and appends the price to car_history.json
whenever it changes. Run by GitHub Actions (see .github/workflows/scrape.yml)
or by hand:  python scrape_cars.py
"""
import json
import os
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

CONFIG_FILE = "cars.json"
HISTORY_FILE = "car_history.json"
DEBUG_DIR = Path("debug")

EXTRACT_JS = """
() => {
  const txt = (sel) => document.querySelector(sel)?.textContent.trim() || "";
  const h1 = document.querySelector("h1.commonSubtitle");
  const meta = (p) => document.querySelector(`meta[property="${p}"]`)?.content || "";
  return {
    has_h1: !!h1,
    title: h1 ? (h1.childNodes[0]?.textContent || "").trim() : "",
    price_text: txt("tr.field-hind span.value"),
    og_description: meta("og:description"),
    img: meta("og:image"),
    year_text: txt("tr.field-month_and_year span.value"),
    mileage_text: txt("tr.field-labisoit span.value"),
    fuel: txt("tr.field-kytus span.value"),
    gearbox: txt("tr.field-kaigukast_kaikudega span.value"),
    location: txt(".other-info .-location b"),
    saved_count: document.querySelector(".bookmark")?.dataset.bookmarkCount || "",
  };
}
"""


def digits(text):
    d = re.sub(r"\D", "", text or "")
    return int(d) if d else None


def parse_price(info):
    price = digits(info.get("price_text"))
    if price:
        return price
    # Backup: og:description looks like "2016, bensiin, 136 900 km, 15 900 EUR - ..."
    m = re.search(r"([\d\s\u00a0]+)\s*EUR", info.get("og_description", ""))
    return digits(m.group(1)) if m else None


def listing_id(url):
    m = re.search(r"/soidukid/(\d+)", url) or re.search(r"[?&]id=(\d+)", url)
    return m.group(1) if m else None


def save_debug(page, name):
    DEBUG_DIR.mkdir(exist_ok=True)
    try:
        page.screenshot(path=str(DEBUG_DIR / f"{name}.png"), full_page=True)
        (DEBUG_DIR / f"{name}.html").write_text(page.content(), encoding="utf-8")
    except Exception as e:  # debug output must never crash the run
        print(f"  (could not save debug files: {e})")


def check_car(page, url, car):
    """Update the `car` record in place. Returns a short status string."""
    resp = page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)
    status_code = resp.status if resp else 0
    html = page.content()

    blocked = (
        status_code in (403, 429)
        or "px-captcha" in html
        or "Press & Hold" in html
    )
    info = page.evaluate(EXTRACT_JS)

    if blocked or not info["has_h1"]:
        # Either bot protection or a listing that no longer exists. We can't
        # tell which, so keep the old data and record the problem.
        save_debug(page, f"{car['id']}")
        car["error_count"] = car.get("error_count", 0) + 1
        car["last_error"] = f"HTTP {status_code}, blocked={blocked}, page has no listing title"
        if car["error_count"] >= 5:
            car["status"] = "unavailable"
        return "ERROR (blocked or removed) - debug files saved"

    price = parse_price(info)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    car.update(
        {
            "title": info["title"] or car.get("title", ""),
            "img": info["img"] or car.get("img", ""),
            "year": (info["year_text"].split("/")[-1] if info["year_text"] else car.get("year", "")),
            "mileage_km": digits(info["mileage_text"]) or car.get("mileage_km"),
            "fuel": info["fuel"] or car.get("fuel", ""),
            "gearbox": info["gearbox"] or car.get("gearbox", ""),
            "location": info["location"] or car.get("location", ""),
            "saved_count": digits(info["saved_count"]),
            "last_seen": now,
            "error_count": 0,
            "last_error": "",
        }
    )

    if price is None:
        save_debug(page, f"{car['id']}-noprice")
        car["status"] = "no_price"
        return "listing loaded but no price found - debug files saved"

    car["status"] = "active"
    entries = car.setdefault("entries", [])
    old = entries[-1]["p"] if entries else None
    if old != price:
        entries.append({"t": now, "p": price})
    car["latest_price"] = price
    return f"{price} EUR" + (f" (was {old})" if old and old != price else "")


def main():
    config = json.loads(Path(CONFIG_FILE).read_text(encoding="utf-8"))
    history = {"meta": {}, "cars": {}}
    if Path(HISTORY_FILE).exists():
        try:
            history = json.loads(Path(HISTORY_FILE).read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print("Warning: history file was unreadable, starting fresh")
    history.setdefault("cars", {})

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            viewport={"width": 1366, "height": 850},
            locale="et-EE",
            timezone_id="Europe/Tallinn",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        for item in config["cars"]:
            url = item["url"]
            cid = listing_id(url)
            if not cid:
                print(f"Skipping, can't find a listing ID in: {url}")
                continue
            car = history["cars"].setdefault(cid, {"id": cid, "entries": []})
            car["url"] = f"https://www.auto24.ee/soidukid/{cid}"
            car["note"] = item.get("note", "")
            print(f"[{cid}] {car.get('title') or url}")
            try:
                print("   ->", check_car(page, url, car))
            except Exception as e:
                car["error_count"] = car.get("error_count", 0) + 1
                car["last_error"] = str(e)[:200]
                save_debug(page, f"{cid}-exception")
                print("   -> ERROR:", e)
            time.sleep(random.uniform(4, 9))  # be polite

        browser.close()

    history["meta"]["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    Path(HISTORY_FILE).write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Done.")


if __name__ == "__main__":
    main()
