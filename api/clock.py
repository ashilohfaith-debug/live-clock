"""Vercel serverless endpoint: serves the room GIF with the clock showing the current time.

  /api/clock                       -> Chennai time (Asia/Kolkata), 24-hour
  /api/clock?tz=America/New_York   -> any IANA time zone
  /api/clock?format=12             -> 12-hour clock (leading zero kept, e.g. 01:17)
  /api/clock?debug=1               -> shows the error text if something is wrong
"""
import os
import sys
import traceback
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

# Make the helper module importable however Vercel loads this file
# (as "clock" or as "api.clock").
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

DEFAULT_TZ = "Asia/Kolkata"
IST = timezone(timedelta(hours=5, minutes=30))
FALLBACK_GIF = os.path.join(_HERE, "..", "assets", "wallpaper.gif")


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
    def _send(self, status, ctype, body, cache=True):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if cache:
            # no caching, so GitHub fetches a fresh image (and the current minute) each time
            self.send_header("Cache-Control", "no-cache, no-store, max-age=0, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        debug = "debug" in query

        # Serve the auto-refreshing HTML page when ?html=1
        if "html" in query:
            html = b"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Live Clock</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      background: #000;
      display: flex;
      justify-content: center;
      align-items: center;
      min-height: 100vh;
      overflow: hidden;
    }
    img {
      max-width: 100%;
      max-height: 100vh;
      display: block;
      image-rendering: pixelated;
    }
  </style>
</head>
<body>
  <img id="clock" src="/clock" alt="Live Clock">
  <script>
  const img = document.getElementById('clock');

  function updateClock() {
    // 1. Preload the new GIF in the background so there's zero flickering
    const nextImg = new Image();
    nextImg.src = '/clock?t=' + Date.now();
    nextImg.onload = () => {
      img.src = nextImg.src;
    };

    // 2. Schedule the next update exactly at the start of the next minute (:00s)
    const now = new Date();
    const msUntilNextMinute = (60 - now.getSeconds()) * 1000 - now.getMilliseconds() + 500;
    setTimeout(updateClock, msUntilNextMinute);
  }

  // Start syncing to the next minute
  const now = new Date();
  const msUntilNextMinute = (60 - now.getSeconds()) * 1000 - now.getMilliseconds() + 500;
  setTimeout(updateClock, msUntilNextMinute);
</script>
</body>
</html>"""
            self._send(200, "text/html; charset=utf-8", html, cache=False)
            return

        # Serve the GIF
        problem = None
        try:
            from clock_gif import render
            self._send(200, "image/gif", render(_hhmm(query)))
            return
        except Exception:
            problem = traceback.format_exc()
            print(problem, file=sys.stderr)

        if debug:
            self._send(500, "text/plain; charset=utf-8", problem.encode("utf-8"), cache=False)
            return
        try:
            with open(FALLBACK_GIF, "rb") as f:
                self._send(200, "image/gif", f.read())
        except Exception:
            msg = (problem + "\n\nFallback GIF also failed:\n" + traceback.format_exc())
            self._send(500, "text/plain; charset=utf-8", msg.encode("utf-8"), cache=False)
