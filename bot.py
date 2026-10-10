"""
EventAgent brain (100% WhatsApp flow).

process(phone, text, type, msg_id) -> list of replies [(to_phone, text, image_url_or_None), ...]
The caller (app.py or test_chat.py) decides how to send them.

Flow:  START_EVENT_SETUP -> details -> preview -> contacts -> SEND
       guest: RSVP (1/2/3) -> family count -> confirm -> pass -> FAQ
       organizer: STATUS | CHECKIN <pass> | LUCKYDRAW | FEEDBACK
"""
import base64, json, os, random, re
from urllib.parse import quote

import config
import checks
import geo
import excel_store as db

try:                                   # invitation CARD image (needs Pillow; optional)
    import invite_card
except Exception as _e:                # bot still works with text-only invitations
    invite_card = None
    print("ℹ️ Invitation cards are off (", _e, ") - run: pip install pillow")

try:                                   # ticket pass card (needs Pillow + qrcode; optional)
    import pass_card
except Exception as _e:
    pass_card = None
    print("ℹ️ Pass cards are off (", _e, ") - run: pip install pillow qrcode")
import extras                          # Directions + Add-to-calendar links

try:                                   # client registration before event setup (registration.py)
    import registration
except Exception as _e:
    registration = None
    print("ℹ️ Registration is off (", _e, ")")

try:                                   # forward + join link (joinlink.py)
    import joinlink
except Exception as _e:
    joinlink = None
    print("ℹ️ Join link is off (", _e, ")")
    


CARDS_DIR = config.CARDS_DIR
CARD_ON = os.getenv("INVITE_CARD", "1") == "1"       # set INVITE_CARD=0 in .env to switch cards off


def save_qr_png(pass_no, link):
    try:
        import qrcode
        q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_Q, border=4, box_size=10)
        q.add_data(link)
        q.make(fit=True)
        q.make_image(fill_color="black", back_color="white").save(
            os.path.join(config.QR_DIR, re.sub(r"[^A-Za-z0-9_-]", "_", pass_no) + ".png"))
    except Exception as e:
        print("ℹ️ QR image not saved:", e)

def _data_uri(jpeg):
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()


def make_card_for(phone, d):
    """Draw the card for this organizer's event, remember it on disk, return it as a data-URI (or None)."""
    if not (CARD_ON and invite_card):
        return None
    try:
        style = invite_card.resolve_style(d["event"], d.get("style"))
        jpeg = invite_card.make_card(d["name"], d["event"], d["date"], d.get("venue", ""), style)
        os.makedirs(CARDS_DIR, exist_ok=True)
        with open(os.path.join(CARDS_DIR, f"{phone}.jpg"), "wb") as f:
            f.write(jpeg)
        with open(os.path.join(CARDS_DIR, f"{phone}.style"), "w") as f:      # remembered for the guests' passes
            f.write(style)
        return _data_uri(jpeg)
    except Exception as e:                         # e.g. Telugu text -> fall back to the text invitation
        print(f"❌ Card not made, sending text invitation instead: {type(e).__name__}: {e}")
        return None


def saved_style(phone):
    try:
        with open(os.path.join(CARDS_DIR, f"{phone}.style")) as f:
            return f.read().strip()
    except OSError:
        return ""


def saved_maps(phone):
    try:
        with open(os.path.join(CARDS_DIR, f"{phone}.maps")) as f:
            return f.read().strip()
    except OSError:
        return ""


def _save_maps(phone, link):
    """Remember the host's map pin on disk (like the card style) until the event is created."""
    p = os.path.join(CARDS_DIR, f"{phone}.maps")
    try:
        if link:
            os.makedirs(CARDS_DIR, exist_ok=True)
            with open(p, "w") as f:
                f.write(link)
        elif os.path.exists(p):
            os.remove(p)
    except OSError as e:
        print("ℹ️ Map pin not saved:", e)


def saved_card(phone):
    p = os.path.join(CARDS_DIR, f"{phone}.jpg")
    if CARD_ON and os.path.exists(p):
        with open(p, "rb") as f:
            return _data_uri(f.read())
    return None

# Number guests chat with (your UltraMsg WhatsApp number). Override with BOT_PHONE in .env
BOT_PHONE = os.getenv("BOT_PHONE", "919391695790")


def tap(text):
    """wa.me link: tapping it opens this chat with `text` already typed - the guest just taps Send."""
    return f"https://wa.me/{BOT_PHONE}?text={quote(text)}"


def btn(label, text):
    return f"{label}\n👉 {tap(text)}"

SEEN = set()  # message ids already handled (webhook retries)


def R(to, text, image=None):
    return (to, text, image)


def toint(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


# ───────────────────────── entry point ─────────────────────────
def process(phone, text, mtype="chat", msg_id=""):
    phone = db.norm(phone)
    if msg_id:
        if msg_id in SEEN:
            return []
        SEEN.add(msg_id)
    db.log(msg_id or db.uid("in"), phone, "in", mtype, text)
    replies = handle(phone, (text or "").strip(), mtype)
    for to, body, _ in replies:
        db.log(db.uid("out"), db.norm(to), "out", "chat", body)
    return replies


def handle(phone, t, mtype):
    up = t.upper()
    if registration:
        out = registration.intercept(phone, t)
        if out is not None:
            return out
    if joinlink:
        out = joinlink.intercept(phone, t)
        if out is not None:
            return out
    if up in ("START_EVENT_SETUP", "HOST-EVENT", "HOST EVENT"):
        db.set_session(phone, state="ask_name", organizer_name="", event_name="",
                       date_venue="", invitation_text="", pending_guests="{}")
        return [R(phone, WELCOME)]
    sess = db.get_session(phone)
    if sess.get("state", "idle") != "idle":
        return wizard(phone, t, mtype, sess)
    if is_organizer(phone):
        out = organizer_commands(phone, t)
        if out is not None:
            return out
    return guest(phone, t)


# ───────────────────────── organizer wizard ─────────────────────────
WELCOME = """✨ *Welcome to EventAgent* ✨
Let's set up your event and invite your guests — right here on WhatsApp. 🙌

It takes just *4 quick steps*. (Type *CANCEL* anytime to stop.)

━━━━━━━━━━━━━━
👤 *Step 1 of 4*
What's your *name*?
_This is the host name shown on the invitation — e.g. Ramesh Kumar_"""

PIN_STEP = os.getenv("VENUE_PIN_STEP", "1") == "1"     # 1 = ask for the (optional) map pin after the venue name
PIN_ASK = ("📍 *Step 4 of 4 — map pin* _(optional, guests love it)_\n"
           "Share the *exact location* so every guest gets one-tap directions:\n"
           "📎 *Attach* ➔ *Location* ➔ pick the venue\n"
           "_Or paste a Google Maps link (Maps app ➔ Share ➔ Copy link)._\n\n"
           "Type *SKIP* to continue without it.")
BAD_PIN = ("😅 I couldn't read that location pin. Please paste a *Google Maps link* instead "
           "(Maps app ➔ Share ➔ Copy link), or type *SKIP*.")
ASK = {
    "ask_name": "👤 *Step 1 of 4*\nWhat's your *name*?\n_This is the host name shown on the invitation — e.g. Ramesh Kumar_",
    "ask_event": "🎉 *Step 2 of 4*\nWhat's the *event name*?\n_e.g. Batukamma Celebrations 2026_",
    "ask_date": "📅 *Step 3 of 4*\nWhen is it? Send the *date & time*.\n_e.g. 18 Oct 2026, 5:00 PM  •  tomorrow 5pm  •  next Saturday 6pm_",
    "ask_venue": "📍 *Step 4 of 4*\nWhere is it? Send the *venue name*.\n_e.g. TA Community Hall, Hyderabad_\n\n"
                 "💡 _Or share the venue's 📍 location pin directly (📎 ➔ Location)._",
    "ask_pin": PIN_ASK,
}
DATE_CONFIRM = ("🗓️ *Please confirm the date & time:*\n\n📅 *{when}*\n\nIs this correct?\n"
                "1️⃣  ✅ Yes, correct\n2️⃣  ✏️ No, change it\n\n_(Type *BACK* to go to the previous step)_")
NEXT = {"ask_name": "ask_event", "ask_event": "ask_date", "ask_date": "ask_venue", "ask_venue": None}
FIELD = {"ask_name": "name", "ask_event": "event", "ask_date": "date", "ask_venue": "venue"}
EDIT_MENU = {"1": "name", "name": "name", "2": "event", "event": "event",
             "3": "date", "date": "date", "time": "date", "4": "venue", "venue": "venue"}
EDIT_ASK = {"name": "👤 Send the new *name*:", "event": "🎉 Send the new *event name*:",
            "date": "📅 Send the new *date & time*:\n_e.g. 18 Oct 2026, 5:00 PM  •  tomorrow 5pm_", "venue": "📍 Send the new *venue name*, or share a *📍 location pin* / Google Maps link.\n_(Typing a new name clears the old map pin.)_"}


STYLE_ROWS = [("classic", "🌸 Classic Floral"), ("festival", "🪔 Festival"), ("party", "🎈 Party / Birthday"),
              ("house", "🏠 New Home"), ("islamic", "🌙 Islamic / Eid / Nikah"), ("mandala", "🕉️ Hindu / Mandala"),
              ("royal", "👑 Royal Navy & Gold"),
              ("floral", "🌸 Watercolor Floral"), ("goldcorner", "✨ Gold Corners"), ("navygold", "💙 Navy & Gold"),
              ("goldwash", "🌼 Golden Watercolor"), ("arch", "💜 Floral Arch"), ("peach", "🍑 Peach Bloom"),
              ("toran", "🏵️ Marigold Toran")]
NUMS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟", "1️⃣1️⃣", "1️⃣2️⃣", "1️⃣3️⃣", "1️⃣4️⃣"]
STYLE_MENU = ("🎨 *Choose your card style*\n\n"
              + "\n".join(f"{NUMS[i]} {lab}" for i, (_, lab) in enumerate(STYLE_ROWS))
              + "\n0️⃣ ✨ Automatic (matches your event name)\n\nReply with a number.")


def show_gallery(phone, d):
    """After the details: show several card designs for this event type and let the host pick one."""
    if not (CARD_ON and invite_card):
        return show_preview(phone, d)
    keys = invite_card.suggestions(d["event"])
    best = invite_card.resolve_style(d["event"], None)
    out = [R(phone, "🎨 *Choose your invitation card!*\nI made these designs for *" + d["event"]
                    + "* — tap the one you love 👇")]
    shown = []
    for i, k in enumerate(keys):
        try:
            jpeg = invite_card.make_card(d["name"], d["event"], d["date"], d.get("venue", ""), k)
        except Exception as e:                       # e.g. Telugu text -> text-only preview
            print("ℹ️ Gallery not made:", e)
            return show_preview(phone, d)
        shown.append(k)
        tag = "  ⭐ _Recommended_" if k == best else ""
        out.append(R(phone, f"{NUMS[i]} *{invite_card.style_label(k)}*{tag}\n"
                            + btn("✅ Choose this card", str(i + 1)), _data_uri(jpeg)))
    d["gallery"] = shown
    db.set_session(phone, state="awaiting_card_pick", pending_guests=json.dumps(d))
    out.append(R(phone, f"Reply *1-{len(shown)}* to pick your card. 🎉\n_(You can change it again at the next step.)_"))
    return out


def parse_details(t):
    d = {}
    for line in t.splitlines():
        m = re.match(r"\s*(name|event|date\s*(?:&|and)?\s*time|date|venue)\s*[:\-]\s*(.+)", line, re.I)
        if m:
            key = m.group(1).lower()
            key = "date" if key.startswith("date") else key
            d[key] = m.group(2).strip()
    return d


def build_invitation(name, event, date, venue, maps=""):
    txt = f"*{name}* warmly invites you & your family to *{event}*! 🎉\n📅 *Date & Time:* {date}\n"
    if venue:
        txt += f"📍 *Venue:* {venue}\n"
    if maps:
        txt += f"🗺️ *Map:* {maps}\n"
    return txt + "\nYour presence will make our celebration complete! 🌼"


def show_preview(phone, d):
    text = build_invitation(d["name"], d["event"], d["date"], d.get("venue", ""), d.get("maps", ""))
    _save_maps(phone, d.get("maps", ""))
    date_venue = d["date"] + (f", {d['venue']}" if d.get("venue") else "")
    db.set_session(phone, state="awaiting_approval", organizer_name=d["name"], event_name=d["event"],
                   date_venue=date_venue, invitation_text=text, pending_guests=json.dumps(d))
    card = make_card_for(phone, d)
    style_line = f"🎨 Card style: *{invite_card.style_label(saved_style(phone))}*\n\n" if card and saved_style(phone) else ""
    style_opt = "3️⃣  🎨 *Change card style*\n" if card else ""
    ok_opt = "create my invite link" if (joinlink and joinlink.ENABLED) else "add my guests"
    return [R(phone, f"🪄 *Invitation Preview*\n━━━━━━━━━━━━━━\n{text}\n━━━━━━━━━━━━━━\n\n{style_line}"
                     "Is everything correct?\n\n"
                     f"1️⃣  ✅ *Looks great* — {ok_opt}\n"
                     "2️⃣  ✏️ *Edit* — change something\n" + style_opt, card)]


YES_WORDS = ("1", "1️⃣", "yes", "y", "yeah", "yep", "ok", "okay", "correct", "right", "sure", "confirm", "avunu", "sare")
NO_WORDS = ("2", "2️⃣", "no", "n", "nope", "wrong", "change", "edit", "kadu", "not correct")
BACK_OF = {"ask_event": "ask_name", "ask_date": "ask_event", "confirm_date": "ask_date",
           "ask_venue": "ask_date", "ask_pin": "ask_venue", "awaiting_card_pick": "ask_venue"}


def _ask_with_current(state, d):
    """The question, plus the answer given earlier (after BACK) so the host can just type KEEP."""
    cur = d.get(FIELD.get(state, ""), "")
    return ASK[state] + (f"\n\n_Current: *{cur}*  —  type a new one, or *KEEP* to keep it._" if cur else "")


def _wrong(phone, d, tag, err, ask):
    """Wrong answer: say why, ask the SAME question again, and after 3 misses offer extra help."""
    n = checks.bump(d, tag)
    db.set_session(phone, pending_guests=json.dumps(d))
    return [R(phone, f"⚠️ {err}\n\n{ask}{checks.retry_hint(n)}")]


def go_back(phone, state, s):
    """BACK = previous question. Returns replies, or None if BACK means nothing in this state."""
    d = json.loads(s.get("pending_guests") or "{}")
    if state == "awaiting_details":
        state = "ask_name"
    if state == "ask_name":
        return [R(phone, "You're already at the first step 🙂 Just type your name, or *CANCEL* to stop.")]
    if state in BACK_OF:
        prev = BACK_OF[state]
        for k in ("_tries", "_date_pending", "_date_long"):
            d.pop(k, None)
        if state == "awaiting_card_pick":
            d.pop("gallery", None)
        db.set_session(phone, state=prev, pending_guests=json.dumps(d))
        return [R(phone, "↩️ Going back.\n\n" + _ask_with_current(prev, d))]
    if state == "awaiting_edit_field" or state.startswith("edit_"):
        d.pop("_tries", None)
        return show_preview(phone, d)
    return None


def _after_venue(phone, d, note=""):
    """Venue name is saved -> ask for the (optional) map pin, unless we already have it."""
    if d.get("maps") or not PIN_STEP:
        d.pop("_pin_addr", None)
        out = show_gallery(phone, d)
        return ([R(phone, note)] + out) if note else out
    db.set_session(phone, state="ask_pin", pending_guests=json.dumps(d))
    return [R(phone, ASK["ask_pin"])]


def _venue_pin(phone, d, pin):
    """Host shared a pin at the venue question."""
    d["maps"] = pin["link"]
    d.pop("_tries", None)
    v, err = checks.venue(geo.venue_text(pin)) if pin.get("name") else (None, "no name")
    if not err:                                   # a picked place comes with its own name
        d["venue"] = v
        return _after_venue(phone, d, note="📍 Location pin saved ✅")
    db.set_session(phone, state="ask_venue", pending_guests=json.dumps(d))
    return [R(phone, "📍 Got your location pin ✅\n\nNow type the *venue name* the way guests should see it.\n"
                     "_e.g. TA Community Hall, Hyderabad_")]


def wizard(phone, t, mtype, s):
    state, up = s["state"], t.upper()
    if up == "CANCEL":
        db.set_session(phone, state="idle", pending_guests="")
        return [R(phone, "Setup cancelled. Send *START_EVENT_SETUP* anytime to begin again.")]
    if up == "BACK":
        out = go_back(phone, state, s)
        if out is not None:
            return out

    if mtype == "location" and state in ("ask_venue", "ask_pin", "edit_venue") and not geo.parse(t):
        return [R(phone, BAD_PIN + "\n\n" + (ASK.get(state) or EDIT_ASK["venue"]))]

    if state == "ask_venue" and geo.parse(t):     # 📍 pin / Google Maps link instead of typing the venue
        return _venue_pin(phone, json.loads(s.get("pending_guests") or "{}"), geo.parse(t))

    if state == "ask_pin":
        d = json.loads(s.get("pending_guests") or "{}")
        pin = geo.parse(t)
        if pin:
            d["maps"] = pin["link"]
            d.pop("_tries", None)
            return _after_venue(phone, d, note="✅ Map pin saved! Every guest gets one-tap directions. 📍")
        if up.strip() in ("SKIP", "NO", "NONE", "LATER"):
            d.pop("_tries", None)
            d.pop("maps", None)
            return show_gallery(phone, d)
        return _wrong(phone, d, "ask_pin", "I need a *location pin* or a *Google Maps link* 🙏 (or type *SKIP*).", ASK["ask_pin"])

    if state in ("ask_name", "ask_event", "ask_date", "ask_venue", "awaiting_details"):
        full = parse_details(t)                       # power users can still paste everything at once
        if all(k in full for k in ("name", "event", "date", "venue")):
            good, bad = {}, None
            for k in ("name", "event", "date", "venue"):
                v, err = checks.CHECK[k](full[k])
                if err:
                    bad = bad or (k, err)
                else:
                    good[k] = v
            if not bad:
                return _after_venue(phone, good)
            back = {v: k for k, v in FIELD.items()}[bad[0]]          # ask only the wrong one again
            db.set_session(phone, state=back, pending_guests=json.dumps(good))
            return [R(phone, f"⚠️ {bad[1]}\n\n{ASK[back]}")]
        if state == "awaiting_details":
            state = "ask_name"
        d = json.loads(s.get("pending_guests") or "{}")
        key = FIELD[state]
        keep = up == "KEEP" and bool(d.get(key))      # after BACK: keep the earlier answer
        value, err = (d[key], None) if keep else checks.CHECK[key](t)   # STRICT: wrong -> same question again
        if err:
            return _wrong(phone, d, state, err, _ask_with_current(state, d))
        d.pop("_tries", None)
        if key == "date" and not keep:                # smart date: ALWAYS confirm what the bot understood
            dt, _ = checks.smart_when(t)
            d["_date_pending"], d["_date_long"] = value, checks.fmt_long(dt)
            db.set_session(phone, state="confirm_date", pending_guests=json.dumps(d))
            return [R(phone, DATE_CONFIRM.format(when=d["_date_long"]))]
        d[key] = value
        nxt = NEXT[state]
        if nxt:
            db.set_session(phone, state=nxt, pending_guests=json.dumps(d))
            return [R(phone, f"✅ Got it!\n\n{_ask_with_current(nxt, d)}")]
        return _after_venue(phone, d)

    if state == "confirm_date":
        d = json.loads(s.get("pending_guests") or "{}")
        low = t.strip().lower()
        if not d.get("_date_pending"):                # lost state -> just ask again
            db.set_session(phone, state="ask_date", pending_guests=json.dumps(d))
            return [R(phone, ASK["ask_date"])]
        if low in YES_WORDS:
            d["date"] = d.pop("_date_pending")
            d.pop("_date_long", None), d.pop("_tries", None)
            db.set_session(phone, state="ask_venue", pending_guests=json.dumps(d))
            return [R(phone, f"✅ Date saved!\n\n{_ask_with_current('ask_venue', d)}")]
        if low in NO_WORDS:
            d.pop("_date_pending", None), d.pop("_date_long", None), d.pop("_tries", None)
            db.set_session(phone, state="ask_date", pending_guests=json.dumps(d))
            return [R(phone, "No problem 🙂 Let's try again.\n\n" + _ask_with_current("ask_date", d))]
        return _wrong(phone, d, "confirm_date", "Please reply *1* (Yes, correct) or *2* (No, change it).",
                      DATE_CONFIRM.format(when=d.get("_date_long", "")))

    if state == "awaiting_approval":
        low = t.strip().lower()
        if choice(t) == 1 or low in ("done", "good", "great", "looks good"):
            db.set_session(phone, state="awaiting_guests", pending_guests="[]")
            return [R(phone, "🎉 Now let's add your *guest list*.\n\n"
                             "📇 *Share contacts* — tap 📎 ➔ *Contact* (as many as you like)\n"
                             "⌨️ *Or type them* — e.g. Suresh - 9876543210\n\n"
                             "When you're done, reply *SEND* to deliver every invitation! 🚀")]
        if choice(t) == 2 or low.startswith(("edit", "change")):
            d = json.loads(s.get("pending_guests") or "{}")
            db.set_session(phone, state="awaiting_edit_field")
            return [R(phone, "✏️ *What would you like to change?*\n\n"
                             f"1️⃣ 👤 Name — _{d.get('name', '')}_\n"
                             f"2️⃣ 🎉 Event — _{d.get('event', '')}_\n"
                             f"3️⃣ 📅 Date & time — _{d.get('date', '')}_\n"
                             f"4️⃣ 📍 Venue — _{d.get('venue') or 'not set'}_\n\n"
                             "Reply with a number (1-4).")]
        if (t.strip() == "3" or low.startswith(("style", "card", "design", "theme"))) and invite_card and CARD_ON:
            db.set_session(phone, state="awaiting_style")
            return [R(phone, STYLE_MENU)]
        return [R(phone, "Please reply *1* to continue or *2* to edit.")]

    if state == "awaiting_card_pick":
        d = json.loads(s.get("pending_guests") or "{}")
        keys = d.get("gallery") or []
        pick = re.sub(r"[^a-z0-9]", "", t.lower())
        if pick in ("0", "auto", "skip", "automatic"):
            idx = 0
        elif pick.isdigit() and 1 <= int(pick) <= len(keys):
            idx = int(pick) - 1
        else:
            idx = next((i for i, k in enumerate(keys) if pick and pick in re.sub(r"[^a-z0-9]", "", invite_card.style_label(k).lower())), None)
            if idx is None:
                return [R(phone, f"Please reply with a number from *1* to *{len(keys)}* to pick your card 🎨")]
        d.pop("gallery", None)
        d["style"] = keys[idx]
        return show_preview(phone, d)

    if state == "awaiting_style":
        keys = ["auto"] + [k for k, _ in STYLE_ROWS]
        pick = re.sub(r"[^a-z0-9]", "", t.lower())
        names = {"auto": 0, "automatic": 0, "floral": 1, "birthday": 3, "home": 4, "newhome": 4, "eid": 5,
                 "nikah": 5, "muslim": 5, "hindu": 6, "royal": 7, "navy": 7}
        names.update({k: i + 1 for i, (k, _) in enumerate(STYLE_ROWS)})
        idx = int(pick) if pick.isdigit() and int(pick) < len(keys) else names.get(pick)
        if idx is None:
            return [R(phone, f"Please reply with a number from *0* to *{len(STYLE_ROWS)}*.\n\n" + STYLE_MENU)]
        d = json.loads(s.get("pending_guests") or "{}")
        if keys[idx] == "auto":
            d.pop("style", None)
        else:
            d["style"] = keys[idx]
        return show_preview(phone, d)

    if state == "awaiting_edit_field":
        field = EDIT_MENU.get(re.sub(r"[^a-z0-9]", "", t.lower().split(" ")[0]) if t.strip() else "")
        if not field:
            return [R(phone, "Please reply with a number from *1* to *4*.")]
        db.set_session(phone, state=f"edit_{field}")
        return [R(phone, EDIT_ASK[field])]

    if state.startswith("edit_"):
        field = state[5:]
        d = json.loads(s.get("pending_guests") or "{}")
        pin = geo.parse(t) if field == "venue" else None
        if pin:                                       # new 📍 pin / Maps link for the venue
            d["maps"] = pin["link"]
            d.pop("_tries", None)
            v, err = checks.venue(geo.venue_text(pin)) if pin.get("name") else (None, "no name")
            if not err:
                d["venue"] = v
            return [R(phone, "📍 Map pin updated ✅")] + show_preview(phone, d)
        value, err = checks.CHECK[field](t)           # STRICT here too
        if err:
            return _wrong(phone, d, state, err, EDIT_ASK[field])
        d.pop("_tries", None)
        d[field] = value
        note = ""
        if field == "venue" and d.pop("maps", None):
            note = ("ℹ️ The old map pin was cleared because the venue changed. "
                    "Choose *Edit ➔ Venue* and share a location pin to add a new one.")
        out = show_preview(phone, d)
        return ([R(phone, note)] + out) if note else out

    if state == "awaiting_guests":
        guests = json.loads(s.get("pending_guests") or "[]")
        if up == "SEND":
            if not guests:
                return [R(phone, "Your list is empty. Share a contact or type: Suresh - 9876543210")]
            return dispatch(phone, s, guests)
        new = parse_contacts(t, mtype)
        if not new:
            return [R(phone, "I couldn't find a phone number 🙏 Share a contact card or type: Suresh - 9876543210")]
        known = {g["phone"] for g in guests}
        added = [g for g in new if g["phone"] not in known]
        if not added:
            return [R(phone, f"Those contacts are already on your list. Total: *{len(guests)}* guests.")]
        guests += added
        db.set_session(phone, pending_guests=json.dumps(guests))
        what = f"*{added[0]['name']}* ({added[0]['phone']})" if len(added) == 1 else f"{len(added)} contacts"
        return [R(phone, f"✅ {what} added. Total list: *{len(guests)}* guests.\n"
                         "Send *SEND* to invite everyone! 🚀")]
    db.set_session(phone, state="idle")
    return [R(phone, "Send *START_EVENT_SETUP* to begin.")]


def parse_contacts(t, mtype):
    out = []
    if "BEGIN:VCARD" in t.upper():
        for card in re.findall(r"BEGIN:VCARD.*?END:VCARD", t, re.S | re.I):
            n = re.search(r"FN:(.+?)(?=\s+(?:TEL|ORG|EMAIL|ITEM|X-|END)|[\r\n]|$)", card)
            p = re.search(r"waid=(\d+)", card) or re.search(r"TEL[^:]*:([+\d\s\-()]+)", card)
            phone = db.norm(p.group(1)) if p else ""
            if len(phone) == 10:
                out.append({"name": (n.group(1).strip() if n else "Guest"), "phone": phone})
        return out
    for line in re.split(r"[\n;]+", t):
        m = re.match(r"^(.*?)[\s\-:,]*(\+?\d[\d\s\-]{8,16}\d)\s*$", line.strip())
        if m and len(db.norm(m.group(2))) == 10:
            out.append({"name": m.group(1).strip() or "Guest", "phone": db.norm(m.group(2))})
    return out


def ensure_customer(phone, name):
    for c in db.rows("Customers"):
        if db.norm(c["phone"]) == phone:
            return c["customer_code"]
    code = db.next_id("CUS", "Customers", "customer_code")
    db.add("Customers", {"customer_code": code, "name": name, "phone": phone,
                         "company": config.DEFAULT_COMPANY, "created_at": db.now()})
    return code


def dispatch(phone, s, guests):
    card = saved_card(phone)                      # invitation card drawn at the preview step (or None)
    cust = ensure_customer(phone, s["organizer_name"])
    evt = db.next_id("EVT", "Events", "event_id")
    db.add("Events", {"event_id": evt, "customer_code": cust, "organizer_name": s["organizer_name"],
                      "organizer_phone": phone, "event_name": s["event_name"],
                      "date_venue": s["date_venue"], "invitation_text": s["invitation_text"],
                      "status": "live", "guests_invited": len(guests), "created_at": db.now(),
                      "card_style": saved_style(phone), "maps_link": saved_maps(phone)})
    replies = [R(phone, f"🚀 Delivering invitations to *{len(guests)}* guests… hang tight!")]
    for g in guests:
        db.add("Guests", {"guest_id": db.uid("G"), "event_id": evt, "organizer_phone": phone,
                          "contact_name": g["name"], "contact_phone": g["phone"],
                          "invite_status": "sent", "conversation_state": "invited",
                          "adults": 0, "children": 0, "invited_at": db.now(), "last_update": db.now()})
        replies.append(R(g["phone"], s["invitation_text"] + RSVP_OPTIONS, config.INVITE_IMAGE_URL or card or None))
    db.set_session(phone, state="idle", pending_guests="", organizer_name="", event_name="",
                   date_venue="", invitation_text="")
    replies.append(R(phone, f"🚀 Invitations were successfully sent to your *{len(guests)}* guests!\n\n"
                            "RSVPs and family registrations update automatically. ✨\n"
                            "📊 Reply *STATUS* anytime for a live summary."))
    return replies


RSVP_OPTIONS = ("\n\n━━━━━━━━━━━━━━\n*Will you attend?* 👇 Just tap one:\n\n"
                + btn("✅ Yes, I'll Attend", "Yes") + "\n\n"
                + btn("🤔 Maybe", "Maybe") + "\n\n"
                + btn("❌ Can't Attend", "No")
                + "\n\n_(or reply 1 / 2 / 3)_")


# ───────────────────────── organizer commands ─────────────────────────
def my_events(phone):
    return [e for e in db.rows("Events") if db.norm(e["organizer_phone"]) == phone]


def is_organizer(phone):
    return bool(my_events(phone))


def organizer_commands(phone, t):
    parts = t.split()
    cmd = parts[0].upper() if parts else ""
    evs = my_events(phone)
    ev = evs[-1]
    if cmd == "STATUS":
        return status(phone, ev)
    if cmd == "CHECKIN" and len(parts) > 1:
        return checkin(phone, evs, parts[1].upper())
    if cmd == "LUCKYDRAW":
        return luckydraw(phone, ev)
    if cmd == "FEEDBACK":
        return ask_feedback(phone, ev)
    return None


def event_guests(ev):
    return [g for g in db.rows("Guests") if g["event_id"] == ev["event_id"]]


def status(phone, ev):
    gs = event_guests(ev)
    n = lambda *s: sum(1 for g in gs if g["invite_status"] in s)
    reg = [g for g in gs if g["invite_status"] == "registered"]
    people = sum(toint(g["adults"]) + toint(g["children"]) for g in reg)
    came = sum(1 for g in gs if g["checkin_status"] == "checked_in")
    return [R(phone, f"📊 *Live RSVP Summary for {ev['event_name']}:*\n"
                     f"• Total Invited: {len(gs)}\n• Accepted (Coming): {n('accepted', 'registered')} 🎉\n"
                     f"• Passes Issued: {len(reg)} 🎟️\n• Declined: {n('declined')}\n"
                     f"• Maybe: {n('maybe')}\n• Pending (Awaiting): {n('sent')}\n"
                     f"• Registered headcount: {people} 👨‍👩‍👧\n• Checked in: {came} 🚪" + meal_summary(reg))]


def meal_summary(reg):
    """'Meals (people): Veg 4, Non-Veg 1, Both 2' - counted by headcount (adults + kids). Empty if nobody chose yet."""
    cnt = {"Veg": 0, "Non-Veg": 0, "Both": 0}
    for g in reg:
        if g.get("meal") in cnt:
            cnt[g["meal"]] += toint(g["adults"]) + toint(g["children"])
    if not any(cnt.values()):
        return ""
    return f"\n• Meals (people): Veg {cnt['Veg']}, Non-Veg {cnt['Non-Veg']}, Both {cnt['Both']} 🍽️"


def checkin(phone, evs, code):
    ids = {e["event_id"] for e in evs}
    for g in db.rows("Guests"):
        if g["event_id"] in ids and g["qr_code"].upper() == code:
            if g["checkin_status"] == "checked_in":
                return [R(phone, f"ℹ️ *{g['contact_name']}* ({code}) is already checked in.")]
            db.update("Guests", "guest_id", g["guest_id"],
                      {"checkin_status": "checked_in", "checkin_time": db.now(),
                       "lucky_draw": "eligible", "last_update": db.now()})
            return [R(phone, f"✅ Checked in: *{g['contact_name']}* — {toint(g['adults']) + toint(g['children'])} people.\n🎁 Lucky Draw eligible!")]
    return [R(phone, f"❌ No pass found with code *{code}*.")]


def luckydraw(phone, ev):
    pool = [g for g in event_guests(ev) if g["lucky_draw"] == "eligible"]
    if not pool:
        return [R(phone, "No eligible guests yet — check guests in first with *CHECKIN <pass no>*.")]
    w = random.choice(pool)
    db.update("Guests", "guest_id", w["guest_id"], {"lucky_draw": "winner", "last_update": db.now()})
    return [R(phone, f"🎁 *Lucky Draw Winner!*\n🏆 {w['contact_name']} ({w['contact_phone']})\n🎫 Pass: {w['qr_code']}"),
            R(w["contact_phone"], f"🎉🎁 *Congratulations {w['contact_name']}!* You won the Lucky Draw at *{ev['event_name']}*! "
                                  "Please meet the organizers to collect your prize. 🏆")]


def ask_feedback(phone, ev):
    out, n = [], 0
    for g in event_guests(ev):
        if g["checkin_status"] == "checked_in":
            db.update("Guests", "guest_id", g["guest_id"], {"conversation_state": "feedback_asked"})
            out.append(R(g["contact_phone"], f"Thank you for joining *{ev['event_name']}*! 🙏\n"
                                             "How was it? 👇 Tap a rating:\n\n"
                                             + btn("⭐⭐⭐⭐⭐ Loved it!", "5 Loved it!") + "\n\n"
                                             + btn("⭐⭐⭐⭐ Great", "4 Great") + "\n\n"
                                             + btn("⭐⭐⭐ Good", "3 Good") + "\n\n"
                                             + btn("⭐⭐ Could be better", "2 Could be better") + "\n\n"
                                             "_(or reply 1-5 with a comment)_"))
            n += 1
    return [R(phone, f"📨 Feedback request sent to *{n}* checked-in guests.")] + out


# ───────────────────────── guest chatbot ─────────────────────────
WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
         "eight": 8, "nine": 9, "ten": 10}
NUM = r"(\d+|" + "|".join(WORDS) + r")"
RELATIVES = r"\b(wife|husband|spouse|partner|mother|mom|mum|father|dad|brother|sister|friends?|grandma|grandpa|uncle|aunt)\b"


def num(x):
    return int(x) if x.isdigit() else WORDS[x]


def parse_attendees(text):
    """'My wife and two kids' -> (2, 2). Returns None when it can't understand."""
    t = text.lower()
    if re.search(r"\b(alone|only me|just me|myself|only i|single)\b", t):
        return 1, 0
    kids = sum(num(m.group(1)) for m in re.finditer(
        NUM + r"\s*(?:little\s*)?(?:kids?|child(?:ren)?|boys?|girls?|sons?|daughters?|babies|baby)\b", t))
    if not kids and re.search(r"\b(kid|child|son|daughter|baby)\b", t):
        kids = 1
    adults = None
    m = re.search(NUM + r"\s*adults?\b", t)
    tot = re.search(NUM + r"\s*(?:members?|people|persons?|of us|pax|total)\b", t) or \
        re.fullmatch(r"\s*" + NUM + r"\s*", t)
    if m:
        adults = num(m.group(1))
    elif tot:
        adults = max(num(tot.group(1)) - kids, 1)
    else:
        rel = len(re.findall(RELATIVES, t))
        if re.search(r"\b(parents|in-laws)\b", t):
            rel += 2
        if rel or kids:
            adults = 1 + rel
    if adults is None or adults + kids > 50:
        return None
    return adults, kids


def choice(t):
    t = t.strip().lower()
    if re.match(r"^(1|y|yes|yeah|yep|sure|ok|okay|confirm|attend|coming)\b", t):
        return 1
    if re.match(r"^(2|maybe|may be|not sure|perhaps)\b", t):
        return 2
    if re.match(r"^(3|n|no|nope|cant|can't|cannot|can not|sorry|not coming|decline)\b", t):
        return 3
    return 0


def find_guest(phone):
    mine = [g for g in db.rows("Guests") if db.norm(g["contact_phone"]) == phone]
    return mine[-1] if mine else None


def event_of(g):
    for e in db.rows("Events"):
        if e["event_id"] == g["event_id"]:
            return e
    return {"event_name": "the event", "date_venue": ""}


def pass_code(ev):
    word = re.sub("[^A-Za-z]", "", (ev["event_name"].split() or [""])[0]).upper()
    cons = word[:1] + "".join(c for c in word[1:] if c not in "AEIOU")   # Batukamma -> BTK
    tag = cons[:3] if len(cons) >= 3 else (word[:3] or "EVT")
    prefix = f"{config.PASS_PREFIX}-{tag}-"
    used = [toint(g["qr_code"][len(prefix):]) for g in db.rows("Guests") if g["qr_code"].startswith(prefix)]
    return f"{prefix}{(max(used) if used else 0) + 1:05d}"


HELP = ("You can ask me:\n• *Where can I park?*\n• *What time does it start?*\n• *What's today's programme?*\n"
        "• *Show my pass*\n• *Directions* / *Add to calendar*\n• *Can I bring another guest?*")


def pass_msg(phone, g, ev):
    total = toint(g["adults"]) + toint(g["children"])
    meal = g.get("meal") or ""
    # QR = wa.me link with "CHECKIN <pass>" pre-typed: gate team scans it, taps Send, done.
    gate_link = tap("CHECKIN " + g["qr_code"])
    save_qr_png(g["qr_code"], gate_link)
    img = None
    if pass_card and CARD_ON:                        # beautiful ticket pass (same style as the invitation card)
        try:
            venue = extras.venue_of(ev)
            style = ev.get("card_style") or None
            jpeg = pass_card.make_pass(g["contact_name"], ev["event_name"], ev["date_venue"] if not venue else
                                       ev["date_venue"].replace(venue, "").rstrip(" ,|-·@"), venue,
                                       toint(g["adults"]), toint(g["children"]), g["qr_code"], gate_link, meal, style)
            img = _data_uri(jpeg)
            
            with open(
                os.path.join(
                    config.PASSES_DIR,
                    re.sub(r"[^A-Za-z0-9_-]", "_", g["qr_code"]) + ".jpg"
                ),
                "wb"
            ) as f:
                f.write(jpeg)
        except Exception as e:                       # e.g. Telugu event name -> old plain pass below
            print("ℹ️ Pass card not made, sending the plain pass instead:", e)
    if not img:
        img = "https://api.qrserver.com/v1/create-qr-code/?size=400x400&data=" + quote(gate_link, safe="")
    meal_line = f"🍽️ Meal: *{meal}*\n" if meal else ""
    out = [R(phone, f"🎟️ *Your registration is confirmed!*\n🎫 Pass No: *{g['qr_code']}*\n"
                    f"👥 Total people: *{total}* ({toint(g['adults'])} adults, {toint(g['children'])} kids)\n"
                    f"{meal_line}📅 {ev['date_venue']}\n\nShow this code at the entry gate for quick entry.", img)]
    links = extras.links_text(ev)
    if links:
        out.append(R(phone, links))
    return out


MEAL_ASK = ("🍽️ *One last thing — what would you like to eat?*\n👇 Just tap one:\n\n"
            + btn("🥗 Veg", "Veg") + "\n\n" + btn("🍗 Non-Veg", "Non-Veg") + "\n\n" + btn("🍽️ Both", "Both"))


def meal_choice(t):
    x = re.sub(r"[^a-z0-9]", "", t.lower())
    if x.startswith(("nonveg", "nv")) or x == "2":
        return "Non-Veg"
    if x.startswith(("veg", "pure")) or x == "1":
        return "Veg"
    if x.startswith(("both", "mix", "any")) or x == "3":
        return "Both"
    return ""


def faq_answer(phone, g, ev, low, upd):
    has = lambda *w: any(re.search(r"\b" + x, low) for x in w)
    if has("pass", "qr", "ticket", "code", "registration"):
        return pass_msg(phone, g, ev) if g["qr_code"] else [R(phone, "You haven't registered yet. Reply *1* to RSVP.")]
    if has("meal", "veg", "non-veg", "nonveg", "food preference"):
        upd(conversation_state="awaiting_meal")
        return [R(phone, MEAL_ASK)]
    if has("direction", "map", "navigate", "route"):
        d = extras.maps_url(ev)
        return [R(phone, f"📍 *{ev['event_name']}*\n{extras.venue_of(ev)}\n\n👉 {d}")] if d else None
    if has("calendar", "remind"):
        c = extras.calendar_link(ev)
        return [R(phone, f"📅 *Add to calendar*\n👉 {c}")] if c else [R(phone, f"📅 {ev['date_venue']}")]
    if has("park"):
        return [R(phone, config.FAQ["parking"])]
    if has("programme", "program", "schedule", "agenda", "today"):
        return [R(phone, config.FAQ["programme"])]
    if has("time", "when", "start", "date"):
        return [R(phone, f"🕐 *{ev['event_name']}*\n📅 {ev['date_venue']}")]
    if has("where", "venue", "location", "address"):
        d = extras.maps_url(ev)
        return [R(phone, f"📍 *{ev['event_name']}*\n{ev['date_venue']}" + (f"\n\n📍 *Directions*\n👉 {d}" if d else ""))]
    if has("change", "edit", "bring", "another", "extra"):
        upd(conversation_state="awaiting_family")
        return [R(phone, "Sure! Tell me the new family count — e.g. _My wife and two kids_ or _5 members_.")]
    if has("hi", "hello", "hey", "help", "menu", "namaste"):
        return [R(phone, f"Namaste {g['contact_name']}! 🙏 I'm the digital assistant for *{ev['event_name']}*.\n\n{HELP}")]
    return None


ARRIVED_RE = r"\s*(arrived|i\s*(?:have\s*)?arrived|i'?m\s+here|i\s+am\s+here|reached)\b"


def self_checkin(phone, g, ev):
    """Guest scanned the gate-poster QR (it pre-types ARRIVED). Identified by their WhatsApp number."""
    name = g["contact_name"]
    if g["invite_status"] != "registered":
        if g["conversation_state"] in ("invited", "maybe", "declined", "accepted"):
            return [R(phone, f"Hi {name}! 👋 I couldn't find your pass yet — please register first 👇\n"
                             + btn("✅ Yes, I'll Attend", "Yes") + "\n\nThen scan the gate QR again.")]
        return [R(phone, f"Hi {name}! 👋 You're almost registered — please finish the steps in my last "
                         "message (family count / Confirm), then scan the gate QR again.")]
    if g["checkin_status"] == "checked_in":
        return [R(phone, f"ℹ️ *{name}*, you're already checked in. Enjoy the event! 🎉")]
    db.update("Guests", "guest_id", g["guest_id"],
              {"checkin_status": "checked_in", "checkin_time": db.now(),
               "lucky_draw": "eligible", "last_update": db.now()})
    total = toint(g["adults"]) + toint(g["children"])
    return [R(phone, f"✅ *Welcome, {name}!* You're checked in.\n"
                     f"👥 {total} people · 🎫 {g['qr_code']}\n"
                     "🎁 You're in the Lucky Draw — good luck!\n\nEnjoy the event! 🎉")]


def guest(phone, t):
    g = find_guest(phone)
    if not g:
        return [R(phone, "Hi! 👋 I'm EventAgent. Want to host your own event? "
                         "Send *START_EVENT_SETUP* and I'll set it up right here on WhatsApp.")]
    ev, st, low = event_of(g), g["conversation_state"], t.lower()
    if re.match(ARRIVED_RE, low):
        return self_checkin(phone, g, ev)
    if re.match(r"\s*check-?in\b", low):
        return [R(phone, "🎟️ That QR is meant for our gate team — just show it at the entry gate. See you there! 🙂")]

    def upd(**f):
        f["last_update"] = db.now()
        db.update("Guests", "guest_id", g["guest_id"], f)

    def fallback(msg):
        return faq_answer(phone, g, ev, low, upd) or [R(phone, msg)]

    ask_family = [R(phone, "Wonderful! 🎉 Will you come alone or with family?\n👇 Just tap one:\n\n"
                           + btn("👤 Just me", "Just me") + "\n\n"
                           + btn("👫 2 adults", "2 adults") + "\n\n"
                           + btn("👨‍👩‍👧 2 adults + 1 child", "2 adults 1 kid") + "\n\n"
                           + btn("👨‍👩‍👧‍👦 2 adults + 2 kids", "2 adults 2 kids") + "\n\n"
                           "✍️ Different? Just type it — e.g. _My wife and two kids_ or _6 members_")]

    if st in ("invited", "maybe", "declined"):
        c = choice(t)
        if c == 1:
            upd(invite_status="accepted", conversation_state="awaiting_family", responded_at=db.now())
            return ask_family
        if c == 2:
            upd(invite_status="maybe", conversation_state="maybe", responded_at=db.now())
            return [R(phone, "No worries! 🤔 Tap below anytime when you're sure 👇\n" + btn("✅ Yes, I'll Attend", "Yes"))]
        if c == 3:
            upd(invite_status="declined", conversation_state="declined", responded_at=db.now())
            return [R(phone, "Sorry you can't make it 🙏 Changed your mind? Tap below 👇\n" + btn("✅ Yes, I'll Attend", "Yes"))]
        return fallback("Please reply *1* (Yes), *2* (Maybe) or *3* (Can't attend).")

    if st == "awaiting_family":
        r = parse_attendees(t)
        if r:
            upd(adults=r[0], children=r[1], conversation_state="awaiting_confirm")
            return [R(phone, f"👨‍👩‍👧 We've reserved *{r[0] + r[1]}* places for your family ({r[0]} adults + {r[1]} kids).\n\n"
                             "Tap to finalize 👇\n\n"
                             + btn("✅ Confirm my registration", "Confirm") + "\n\n"
                             + btn("✏️ Change the count", "Change"))]
        return fallback("Sorry, I didn't get the count 🙏 Try: _Alone_, _My wife and two kids_ or _4 members_.")

    if st == "awaiting_confirm":
        c = choice(t)
        if c == 1:
            code = g["qr_code"] or pass_code(ev)
            g["qr_code"] = code
            upd(qr_code=code, invite_status="registered", conversation_state="awaiting_meal")
            return [R(phone, "✅ *You're registered!* 🎉\n\n" + MEAL_ASK)]
        if c == 3 or low.startswith("2") or "change" in low:
            upd(conversation_state="awaiting_family")
            return ask_family
        return fallback("Reply *1* to confirm or *2* to change your family count.")

    if st == "awaiting_meal":
        m = meal_choice(t)
        if m:
            upd(meal=m, conversation_state="registered")
            g["meal"] = m
            return pass_msg(phone, g, ev) + [R(phone, HELP)]
        return fallback("Please tap one 👇\n\n" + MEAL_ASK)

    if st == "feedback_asked":
        m = re.match(r"\s*([1-5])\b\s*(.*)", t, re.S)
        if m:
            upd(rating=int(m.group(1)), feedback=m.group(2).strip(), conversation_state="feedback_done")
            return [R(phone, "Thank you for your feedback! 💛 See you at the next event.")]
        return fallback("Please reply with a rating from *1* to *5*.")

    return fallback(f"I didn't get that 🙏\n\n{HELP}")