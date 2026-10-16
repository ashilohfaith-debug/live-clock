"""Vercel serverless endpoint: serves the room GIF with the clock showing the current time.

  /clock.gif                       -> Chennai time (Asia/Kolkata), 24-hour
  /clock.gif?tz=America/New_York   -> any IANA time zone
  /clock.gif?format=12             -> 12-hour clock (leading zero kept, e.g. 01:17)
"""
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
import os

from _clock_gif import GIF_PATH, render

DEFAULT_TZ = "Asia/Kolkata"
IST = timezone(timedelta(hours=5, minutes=30))


def _now(tz_name):
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(tz_name))
    except Exception:
        return datetime.now(IST)          # bad/unknown zone -> fall back to IST


def _hhmm(query):
    tz_name = (query.get("tz") or [DEFAULT_TZ])[0]
    fmt = (query.get("format") or ["24"])[0]
    now = _now(tz_name)
    hour = now.hour
    if fmt == "12":
        hour = hour % 12 or 12
    return f"{hour:02d}{now.minute:02d}"


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        try:
            body = render(_hhmm(query))
        except Exception:
            # never leave a broken image on the profile: fall back to the plain GIF
            with open(GIF_PATH, "rb") as f:
                body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "image/gif")
        self.send_header("Content-Length", str(len(body)))
        # no caching, so GitHub fetches a fresh image (and the current minute) each time
        self.send_header("Cache-Control", "no-cache, no-store, max-age=0, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(body)
