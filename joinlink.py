"""FORWARD + JOIN LINK  -  invite guests from the HOST'S OWN WhatsApp.

HOST   finishes the card preview and replies 1  ->  event is created  ->  bot sends ONE card message
       (invitation card + text + a JOIN link).  The host long-presses it -> Forward -> sends to
       relatives / friends / groups from his own number.  (No guest numbers needed.)
GUEST  taps the JOIN link -> WhatsApp opens the bot with  JOIN <CODE>  typed -> Send ->
       bot asks the name -> RSVP (Yes/Maybe/No) -> family count -> meal -> entry pass.
       From here everything is the normal EventAgent flow (reminders, gate QR, STATUS, lucky draw...).

Host commands (after the event is created):   SHARE = get the forward message again
                                              CLOSE RSVP / OPEN RSVP = stop / allow new guests
Join links are kept in a NEW tab "EventLinks" (created automatically). Nothing else in your sheet changes.

Turn off any time with  JOINLINK=0  in .env  (the old "add guest numbers" step comes back).
"""
import json, os, random, re

import config
import checks
import excel_store as db

ENABLED = os.getenv("JOINLINK", "1") == "1"
LINKS = "EventLinks"
COLS = ["join_code", "event_id", "organizer_phone", "status", "created_at"]
JOIN_RE = re.compile(r"^\s*join[\s:\-_]*([A-Za-z0-9]{4,12})\s*$", re.I)
_READY = [False]


# ───────────────────────── storage ─────────────────────────
def _prepare():
    if not _READY[0]:
        db._ensure()
        db._call("ensure", sheets={LINKS: COLS})
        _READY[0] = True


def _link_by_code(code):
    _prepare()
    for l in db.rows(LINKS):
        if l["join_code"].upper() == code.upper():
            return l
    return None


def _link_by_event(event_id):
    _prepare()
    mine = [l for l in db.rows(LINKS) if l["event_id"] == event_id]
    return mine[-1] if mine else None


def _event(event_id):
    for e in db.rows("Events"):
        if e["event_id"] == event_id:
            return e
    return None


def _new_code(event_name):
    word = re.sub("[^A-Za-z]", "", (event_name.split() or [""])[0]).upper()
    cons = word[:1] + "".join(c for c in word[1:] if c not in "AEIOU")          # Batukamma -> BTK
    tag = (cons[:3] if len(cons) >= 3 else (word[:3] or "EVT")).ljust(3, "X")
    used = {l["join_code"].upper() for l in db.rows(LINKS)}
    while True:
        code = f"{tag}{random.randint(100, 999)}"
        if code not in used:
            return code


def _make_link(event_id, event_name, phone):
    _prepare()
    code = _new_code(event_name)
    db.add(LINKS, {"join_code": code, "event_id": event_id, "organizer_phone": phone, "status": "open", "created_at": db.now()})
    return code


# ───────────────────────── messages ─────────────────────────
def _share(phone, event_name, invitation_text, code, card):
    import bot
    link = bot.tap("JOIN " + code)
    intro = (f"🎉 *Your event is ready!* ✅\n*{event_name}*\n\n"
             "Here's how to invite your guests 👇\n"
             "1️⃣ *Long-press* the next message (the card) → tap *Forward*\n"
             "2️⃣ Send it to your family, friends or WhatsApp groups\n"
             "3️⃣ Guests tap the link, confirm, and get their *entry pass* automatically 🎟️\n\n"
             "📊 *STATUS* — live RSVP summary\n"
             "🔗 *SHARE* — get the forward message again\n"
             "🔒 *CLOSE RSVP* — stop new guests _(OPEN RSVP to allow again)_")
    caption = (invitation_text + "\n\n━━━━━━━━━━━━━━\n👉 *Tap to confirm your attendance:*\n" + link)
    return [bot.R(phone, intro), bot.R(phone, caption, config.INVITE_IMAGE_URL or card or None)]


# ───────────────────────── flow ─────────────────────────
def intercept(phone, t):
    """Called by bot.handle() after the registration check. Returns replies, or None = normal flow."""
    if not ENABLED:
        return None
    try:
        import bot
        up = (t or "").strip().upper()
        m = JOIN_RE.match(t or "")
        if m:
            return _join(phone, m.group(1).upper())
        state = db.get_session(phone).get("state", "idle")
        if state == "join_name":
            return _join_name(phone, (t or "").strip())
        if state == "awaiting_approval" and (bot.choice(t) == 1 or (t or "").strip().lower() in ("done", "good", "great", "looks good")):
            return _create_event(phone, db.get_session(phone))
        if state == "idle" and bot.is_organizer(phone):
            if up == "SHARE":
                return _reshare(phone)
            if up in ("CLOSE RSVP", "OPEN RSVP"):
                return _toggle(phone, up == "OPEN RSVP")
    except Exception as e:                         # never break the bot (old flow is used instead)
        print("❌ Join-link error (old flow used instead):", e)
    return None


def _create_event(phone, s):
    """Same as bot.dispatch(), but with NO guest list: creates the event + join link and sends the forward message."""
    import bot
    card = bot.saved_card(phone)
    cust = bot.ensure_customer(phone, s["organizer_name"])
    evt = db.next_id("EVT", "Events", "event_id")
    db.add("Events", {"event_id": evt, "customer_code": cust, "organizer_name": s["organizer_name"],
                      "organizer_phone": phone, "event_name": s["event_name"],
                      "date_venue": s["date_venue"], "invitation_text": s["invitation_text"],
                      "status": "live", "guests_invited": 0, "created_at": db.now(),
                      "card_style": bot.saved_style(phone), "maps_link": bot.saved_maps(phone)})
    code = _make_link(evt, s["event_name"], phone)
    text, name = s["invitation_text"], s["event_name"]
    db.set_session(phone, state="idle", pending_guests="", organizer_name="", event_name="",
                   date_venue="", invitation_text="")
    return _share(phone, name, text, code, card)


def _reshare(phone):
    import bot
    ev = bot.my_events(phone)[-1]
    link = _link_by_event(ev["event_id"])
    code = link["join_code"] if link else _make_link(ev["event_id"], ev["event_name"], phone)
    return _share(phone, ev["event_name"], ev["invitation_text"], code, bot.saved_card(phone))


def _toggle(phone, open_):
    import bot
    ev = bot.my_events(phone)[-1]
    link = _link_by_event(ev["event_id"])
    if not link:
        return [bot.R(phone, "No join link yet. Reply *SHARE* to create it first. 🔗")]
    db.update(LINKS, "join_code", link["join_code"], {"status": "open" if open_ else "closed"})
    return [bot.R(phone, ("🔓 RSVPs are *open* again." if open_ else
                          "🔒 RSVPs are *closed*. New guests can't join with the link now.\n"
                          "Reply *OPEN RSVP* to allow again.") + f"\n\n_{ev['event_name']}_")]


def _join(phone, code):
    import bot
    R = bot.R
    link = _link_by_code(code)
    ev = _event(link["event_id"]) if link else None
    if not link or not ev:
        return [R(phone, "Sorry, this invitation link isn't valid 🙏 Please ask the host to share it again.")]
    if link.get("status") != "open" or ev.get("status") != "live":
        return [R(phone, f"Sorry 🙏 RSVPs for *{ev['event_name']}* are closed now. Please contact the host.")]
    for g in db.rows("Guests"):
        if g["event_id"] == ev["event_id"] and db.norm(g["contact_phone"]) == phone:
            if g["conversation_state"] == "registered" and g["qr_code"]:
                return [R(phone, f"✅ You're already registered for *{ev['event_name']}*! Here's your pass again 👇")] + bot.pass_msg(phone, g, ev)
            db.update("Guests", "guest_id", g["guest_id"], {"conversation_state": "invited", "last_update": db.now()})
            return [R(phone, f"Welcome back, *{g['contact_name']}*! 🎉\n*{ev['event_name']}*\n📅 {ev['date_venue']}" + bot.RSVP_OPTIONS)]
    db.set_session(phone, state="join_name", pending_guests=json.dumps({"event_id": ev["event_id"]}))
    return [R(phone, f"👋 *Welcome!*\n*{ev['organizer_name']}* has invited you to *{ev['event_name']}* 🎉\n"
                     f"📅 {ev['date_venue']}\n\nMay I know your *name*? 🙏\n_(Type *CANCEL* to stop)_")]


def _join_name(phone, t):
    import bot
    R = bot.R
    if t.upper() == "CANCEL":
        db.set_session(phone, state="idle", pending_guests="")
        return [R(phone, "No problem 🙏 Tap the invitation link again anytime to RSVP.")]
    d = json.loads(db.get_session(phone).get("pending_guests") or "{}")
    name, err = checks.name(t)                    # STRICT: wrong answer -> ask the name again
    if err:
        n = checks.bump(d, "join_name")
        db.set_session(phone, pending_guests=json.dumps(d))
        return [R(phone, f"⚠️ {err}\n_(Type *CANCEL* to stop)_{checks.retry_hint(n)}")]
    d.pop("_tries", None)
    ev = _event(d.get("event_id", ""))
    if not ev:
        db.set_session(phone, state="idle", pending_guests="")
        return [R(phone, "Sorry, something went wrong 🙏 Please tap the invitation link again.")]
    db.add("Guests", {"guest_id": db.uid("G"), "event_id": ev["event_id"], "organizer_phone": ev["organizer_phone"],
                      "contact_name": name, "contact_phone": phone, "invite_status": "sent",
                      "conversation_state": "invited", "adults": 0, "children": 0,
                      "invited_at": db.now(), "last_update": db.now()})
    db.set_session(phone, state="idle", pending_guests="")
    return [R(phone, f"Thank you, *{name}*! 🙏\n🎉 You're invited to *{ev['event_name']}*\n📅 {ev['date_venue']}" + bot.RSVP_OPTIONS)]