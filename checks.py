"""STRICT answer checks for every question the bot asks.

Each check takes the raw text and returns  (clean_value, None)  when the answer is good,
or  (None, "friendly error message")  when it is not.  The bot must then ask the SAME question again
and must NOT move to the next step.
"""
import re
import unicodedata
from datetime import datetime, timedelta

from dateutil import parser as dparse

# words that are never a real name / event / venue
JUNK = {"hi", "hii", "hello", "hey", "ok", "okay", "yes", "no", "y", "n", "yeah", "nope", "skip", "none",
        "na", "n/a", "nil", "test", "testing", "abc", "xyz", "asdf", "qwerty", "namaste", "help", "menu",
        "start", "send", "done", "confirm", "change", "edit", "status", "null", "nothing", "idk"}

MONTH_RE = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b", re.I)
TIME_RE = re.compile(r"\b\d{1,2}(?:[:.]\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)(?![a-z])|\b(?:[01]?\d|2[0-3]):[0-5]\d\b", re.I)
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")
EMAIL_TYPOS = {"gmial.com": "gmail.com", "gamil.com": "gmail.com", "gmai.com": "gmail.com", "gmail.co": "gmail.com",
               "gmail.con": "gmail.com", "gmail.cm": "gmail.com", "gmaill.com": "gmail.com", "gnail.com": "gmail.com",
               "yahho.com": "yahoo.com", "yaho.com": "yahoo.com", "hotmial.com": "hotmail.com",
               "outlok.com": "outlook.com"}


def _clean(t):
    return " ".join(str(t or "").split())


def _letters(t):
    """Count letters of any language (Telugu / Hindi / English ...)."""
    return sum(1 for c in t if unicodedata.category(c).startswith("L"))


def _only_allowed(t, extra):
    """True if every char is a letter / mark / digit / space or one of `extra` (works for Telugu too)."""
    for c in t:
        cat = unicodedata.category(c)
        if not (cat[0] in "LMN" or c == " " or c in extra):
            return False
    return True


def _mash(t):
    s = re.sub(r"\W", "", t.lower())
    return len(s) >= 3 and len(set(s)) == 1          # 'aaaa', 'xxxx'


def _no_vowel_latin(t):
    """'xyz', 'qwrt' - Latin text with no vowel at all is not a real word."""
    if re.search(r"[^\x00-\x7F]", t):
        return False
    s = re.sub(r"[^a-z]", "", t.lower())
    return bool(s) and not re.search(r"[aeiouy]", s)


# ───────────────────────── checks ─────────────────────────
def name(t):
    t = _clean(t)
    if t.lower() in JUNK or not t:
        return None, "That doesn't look like a *name* 🙏 Please type your real name — e.g. _Ramesh Kumar_"
    if re.search(r"\d", t):
        return None, "A name can't have numbers 🙏 Please type your real name — e.g. _Ramesh Kumar_"
    if not _only_allowed(t, ".'-"):
        return None, "Please use only letters in the name 🙏 (no symbols or emojis)"
    if _letters(t) < 2 or len(t) > 40 or _mash(t) or _no_vowel_latin(t):
        return None, "Please type your *real name* (2-40 letters) 🙏 — e.g. _Ramesh Kumar_"
    return t, None


def event(t):
    t = _clean(t)
    if t.lower() in JUNK or not t:
        return None, "That doesn't look like an *event name* 🙏 e.g. _Batukamma Celebrations 2026_ or _Ravi's Birthday Party_"
    if re.fullmatch(r"[\d\W_]+", t):
        return None, "The event name needs some words, not only numbers 🙏 e.g. _Ravi's Birthday Party_"
    if not _only_allowed(t, ".'-&,()!:#/+"):
        return None, "Please remove special symbols/emojis from the event name 🙏"
    if _letters(t) < 3 or len(t) > 80 or _mash(t) or _no_vowel_latin(t):
        return None, "Please type a proper *event name* (3-80 characters) 🙏 e.g. _Housewarming Ceremony_"
    return t, None


WEEKDAYS = {"mon": 0, "monday": 0, "tue": 1, "tues": 1, "tuesday": 1, "wed": 2, "wednesday": 2,
            "thu": 3, "thur": 3, "thurs": 3, "thursday": 3, "fri": 4, "friday": 4,
            "sat": 5, "saturday": 5, "sun": 6, "sunday": 6}
TIME12 = re.compile(r"\b(\d{1,2})(?:[:.]([0-5]\d))?\s*([ap])\.?m\.?(?![a-z])", re.I)
TIME24 = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
EXAMPLE = "_18 Oct 2026, 5:00 PM_  or  _tomorrow 5pm_  or  _next Saturday 6pm_"


def fmt(dt):
    """datetime -> '18 Dec 2026, 5:00 PM'  (the exact format reminders.py already understands)."""
    h = dt.hour % 12 or 12
    return f"{dt.day} {dt:%b %Y}, {h}:{dt:%M} {'AM' if dt.hour < 12 else 'PM'}"


def fmt_long(dt):
    return f"{dt:%a}, " + fmt(dt)


def _pull_time(t):
    """Find the time in the text. Returns (hour, minute, text_without_time) or None."""
    m = TIME12.search(t)
    if m:
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        if not 1 <= h <= 12:
            return "bad"
        h = h % 12 + (12 if m.group(3).lower() == "p" else 0)
        return h, mi, (t[:m.start()] + " " + t[m.end():])
    m = TIME24.search(t)
    if m:
        return int(m.group(1)), int(m.group(2)), (t[:m.start()] + " " + t[m.end():])
    return None


def smart_when(t, now=None):
    """Natural date+time -> (datetime, None) or (None, error).
    Understands: '18 Oct 2026, 5:00 PM', 'tomorrow 5pm', 'day after tomorrow 7 pm', 'next Saturday 6pm',
    '18/12/2026 5pm' (day first, Indian style), '18 Dec 5pm' (year optional)."""
    now = now or datetime.now()
    t = _clean(t)
    if not t or t.lower() in JUNK:
        return None, f"Please send the *date & time* \U0001F64F e.g. {EXAMPLE}"
    tm = _pull_time(t)
    if tm == "bad":
        return None, "That time doesn't look right \U0001F914 Use e.g. _5:00 PM_ or _17:30_"
    if tm is None:
        return None, f"I need the *time* also \U0001F64F e.g. {EXAMPLE}"
    hour, minute, rest = tm
    low = rest.lower()
    day, explicit_year = None, bool(re.search(r"\b(19|20)\d\d\b", rest))
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if re.search(r"\b(day after tomorrow|overmorrow)\b", low):
        day = today + timedelta(days=2)
    elif re.search(r"\b(tomorrow|tomorow|tommorow|tmrw|tmr)\b", low):
        day = today + timedelta(days=1)
    elif re.search(r"\btoday\b", low):
        day = today
    else:
        wd = re.search(r"\b(next\s+|this\s+|coming\s+)?(" + "|".join(sorted(WEEKDAYS, key=len, reverse=True)) + r")\b", low)
        if wd and not re.search(r"\d", re.sub(r"\b(" + "|".join(WEEKDAYS) + r")\b", "", low)):
            delta = (WEEKDAYS[wd.group(2)] - today.weekday()) % 7
            if delta == 0 and (wd.group(1) or "").strip() == "next":
                delta = 7
            day = today + timedelta(days=delta)
    if day is None:
        if not re.search(r"\d", rest):
            return None, f"I need the *date* also \U0001F64F e.g. {EXAMPLE}"
        try:
            day = dparse.parse(rest, fuzzy=True, dayfirst=True, default=datetime(now.year, 1, 1))
        except (ValueError, OverflowError):
            return None, f"I couldn't understand that date \U0001F914 Please send it like {EXAMPLE}"
    dt = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if dt <= now and not explicit_year and day.year == now.year and not re.search(
            r"\b(tomorrow|today|next|this|coming)\b", low) and day.date() != today.date():
        dt = dt.replace(year=dt.year + 1)           # '5 Jan 5pm' typed in October means next January
    if dt <= now:
        return None, f"That date & time is already in the *past* \U0001F64F Please send a future one, e.g. {EXAMPLE}"
    if dt.year > now.year + 3:
        return None, "That date is too far away \U0001F914 Please check the year and send again."
    return dt, None


def when(t):
    """Wizard check for the date question: returns the date in standard form ('18 Dec 2026, 5:00 PM')."""
    dt, err = smart_when(t)
    return (fmt(dt), None) if not err else (None, err)


def bump(d, tag):
    """Count wrong answers in a row for the SAME question (resets when the question changes)."""
    tr = d.get("_tries") or {}
    n = tr.get("n", 0) + 1 if tr.get("k") == tag else 1
    d["_tries"] = {"k": tag, "n": n}
    return n


def retry_hint(n):
    """After 3 wrong answers in a row the bot offers extra help."""
    if n >= 3:
        return ("\n\n\U0001F4A1 *Need help?* Look at the example above and send just that kind of answer.\n"
                "Type *BACK* to go to the previous step, or *CANCEL* to stop.")
    return ""


def venue(t):
    t = _clean(t)
    if not t or t.lower() in JUNK:
        return None, "The *venue* is required 🙏 Please type where the event is — e.g. _TA Community Hall, Hyderabad_"
    if re.fullmatch(r"[\d\W_]+", t):
        return None, "The venue needs a place name, not only numbers 🙏 e.g. _TA Community Hall, Hyderabad_"
    if not _only_allowed(t, ".'-&,()/#:@+"):
        return None, "Please remove special symbols/emojis from the venue 🙏"
    if _letters(t) < 4 or len(t) > 120 or _mash(t) or _no_vowel_latin(t):
        return None, "Please type a proper *venue / place name* 🙏 e.g. _TA Community Hall, Hyderabad_"
    return t, None


def email(t):
    t = _clean(t).lower()
    if not t or t in JUNK:
        return None, "Your *email address* is required 🙏 e.g. _ramesh@gmail.com_"
    if not EMAIL_RE.match(t):
        return None, "That doesn't look like a valid email 🤔 Please type it again — e.g. _ramesh@gmail.com_"
    dom = t.split("@", 1)[1]
    if dom in EMAIL_TYPOS:
        return None, f"Did you mean *{t.split('@')[0]}@{EMAIL_TYPOS[dom]}*? 🤔 Please type your email again."
    return t, None


CHECK = {"name": name, "event": event, "date": when, "venue": venue, "email": email}