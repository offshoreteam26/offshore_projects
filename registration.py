"""Client REGISTRATION gate for the  START_EVENT_SETUP  link.

   New person opens the link  -> "Would you like to create an event?"  Yes / Not interested
        Not interested        -> polite goodbye, nothing opens, nothing is created
        Yes                   -> registration (name, email) -> saved -> event setup starts
   Already registered person  -> "Welcome back"  1 Create new event / 2 My events / 3 Not now
   Old customers (who already created events before this feature) count as registered - no re-registration.

Saved in a NEW tab  "Registrations"  (created automatically). Your other tabs/columns are not changed,
except that one row is added to "Customers" when someone registers (so the event is linked to them).

Turn off any time with  REGISTRATION=0  in .env  (the old behaviour comes back).
"""
import json, os, re

import checks
import excel_store as db

ENABLED = os.getenv("REGISTRATION", "1") == "1"
START_WORDS = ("START_EVENT_SETUP", "HOST-EVENT", "HOST EVENT")
SHEET = "Registrations"
COLS = ["phone", "name", "email", "status", "created_at", "registered_at", "updated_at"]
YES = ("1", "1️⃣", "yes", "y", "yeah", "ok", "okay", "interested", "i am interested", "i'm interested", "create", "sure")
NO = ("2", "2️⃣", "no", "n", "nope", "not interested", "no thanks", "not now", "later")
_READY = [False]


# ───────────────────────── storage ─────────────────────────
def _prepare():
    """Make sure the Registrations tab exists (first use only)."""
    if not _READY[0]:
        db._ensure()
        db._call("ensure", sheets={SHEET: COLS})
        _READY[0] = True


def _get(phone):
    _prepare()
    mine = [r for r in db.rows(SHEET) if db.norm(r.get("phone")) == phone]
    return mine[-1] if mine else None


def _save(phone, **fields):
    _prepare()
    fields["updated_at"] = db.now()
    if _get(phone):
        db.update(SHEET, "phone", phone, fields)
    else:
        db.add(SHEET, {"phone": phone, "created_at": db.now(), **fields})


def _customer(phone):
    for c in db.rows("Customers"):
        if db.norm(c.get("phone")) == phone:
            return c
    return None


def is_registered(phone):
    r = _get(phone)
    if r and r.get("status") == "registered":
        return True
    if r and r.get("status") == "not_interested":
        return False
    import bot
    return bool(_customer(phone)) or bot.is_organizer(phone)      # old customers = already registered


def _first_name(phone):
    r, c = _get(phone), _customer(phone)
    name = ((r or {}).get("name") or (c or {}).get("name") or "").strip()
    return name.split()[0] if name else "there"


# ───────────────────────── messages ─────────────────────────
def _offer(btn):
    return ("✨ *Welcome to EventAgent* ✨\n"
            "Beautiful WhatsApp invitations, RSVPs, guest passes and entry check-in — all in one place. 🎉\n\n"
            "*Would you like to create an event with us?*\n\n"
            + btn("✅ Yes, I'm interested", "Yes") + "\n\n"
            + btn("❌ Not interested", "No") + "\n\n_(or reply 1 / 2)_")


def _menu(first, btn):
    return (f"👋 *Welcome back, {first}!*\nWhat would you like to do?\n\n"
            + btn("1️⃣ 🎉 Create a new event", "1") + "\n\n"
            + btn("2️⃣ 📊 My events", "2") + "\n\n"
            + btn("3️⃣ 👋 Not now", "3"))


ASK = {
    "reg_name": "👤 *Step 1 of 2*\nWhat's your *full name*?",
    "reg_email": "📧 *Step 2 of 2*\nYour *email address*?\n_e.g. ramesh@gmail.com_",
}
NEXT = {"reg_name": "reg_email", "reg_email": None}
FIELD = {"reg_name": "name", "reg_email": "email"}
GOODBYE = ("No problem at all 🙏 Thank you for your time!\n"
           "If you change your mind, just open the link again anytime. Have a lovely day! 😊")


# ───────────────────────── flow ─────────────────────────
def intercept(phone, t):
    """Called first by bot.handle(). Returns the replies, or None = not mine (normal bot flow continues)."""
    if not ENABLED:
        return None
    up = (t or "").strip().upper()
    try:
        if up in START_WORDS:
            return _start(phone)
        state = db.get_session(phone).get("state", "idle")
        if state.startswith("reg_"):
            return _step(phone, (t or "").strip(), state)
    except Exception as e:                      # never break the bot because of registration
        print("❌ Registration error (old flow used instead):", e)
    return None


def _start(phone):
    import bot
    if is_registered(phone):
        db.set_session(phone, state="reg_menu", pending_guests="{}")
        return [bot.R(phone, _menu(_first_name(phone), bot.btn))]
    db.set_session(phone, state="reg_offer", pending_guests="{}")
    return [bot.R(phone, _offer(bot.btn))]


def _begin_event(phone):
    """Same as the original START_EVENT_SETUP: asks Step 1 of the event wizard."""
    import bot
    db.set_session(phone, state="ask_name", organizer_name="", event_name="",
                   date_venue="", invitation_text="", pending_guests="{}")
    return bot.WELCOME


def _step(phone, t, state):
    import bot
    R, low = bot.R, t.strip().lower()
    if t.strip().upper() == "CANCEL":
        db.set_session(phone, state="idle", pending_guests="")
        return [R(phone, "Cancelled. Open the link again anytime to continue. 🙏")]

    if state == "reg_offer":
        if low in YES:
            _save(phone, status="interested")
            db.set_session(phone, state="reg_name", pending_guests="{}")
            return [R(phone, "🙏 Great! Let's get you registered — just 2 quick questions.\n"
                             "_(Type *CANCEL* anytime to stop.)_\n\n" + ASK["reg_name"])]
        if low in NO:
            _save(phone, status="not_interested")
            db.set_session(phone, state="idle", pending_guests="")
            return [R(phone, GOODBYE)]
        return [R(phone, "Please tap *Yes* or *No* 👇\n\n" + btn_pair(bot))]

    if state == "reg_menu":
        if low in ("1", "1️⃣", "create", "new", "yes", "create event", "create a new event"):
            return [R(phone, _begin_event(phone))]
        if low in ("2", "2️⃣", "my events", "events", "status"):
            db.set_session(phone, state="idle", pending_guests="")
            if bot.is_organizer(phone):
                return bot.organizer_commands(phone, "STATUS")
            return [R(phone, "You haven't created an event yet. Open the link and choose *Create a new event*. 🎉")]
        if low in ("3", "3️⃣", "no", "not now", "later"):
            db.set_session(phone, state="idle", pending_guests="")
            return [R(phone, "Sure 👋 Open the link whenever you're ready!")]
        return [R(phone, "Please tap *1*, *2* or *3* 👇\n\n" + _menu(_first_name(phone), bot.btn))]

    if state in FIELD:
        d = json.loads(db.get_session(phone).get("pending_guests") or "{}")
        key = FIELD[state]
        if low == "back":
            if state == "reg_name":
                return [R(phone, "You're already at the first step 🙂 Just type your name, or *CANCEL* to stop.")]
            d.pop("_tries", None)
            db.set_session(phone, state="reg_name", pending_guests=json.dumps(d))
            return [R(phone, "↩️ Going back.\n\n" + ASK["reg_name"] + (f"\n\n_Current: *{d['name']}*  —  type a new one, or *KEEP*._" if d.get("name") else ""))]
        if low == "keep" and d.get(key):
            value, err = d[key], None
        else:
            value, err = checks.CHECK[key](t)         # STRICT: wrong answer -> same question again
        if err:
            n = checks.bump(d, state)
            db.set_session(phone, pending_guests=json.dumps(d))
            return [R(phone, f"⚠️ {err}\n\n{ASK[state]}{checks.retry_hint(n)}")]
        d.pop("_tries", None)
        d[key] = value
        nxt = NEXT[state]
        if nxt:
            db.set_session(phone, state=nxt, pending_guests=json.dumps(d))
            return [R(phone, "✅ Got it!\n\n" + ASK[nxt])]
        return _complete(phone, d)

    db.set_session(phone, state="idle", pending_guests="")
    return None


def btn_pair(bot):
    return bot.btn("✅ Yes, I'm interested", "Yes") + "\n\n" + bot.btn("❌ Not interested", "No")


def _complete(phone, d):
    import bot
    _save(phone, name=d.get("name", ""), email=d.get("email", ""), status="registered", registered_at=db.now())
    cust = _customer(phone)
    if cust:
        db.update("Customers", "phone", cust["phone"], {"name": d.get("name", "")})
    else:
        code = db.next_id("CUS", "Customers", "customer_code")
        db.add("Customers", {"customer_code": code, "name": d.get("name", ""), "phone": phone,
                             "company": bot.config.DEFAULT_COMPANY, "created_at": db.now()})
    first = (d.get("name") or "there").split()[0]
    return [bot.R(phone, f"🎉 *Registration complete, {first}!* ✅\nYou're all set — let's create your event right now. 🚀"),
            bot.R(phone, _begin_event(phone))]