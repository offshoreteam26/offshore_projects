"""Venue map pin (free, no API key).

The host can give the exact venue in two ways:
  1) WhatsApp  📎 Attach ➔ Location  (a location pin)   -> read from the UltraMsg message
  2) paste a Google Maps link (Maps app ➔ Share ➔ Copy link)

Everything is turned into ONE clean Google Maps link that guests can tap.
"""
import re

# a pin message is handed to the bot as text:  LOCATION|lat|lng|name|address
PREFIX = "LOCATION|"

ALLOWED_LINK = re.compile(
    r"https?://(?:www\.)?(?:google\.[a-z.]{2,6}/maps[^\s]*|maps\.google\.[a-z.]{2,6}[^\s]*"
    r"|maps\.app\.goo\.gl/[^\s]+|goo\.gl/maps/[^\s]+)", re.I)
PAIR = re.compile(r"(-?\d{1,3}\.\d{3,})\s*[,;]\s*(-?\d{1,3}\.\d{3,})")
AT_PAIR = re.compile(r"@(-?\d{1,3}\.\d+),(-?\d{1,3}\.\d+)")
BANG_PAIR = re.compile(r"!3d(-?\d{1,3}\.\d+)!4d(-?\d{1,3}\.\d+)")


def _ok(lat, lng):
    try:
        lat, lng = float(lat), float(lng)
    except (TypeError, ValueError):
        return None
    if abs(lat) > 90 or abs(lng) > 180 or (lat == 0 and lng == 0):
        return None
    return round(lat, 6), round(lng, 6)


def link(lat, lng):
    return f"https://www.google.com/maps/search/?api=1&query={lat},{lng}"


def _clean(s):
    return " ".join(str(s or "").split())


def from_message(data):
    """UltraMsg message dict -> {'link','name','address'} or None.  Tolerant: UltraMsg versions differ."""
    if not isinstance(data, dict):
        return None
    sources = [data]
    for k in ("location", "locationMessageData", "message", "data"):
        if isinstance(data.get(k), dict):
            sources.append(data[k])
    lat = lng = None
    for src in sources:
        for a, b in (("latitude", "longitude"), ("lat", "lng"), ("lat", "lon"), ("degreesLatitude", "degreesLongitude")):
            if src.get(a) not in (None, "") and src.get(b) not in (None, ""):
                lat, lng = src[a], src[b]
                break
        if lat is not None:
            break
    pair = _ok(lat, lng) if lat is not None else None
    body = str(data.get("body") or "")
    if not pair:                                             # coordinates inside the text body
        m = AT_PAIR.search(body) or BANG_PAIR.search(body) or PAIR.search(body)
        pair = _ok(*m.groups()) if m else None
    if not pair:
        return None
    name = address = ""
    for src in sources:
        name = name or _clean(src.get("nameLocation") or src.get("name") or src.get("title") or "")
        address = address or _clean(src.get("address") or "")
    if not name and body and not PAIR.search(body) and not body.lower().startswith(("http", "data:")) and len(body) < 120:
        name = _clean(body.splitlines()[0])                 # some versions put the place name in body
    return {"link": link(*pair), "name": name, "address": address}


def encode(loc):
    """Pin -> the text the bot receives (so the bot needs no special message type)."""
    return f"{PREFIX}{loc['link']}|{loc.get('name', '').replace('|', ' ')}|{loc.get('address', '').replace('|', ' ')}"


def parse(text):
    """Text from the host -> {'link','name','address'} (a pin or a Google Maps link) or None."""
    t = str(text or "").strip()
    if t.startswith(PREFIX):
        parts = (t[len(PREFIX):].split("|") + ["", "", ""])[:3]
        return {"link": parts[0], "name": _clean(parts[1]), "address": _clean(parts[2])}
    m = ALLOWED_LINK.search(t)
    if m:
        url = m.group(0).rstrip(").,;!?\"'")
        p = AT_PAIR.search(url) or BANG_PAIR.search(url)
        q = re.search(r"[?&](?:q|query|ll|destination)=(-?\d{1,3}\.\d+)(?:,|%2C)(-?\d{1,3}\.\d+)", url)
        pair = _ok(*(p or q).groups()) if (p or q) else None
        return {"link": link(*pair) if pair else url, "name": "", "address": ""}
    return None


def venue_text(loc, max_len=60):
    """Name for the invitation: place name (+ address if it still fits on the card)."""
    name, addr = loc.get("name", ""), loc.get("address", "")
    if name and addr and addr.lower() not in name.lower() and len(name) + len(addr) + 2 <= max_len:
        return f"{name}, {addr}"
    return name