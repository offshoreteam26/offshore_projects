"""Tiny 'database' - now stored in a GOOGLE SHEET (through a small Apps Script) instead of EventAgent.xlsx.

Same file name, same functions, same tabs and same columns as before, so bot.py, app.py,
reminders.py, make_poster.py and whatsapp.py work without any change.

Needs in .env:
  GOOGLE_SCRIPT_URL=https://script.google.com/macros/s/XXXXXXXX/exec    (Web app URL from Deploy)
  GOOGLE_SCRIPT_SECRET=your secret word                                  (same as SECRET in Code.gs)
"""
import atexit, json, os, queue, re, threading, time, uuid
from datetime import datetime
import requests
import config                                   # loads .env

LOCK = threading.RLock()

SCRIPT_URL = os.getenv("GOOGLE_SCRIPT_URL", "")
SCRIPT_SECRET = os.getenv("GOOGLE_SCRIPT_SECRET", "")
CACHE_SECONDS = float(os.getenv("SHEET_CACHE_SECONDS", "30"))   # fewer calls to Google = faster bot

SHEETS = {
    "Customers": ["customer_code", "name", "phone", "company", "created_at"],
    "Events": ["event_id", "customer_code", "organizer_name", "organizer_phone", "event_name",
               "date_venue", "invitation_text", "status", "guests_invited", "created_at", "starts_at", "card_style", "maps_link"],
    "Guests": ["guest_id", "event_id", "organizer_phone", "contact_name", "contact_phone",
               "invite_status", "conversation_state", "adults", "children", "qr_code",
               "invited_at", "responded_at", "last_update",
               "checkin_status", "checkin_time", "lucky_draw", "rating", "feedback",
               "reminder_morning", "reminder_pre", "meal"],
    "Sessions": ["phone", "state", "organizer_name", "event_name", "date_venue",
                 "invitation_text", "updated_at", "pending_guests"],
    "ConversationLog": ["msg_id", "timestamp", "phone", "direction", "message_type", "message_text"],
}


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def norm(phone):
    """Keep last 10 digits (Indian numbers), e.g. 919951542139@c.us -> 9951542139."""
    d = re.sub(r"\D", "", str(phone or ""))
    return d[-10:] if len(d) >= 10 else d


def uid(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


# ───────────────────────── Google Sheet plumbing ─────────────────────────
_READY = [False]
_CACHE = {}                 # sheet name -> (time, values)


def _s(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v)


def _call(action, **payload):
    """Send one command to the Apps Script and return its JSON answer."""
    if not SCRIPT_URL:
        raise RuntimeError("GOOGLE_SCRIPT_URL is empty in .env")
    body = json.dumps({"secret": SCRIPT_SECRET, "action": action, **payload}).encode("utf-8")
    last = None
    for i in range(4):
        try:
            r = requests.post(SCRIPT_URL, data=body, timeout=60,
                              headers={"Content-Type": "text/plain; charset=utf-8"})
        except requests.RequestException as e:          # network problem -> try again
            last = e
            time.sleep(2 ** i)
            continue
        try:
            data = r.json()
        except ValueError:
            raise RuntimeError("Google Script did not answer with JSON. Check: Deploy > Web app > "
                               "'Who has access' = Anyone, and GOOGLE_SCRIPT_URL ends with /exec")
        if isinstance(data, dict) and data.get("error"):
            raise RuntimeError(f"Google Sheet error: {data['error']}")
        return data
    raise RuntimeError(f"Could not reach Google Script: {last}")


def _ensure():
    """First use: create missing tabs / header columns in the Google Sheet (same as the Excel version)."""
    if not _READY[0]:
        _call("ensure", sheets=SHEETS)
        _READY[0] = True


# Writes go to Google in a background thread (in order), reads come from the local copy that is
# updated immediately. So the bot never waits for Google to answer.
_Q = queue.Queue()
_WORKER = [None]


def _worker():
    while True:
        action, payload = _Q.get()
        try:
            _call(action, **payload)
        except Exception as e:
            print(f"❌ Google Sheet write failed ({action} {payload.get('sheet')}): {str(e)[:150]}")
        finally:
            _Q.task_done()


def _send(action, **payload):
    if _WORKER[0] is None:
        _WORKER[0] = threading.Thread(target=_worker, daemon=True)
        _WORKER[0].start()
    _Q.put((action, payload))


def _flush(timeout=20):
    t0 = time.time()
    while _Q.unfinished_tasks and time.time() - t0 < timeout:
        time.sleep(0.2)


atexit.register(_flush)


def _values(sheet, fresh=False):
    _ensure()
    hit = _CACHE.get(sheet)
    if hit and (_Q.unfinished_tasks or (not fresh and time.time() - hit[0] < CACHE_SECONDS)):
        return hit[1]
    _Q.join()                                   # make sure Google has all our writes before we download
    vals = _call("rows", sheet=sheet)["values"]
    _CACHE[sheet] = (time.time(), vals)
    return vals


# ───────────────────────── public API (unchanged) ─────────────────────────
def rows(sheet):
    with LOCK:
        vals = _values(sheet)
        if not vals:
            return []
        head = vals[0]
        out = []
        for r in vals[1:]:
            if any(v not in (None, "") for v in r):
                r = list(r) + [""] * (len(head) - len(r))
                out.append({h: ("" if v is None else str(v)) for h, v in zip(head, r)})
        return out


def add(sheet, row):
    with LOCK:
        _ensure()
        row = {k: _s(v) for k, v in row.items()}
        hit = _CACHE.get(sheet)
        if hit and hit[1]:
            head = hit[1][0]
            hit[1].append([row.get(h, "") for h in head])
        _send("add", sheet=sheet, row=row)


def update(sheet, key, value, changes):
    """Update the first row where `key` == value. Returns True if found."""
    with LOCK:
        _ensure()
        vals = _values(sheet)
        changes = {k: _s(v) for k, v in changes.items()}
        if not vals or key not in vals[0]:
            return False
        head = vals[0]
        ki = head.index(key)
        for r in vals[1:]:
            if len(r) > ki and _s(r[ki]) == _s(value):
                r.extend([""] * (len(head) - len(r)))
                for k, v in changes.items():
                    if k in head:
                        r[head.index(k)] = v
                _send("update", sheet=sheet, key=key, value=_s(value), changes=changes)
                return True
        return False


def upsert(sheet, key, value, fields):
    if not update(sheet, key, value, fields):
        add(sheet, {key: value, **fields})


def next_id(prefix, sheet, col, width=5):
    nums = [int(m.group(1)) for r in rows(sheet) if (m := re.search(r"(\d+)$", r[col]))]
    return f"{prefix}-{(max(nums) if nums else 0) + 1:0{width}d}"


def log(msg_id, phone, direction, mtype, text):
    add("ConversationLog", {"msg_id": msg_id, "timestamp": now(), "phone": phone,
                            "direction": direction, "message_type": mtype, "message_text": text})


def get_session(phone):
    for s in rows("Sessions"):
        if norm(s["phone"]) == phone:
            return s
    return {"phone": phone, "state": "idle", "pending_guests": ""}


def set_session(phone, **fields):
    fields["updated_at"] = now()
    upsert("Sessions", "phone", phone, fields)

def _warm():
    """Download the sheets once at start-up, so the very first WhatsApp message is already fast."""
    try:
        for name in SHEETS:
            if name != "ConversationLog":
                _values(name)
    except Exception as e:
        print("ℹ️ Sheet warm-up skipped:", str(e)[:120])


if SCRIPT_URL:
    threading.Thread(target=_warm, daemon=True).start()