"""All settings in one place. Values come from .env (see .env.example)."""
import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
DATA_DIR = os.path.join(STATIC_DIR, "data")
CARDS_DIR = os.path.join(STATIC_DIR, "cards")
PASSES_DIR = os.path.join(STATIC_DIR, "passes")
QR_DIR = os.path.join(STATIC_DIR, "qrcodes")
POSTERS_DIR = os.path.join(STATIC_DIR, "posters")
PREVIEWS_DIR = os.path.join(STATIC_DIR, "previews")
TEMPLATES_DIR = os.path.join(STATIC_DIR, "templates")
FONTS_DIR = os.path.join(STATIC_DIR, "fonts")
for _d in (DATA_DIR, CARDS_DIR, PASSES_DIR, QR_DIR, POSTERS_DIR, PREVIEWS_DIR, TEMPLATES_DIR, FONTS_DIR):
    os.makedirs(_d, exist_ok=True)

_xl = os.getenv("EXCEL_FILE", "EventAgent.xlsx")
EXCEL_FILE = _xl if os.path.isabs(_xl) else os.path.join(DATA_DIR, os.path.basename(_xl))
ULTRAMSG_INSTANCE = os.getenv("ULTRAMSG_INSTANCE", "")
ULTRAMSG_TOKEN = os.getenv("ULTRAMSG_TOKEN", "")
COUNTRY_CODE = os.getenv("COUNTRY_CODE", "91")
DEFAULT_COMPANY = os.getenv("DEFAULT_COMPANY", "Telugu Association")
PASS_PREFIX = os.getenv("PASS_PREFIX", "TA")          # pass looks like TA-BAT-00001
INVITE_IMAGE_URL = os.getenv("INVITE_IMAGE_URL", "")
GATE_CODE = os.getenv("GATE_CODE", "")                  # secret word printed only in the gate poster QR
REMINDERS = os.getenv("REMINDERS", "1") == "1"
REMIND_MORNING_HOUR = int(os.getenv("REMIND_MORNING_HOUR", "8"))   # 8 = 8 AM on event day
REMIND_HOURS_BEFORE = float(os.getenv("REMIND_HOURS_BEFORE", "2"))  # hours before start
SEND_DELAY = float(os.getenv("SEND_DELAY", "1.5"))     # seconds between bulk messages

# Edit these answers for your event (time/venue come from the event itself)
FAQ = {
    "parking": "🚗 Free parking is available near the venue entrance. Please arrive 15 minutes early.",
    "programme": "🎭 Today's programme: cultural performances, traditional food and a Lucky Draw at the end!",
}