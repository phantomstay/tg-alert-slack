"""Parse a PJX flight alert and render it as a Slack message."""
import json
import os
import re

FIELDS = {
    "route":    r"Route:\s*(.+)",
    "date":     r"Date:\s*(.+)",
    "schedule": r"Schedule:\s*(.+)",
    "aircraft": r"Aircraft Type:\s*(.+)",
    "seats":    r"Available Seats:\s*(\d+)",
    "price":    r"Discounted Rate:\s*\$?([\d,]+)",
}


def parse(text):
    """Return a dict of alert fields, or None if this isn't an alert."""
    if not text or "Route:" not in text:
        return None

    out = {}
    for key, pattern in FIELDS.items():
        m = re.search(pattern, text)
        out[key] = m.group(1).strip() if m else None

    if not out["route"]:
        return None

    out["seats"] = int(out["seats"]) if out["seats"] else None
    out["price"] = int(out["price"].replace(",", "")) if out["price"] else None
    codes = re.findall(r"\(([A-Z]{3})\)", out["route"])
    out["from_code"], out["to_code"] = (codes + [None, None])[:2]
    return out


def passes_filters(alert, max_price=None, min_seats=None):
    if max_price and alert["price"] and alert["price"] > max_price:
        return False
    if min_seats and alert["seats"] and alert["seats"] < min_seats:
        return False
    return True


def _load_image_map():
    """aircraft type -> public image url, from aircraft_images.json.

    Keys starting with "_" are notes for humans, not aircraft.
    """
    path = os.path.join(os.path.dirname(__file__), "aircraft_images.json")
    try:
        with open(path) as f:
            return {k.lower().strip(): v for k, v in json.load(f).items()
                    if not k.startswith("_")}
    except FileNotFoundError:
        return {}


IMAGE_MAP = _load_image_map()


def image_for(alert):
    """Pick the photo for this alert.

    The channel posts short type codes ("GLEX", "CL350", "C56P"), so an exact
    match on the whole Aircraft Type is tried first. Only if that misses do we
    fall back to fragment matching, which is what full spelled-out names like
    "Bombardier Global 7500" need. Substring matching alone is wrong for codes:
    "L600" sits inside "L6000", and a near-miss puts the wrong jet on the card.

    Placeholder entries (anything containing REPLACE-ME) are ignored, so an
    unfilled aircraft_images.json falls through to ALERT_IMAGE_URL instead of
    handing Slack a URL it can't fetch.
    """
    aircraft = (alert.get("aircraft") or "").lower().strip()
    if aircraft:
        url = IMAGE_MAP.get(aircraft)
        if url and "REPLACE-ME" not in url:
            return url
        matches = [
            (frag, url) for frag, url in IMAGE_MAP.items()
            if frag and frag in aircraft and "REPLACE-ME" not in url
        ]
        if matches:
            return max(matches, key=lambda m: len(m[0]))[1]
    # read at call time, not import time: run.py imports us before load_dotenv()
    return os.getenv("ALERT_IMAGE_URL") or None


def mapped_images():
    """Every distinct image url in the map, with the types that point at it."""
    out = {}
    for frag, url in IMAGE_MAP.items():
        if "REPLACE-ME" not in url:
            out.setdefault(url, []).append(frag)
    return out


def to_slack(alert):
    """Slack Block Kit payload."""
    title = alert["route"]
    if alert["from_code"] and alert["to_code"]:
        title = f"{alert['from_code']} → {alert['to_code']}"

    detail = " · ".join(
        p for p in [
            alert["date"],
            alert["schedule"],
            alert["aircraft"],
            f"{alert['seats']} seats" if alert["seats"] else None,
        ] if p
    )
    price = f"${alert['price']:,}" if alert["price"] else "Rate on request"

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{title}*  ·  *{price}*\n{alert['route']}",
            },
        },
    ]

    image_url = image_for(alert)
    if image_url:
        blocks.append({
            "type": "image",
            "image_url": image_url,
            "alt_text": alert["aircraft"] or title,
        })

    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": detail}],
    })

    return {"text": f"Flight alert: {title} — {price}", "blocks": blocks}
