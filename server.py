import concurrent.futures
import os
import re
import time
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template, request

BASE_URL = "https://cedarparkpl.librarycalendar.com"
ROOMS_PAGE = f"{BASE_URL}/reserve-room/room"

app = Flask(__name__)

# ---------- HTTP session (connection reuse) ----------
_http = requests.Session()
_http.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml",
})

# ---------- cache ----------
_cache = {}
_cache_lock = threading.Lock()
_cache_locks = {}
ROOMS_TTL = 1800  # 30 minutes — rooms list rarely changes
AVAIL_TTL = 120   # 2 minutes — availability changes more often


def _cache_get(key):
    with _cache_lock:
        entry = _cache.get(key)
        if entry and entry["ts"] > time.time():
            return entry["data"]
        if entry:
            del _cache[key]
    return None


def _cache_set(key, data, ttl=None):
    with _cache_lock:
        _cache[key] = {"data": data, "ts": time.time() + (ttl if ttl else ROOMS_TTL)}


def _cache_del(key):
    with _cache_lock:
        _cache.pop(key, None)


def _cache_lock_for(key):
    with _cache_lock:
        if key not in _cache_locks:
            _cache_locks[key] = threading.Lock()
        return _cache_locks[key]


# ---------- room scraping ----------

def _download_image(image_url: str, slug: str):
    img_dir = Path("static/images")
    img_dir.mkdir(parents=True, exist_ok=True)
    dest = img_dir / f"{slug}.jpg"
    if dest.exists():
        return
    try:
        resp = _http.get(image_url, timeout=10)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
    except Exception:
        pass


def scrape_rooms():
    cached = _cache_get("rooms")
    if cached:
        return cached

    lock = _cache_lock_for("rooms")
    with lock:
        cached = _cache_get("rooms")
        if cached:
            return cached

        resp = _http.get(ROOMS_PAGE, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        rooms = []
        for group in soup.select(".lc-available-rooms__group"):
            type_label_el = group.find_previous(
                "h2", class_="lc-available-rooms__group-label"
            )
            room_type = type_label_el.get_text(strip=True) if type_label_el else "Other"

            for row in group.select(".lc-available-rooms__row"):
                link = row.select_one(".lc_room__room")
                if not link:
                    continue
                href = link.get("href", "")
                url = href.split("?")[0]
                if url.startswith(BASE_URL):
                    url = url[len(BASE_URL):]
                name = link.get_text(strip=True)
                slug = url.rstrip("/").split("/")[-1]

                img_el = row.select_one("img")
                image_url = img_el.get("src", "") if img_el else ""

                rooms.append({
                    "name": name,
                    "url": url,
                    "type": room_type,
                    "slug": slug,
                    "image": image_url,
                })

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            for room in rooms:
                if room["image"]:
                    pool.submit(_download_image, room["image"], room["slug"])

        _cache_set("rooms", rooms)
        return rooms


# ---------- availability scraping ----------

def scrape_availability(room_url: str, target_date: Optional[datetime] = None, refresh: bool = False):
    if target_date is None:
        target_date = datetime.now()

    date_str = target_date.strftime("%Y-%m-%d")
    cache_key = f"avail:{room_url}:{date_str}"

    if not refresh:
        cached = _cache_get(cache_key)
        if cached:
            return cached

    lock = _cache_lock_for(cache_key)
    with lock:
        if not refresh:
            cached = _cache_get(cache_key)
            if cached:
                return cached

        today = datetime.now()
        week_days = {}

        for offset in [0, 3]:
            fetch_date = target_date + timedelta(days=offset)
            fetch_str = fetch_date.strftime("%Y-%m-%d")
            full_url = f"{BASE_URL}{room_url}?selected_date={fetch_str}"
            try:
                resp = _http.get(full_url, timeout=30)
                resp.raise_for_status()
            except Exception:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            day_containers = soup.select(".lc-reservation-openings")

            for container in day_containers:
                heading = container.find("h3")
                if heading:
                    heading_text = heading.get_text(strip=True)
                    m = re.match(r"(\w+)\s*-\s*(\d{1,2})/(\d{1,2})", heading_text)
                    if not m:
                        continue
                    month_s, day_s = m.group(2), m.group(3)
                    year = fetch_date.year
                    month = int(month_s)
                    day_i = int(day_s)
                    day_parsed = datetime(year, month, day_i)
                    if abs((day_parsed - fetch_date).days) > 60:
                        if day_parsed > fetch_date:
                            day_parsed = datetime(year - 1, month, day_i)
                        else:
                            day_parsed = datetime(year + 1, month, day_i)
                else:
                    day_parsed = today

                day_key = day_parsed.strftime("%Y-%m-%d")
                if day_key in week_days:
                    continue

                hours_data = []
                for hour_el in container.select(".lc-reservation-openings-hour"):
                    quarters = hour_el.select(".lc-reservation-openings-quarter")
                    if not quarters:
                        continue

                    total = len(quarters)
                    slots = []
                    for q in quarters:
                        q_time_el = q.select_one(
                            ".lc-reservation-openings-time--quarter"
                        )
                        q_time = q_time_el.get_text(strip=True) if q_time_el else ""
                        q_avail = "lc-reservation-openings-quarter--available" in q.get(
                            "class", []
                        )
                        q_status = "available" if q_avail else "blocked"
                        slots.append({"time": q_time, "status": q_status})

                    available = sum(1 for s in slots if s["status"] == "available")

                    first_time_el = quarters[0].select_one(
                        ".lc-reservation-openings-time--quarter"
                    )
                    last_time_el = quarters[-1].select_one(
                        ".lc-reservation-openings-time--quarter"
                    )
                    time_start = first_time_el.get_text(strip=True) if first_time_el else ""
                    time_end = last_time_el.get_text(strip=True) if last_time_el else ""

                    if available == total:
                        status = "available"
                    elif available == 0:
                        status = "blocked"
                    else:
                        status = "partial"

                    hours_data.append({
                        "time": time_start,
                        "time_end": time_end,
                        "slots_available": available,
                        "slots_total": total,
                        "status": status,
                        "slots": slots,
                    })

                week_days[day_key] = hours_data

        _cache_set(cache_key, week_days, ttl=AVAIL_TTL)
        return week_days


# ---------- routes ----------

def _local_image(slug: str) -> str:
    img_path = Path("static/images") / f"{slug}.jpg"
    return f"/static/images/{slug}.jpg" if img_path.exists() else ""


@app.route("/")
def index():
    rooms = scrape_rooms()
    for r in rooms:
        r["image"] = _local_image(r["slug"])
    return render_template("index.html", rooms=rooms)


@app.route("/api/rooms")
def api_rooms():
    rooms = scrape_rooms()
    for r in rooms:
        r["image"] = _local_image(r["slug"])
    return jsonify(rooms)


@app.route("/api/availability")
def api_availability():
    date_param = request.args.get("date")
    refresh = request.args.get("refresh", "").lower() in ("1", "true", "yes")

    if date_param:
        try:
            target_date = datetime.strptime(date_param, "%Y-%m-%d")
        except ValueError:
            return jsonify({"error": "Invalid date format, use YYYY-MM-DD"}), 400
    else:
        target_date = datetime.now()

    rooms = scrape_rooms()

    if refresh:
        for r in rooms:
            _cache_del(f"avail:{r['url']}:{target_date.strftime('%Y-%m-%d')}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            pool.submit(scrape_availability, room["url"], target_date, refresh): room
            for room in rooms
        }
        result = []
        for future in concurrent.futures.as_completed(futures):
            room = futures[future]
            try:
                avail = future.result()
            except Exception:
                avail = {}
            result.append({
                "name": room["name"],
                "url": room["url"],
                "type": room["type"],
                "image": _local_image(room["slug"]),
                "availability": avail,
            })
    return jsonify(result)


# ---------- start ----------
def _warm_cache():
    """Pre-warm room cache at startup so first request isn't slow."""
    try:
        rooms = scrape_rooms()
        if rooms:
            today_str = datetime.now().strftime("%Y-%m-%d")
            for room in rooms:
                _cache_del(f"avail:{room['url']}:{today_str}")
            # Scrape today's availability in background
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                for room in rooms:
                    pool.submit(scrape_availability, room["url"], datetime.now())
            print(f"[warmup] cached {len(rooms)} rooms + today's availability")
    except Exception as e:
        print(f"[warmup] failed: {e}")


# Warm cache in background (won't block gunicorn startup)
threading.Thread(target=_warm_cache, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV", "production") == "development"
    app.run(debug=debug, host="0.0.0.0", port=port)
