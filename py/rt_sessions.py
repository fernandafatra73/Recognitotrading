"""Sesi pasar (WIB), jadwal berita (FOMC, NFP, events.txt, kalender online)."""
import json
import os
from datetime import datetime, timedelta, timezone

import requests

WIB = timezone(timedelta(hours=7))

SESSION_HOURS = (5, 7, 14, 16, 19, 23, 4)  # jam WIB pergantian sesi
BLOCK_ENDS = {9: "05-09", 13: "09-13", 17: "13-17", 21: "17-21", 1: "21-01", 4: "01-04"}

# (mulai, selesai, judul, rincian, catatan persilangan, biasanya)
SEGMENTS = [
    (4, 5, "PASAR SEPI", "transisi New York ke Sydney 04:00-05:00",
     "Sydney buka 05:00", "Spread melebar dan gerak kecil. Hindari entry baru."),
    (5, 7, "SESI SYDNEY", "Sydney 05:00-14:00",
     "Tidak ada persilangan - persilangan Sydney-Tokyo mulai 07:00",
     "Pasar masih tipis, cenderung range. Waspadai spread dan gap pembukaan."),
    (7, 14, "OVERLAP SYDNEY - TOKYO", "Sydney 05:00-14:00 + Tokyo 07:00-16:00",
     "persilangan Sydney-Tokyo sampai 14:00, lalu Tokyo-London",
     "Likuiditas naik, range Asia terbentuk. Breakout kecil, sering fake move."),
    (14, 16, "LONDON OPEN (TOKYO + LONDON)", "Tokyo 07:00-16:00 + London 14:00-23:00",
     "persilangan Tokyo-London sampai 16:00",
     "Volatilitas melonjak. Sering sweep high/low Asia lalu arah hari terbentuk."),
    (16, 19, "SESI LONDON", "London 14:00-23:00",
     "Tidak ada persilangan - persilangan London-New York mulai 19:00",
     "Arah tren harian terbentuk. Ikuti BOS London, entry di pullback ke FVG / order block."),
    (19, 23, "OVERLAP LONDON - NEW YORK", "London 14:00-23:00 + New York 19:00-04:00",
     "persilangan London-New York sampai 23:00",
     "Volatilitas tertinggi, berita AS. Breakout besar dan reversal tajam; pakai SL ketat."),
    (23, 28, "SESI NEW YORK", "New York 19:00-04:00",
     "London sudah tutup, New York sampai 04:00",
     "Volume menurun setelah London tutup. Sering koreksi/profit taking, gerak berita AS."),
]


def now_wib():
    return datetime.now(WIB)


def segment(hour):
    h = hour if hour >= 4 else hour + 24
    for s in SEGMENTS:
        if s[0] <= h < s[1]:
            return s
    return SEGMENTS[-1]


def session_line(dt):
    s = segment(dt.hour)
    return "Waktu trading: %s (%s)  •  %s" % (s[2], s[3], s[4]), "Biasanya: " + s[5], s[2]


# ---- berita ----
def _us_dst(d):
    y = d.year
    mar = datetime(y, 3, 8)
    mar += timedelta(days=(6 - mar.weekday()) % 7)
    nov = datetime(y, 11, 1)
    nov += timedelta(days=(6 - nov.weekday()) % 7)
    return mar <= datetime(d.year, d.month, d.day) < nov


def _et_to_wib(y, m, d, hh, mm):
    off = 4 if _us_dst(datetime(y, m, d)) else 5
    return (datetime(y, m, d, hh, mm) + timedelta(hours=off)).replace(tzinfo=timezone.utc).astimezone(WIB)


FOMC_2026 = [(1, 28), (3, 18), (4, 29), (6, 17), (7, 29), (9, 16), (10, 28), (12, 9)]


def builtin_events(year):
    ev = []
    for m, d in FOMC_2026 if year == 2026 else []:
        ev.append((_et_to_wib(year, m, d, 14, 0), "FOMC Keputusan Suku Bunga", "High"))
    for m in range(1, 13):
        d = datetime(year, m, 1)
        d += timedelta(days=(4 - d.weekday()) % 7)  # Jumat pertama
        ev.append((_et_to_wib(year, m, d.day, 8, 30), "NFP (Non-Farm Payrolls)", "High"))
    return ev


def read_events_txt(path):
    ev = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(";")
                if len(parts) < 3:
                    continue
                try:
                    dt = datetime.strptime(parts[0].strip(), "%Y-%m-%d %H:%M").replace(tzinfo=WIB)
                except ValueError:
                    continue
                ev.append((dt, parts[1].strip(), parts[2].strip()))
    except OSError:
        pass
    return ev


def fetch_online_events():
    r = requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json", timeout=10,
                     headers={"User-Agent": "RecognitoTrading/2.0"})
    r.raise_for_status()
    ev = []
    for it in r.json():
        if it.get("country") != "USD" or it.get("impact") != "High":
            continue
        dt = datetime.fromisoformat(it["date"]).astimezone(WIB)
        ev.append((dt, it.get("title", "Berita USD"), "High"))
    return ev
