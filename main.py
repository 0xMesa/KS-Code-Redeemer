#!/usr/bin/env python3
"""
Kingshot Gift Code Auto-Redeemer
=================================
Polls kingshot.net for new gift codes and automatically redeems
them for your account.

Setup:
    pip install requests

Configuration:
    PLAYER_ID        -> your in-game Player ID (tap Avatar -> top left)
    INTERVAL_MINUTES -> how often to check for new codes (default: 15)

Run:
    python kingshot_autoredeemer.py
"""

import hashlib
import json
import time
import requests
from datetime import datetime
from pathlib import Path

# ─── CONFIGURATION ────────────────────────────────────────────────────────────

PLAYER_ID = "YOUR_PLAYER_ID_HERE"  # <- enter your Player ID here!

INTERVAL_MINUTES = 15  # Check interval in minutes

# ─── INTERNALS (no changes needed below) ──────────────────────────────────────

LOGIN_URL  = "https://kingshot-giftcode.centurygame.com/api/player"
REDEEM_URL = "https://kingshot-giftcode.centurygame.com/api/gift_code"
CODES_API  = "https://kingshot.net/api/gift-codes"

ENCRYPT_KEY = "mN4!pQs6JrYwV9"

STATE_FILE = Path(__file__).parent / "seen_codes.json"
LOG_FILE   = Path(__file__).parent / "redeemer.log"

RESULT_MESSAGES = {
    "SUCCESS":            "✅ Successfully redeemed",
    "RECEIVED":           "⏭️  Already redeemed",
    "SAME TYPE EXCHANGE": "✅ Successfully redeemed (same type)",
    "TIME ERROR":         "⌛ Code has expired",
    "USED":               "🚫 Claim limit reached",
    "TIMEOUT RETRY":      "🔄 Server timeout, retried",
}

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def log(msg: str):
    """Write a timestamped line to console and log file."""
    entry = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(entry)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(entry + "\n")


def load_seen_codes() -> set:
    """Load previously seen/redeemed codes from local JSON file."""
    if STATE_FILE.exists():
        try:
            return set(json.loads(STATE_FILE.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()


def save_seen_codes(codes: set):
    """Persist the set of seen codes to the local JSON file."""
    STATE_FILE.write_text(json.dumps(sorted(codes)), encoding="utf-8")


def sign_payload(data: dict) -> dict:
    """Sign the request payload with MD5 (mirrors the official website logic)."""
    sorted_keys = sorted(data.keys())
    encoded = "&".join(
        f"{k}={json.dumps(data[k]) if isinstance(data[k], dict) else data[k]}"
        for k in sorted_keys
    )
    signature = hashlib.md5(f"{encoded}{ENCRYPT_KEY}".encode()).hexdigest()
    return {"sign": signature, **data}


def api_post(url: str, payload: dict, retries: int = 3, retry_delay: int = 3):
    """Send a signed POST request with automatic retry on failure."""
    signed = sign_payload(payload)
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(url, json=signed, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                msg = data.get("msg", "")
                if isinstance(msg, str) and msg.strip(".") == "TIMEOUT RETRY":
                    if attempt < retries:
                        log(f"  ↩ Server requested retry (attempt {attempt}/{retries}) ...")
                        time.sleep(retry_delay)
                        continue
                return data
            log(f"  ⚠ HTTP {resp.status_code} on attempt {attempt}")
        except requests.RequestException as e:
            log(f"  ⚠ Network error (attempt {attempt}): {e}")
        if attempt < retries:
            time.sleep(retry_delay)
    return None

# ─── CORE LOGIC ───────────────────────────────────────────────────────────────

def fetch_active_codes() -> list[str]:
    """Fetch active gift codes from kingshot.net."""
    try:
        resp = requests.get(CODES_API, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        # API may return a list of strings or a list of objects — handle both
        codes = []
        for item in data:
            if isinstance(item, str):
                codes.append(item.strip())
            elif isinstance(item, dict):
                code = item.get("code") or item.get("cdkey") or item.get("gift_code")
                if code:
                    codes.append(str(code).strip())
        return codes
    except Exception as e:
        log(f"⚠ Could not fetch codes: {e}")
        return []


def redeem_code(player_id: str, code: str) -> str:
    """
    Redeem a single gift code for one account.
    Returns the raw result string from the API.
    """
    # Step 1: Login (verifies the Player ID and retrieves nickname)
    login_resp = api_post(LOGIN_URL, {"fid": player_id, "time": int(time.time() * 1000)})
    if not login_resp:
        return "REQUEST_FAILED"
    if login_resp.get("code") != 0:
        log(f"  ✗ Login failed: {login_resp.get('msg', '?')}")
        return "LOGIN_FAILED"

    nickname = login_resp.get("data", {}).get("nickname", "Unknown")
    log(f"  👤 Logged in as: {nickname} ({player_id})")

    # Step 2: Redeem the code
    redeem_resp = api_post(REDEEM_URL, {
        "fid": player_id,
        "cdk": code,
        "time": int(time.time() * 1000),
    })
    if not redeem_resp:
        return "REQUEST_FAILED"

    return str(redeem_resp.get("msg", "UNKNOWN")).strip(".")


def check_and_redeem():
    """Main routine: fetch new codes and redeem them."""
    log("🔍 Checking for new gift codes ...")
    seen = load_seen_codes()

    active_codes = fetch_active_codes()
    if not active_codes:
        log("   No codes received from the API.")
        return

    new_codes = [c for c in active_codes if c not in seen]

    if not new_codes:
        log(f"   No new codes (known: {len(seen)}, active: {len(active_codes)}).")
        return

    log(f"🎁 {len(new_codes)} new code(s) found: {', '.join(new_codes)}")

    for code in new_codes:
        log(f"\n▶ Redeeming: {code}")
        result_raw = redeem_code(PLAYER_ID, code)
        friendly   = RESULT_MESSAGES.get(result_raw, f"Unknown response: {result_raw}")
        log(f"  → {friendly}")

        # Mark code as seen regardless of result to avoid retrying failed codes
        seen.add(code)
        save_seen_codes(seen)

        time.sleep(1.5)  # short pause between codes

# ─── ENTRY POINT ──────────────────────────────────────────────────────────────

def main():
    if PLAYER_ID == "YOUR_PLAYER_ID_HERE":
        print("❌ Please set your Player ID in the PLAYER_ID variable first!")
        return

    log("=" * 55)
    log("  Kingshot Auto-Redeemer started")
    log(f"  Player ID : {PLAYER_ID}")
    log(f"  Interval  : every {INTERVAL_MINUTES} minutes")
    log("=" * 55)

    while True:
        try:
            check_and_redeem()
        except Exception as e:
            log(f"❌ Unexpected error: {e}")

        next_check = datetime.fromtimestamp(time.time() + INTERVAL_MINUTES * 60)
        log(f"\n⏰ Next check at {next_check.strftime('%H:%M:%S')}\n")
        time.sleep(INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    main()
