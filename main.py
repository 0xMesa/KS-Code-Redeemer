#!/usr/bin/env python3
"""
Kingshot Gift Code Auto-Redeemer
=================================
Pollt regelmäßig neue Gift Codes von kingshot.net und löst sie
automatisch für deinen Account ein.

Setup:
    pip install requests

Konfiguration:
    PLAYER_ID  → deine Ingame-Player-ID (steht unter Avatar → oben links)
    INTERVAL   → wie oft in Minuten auf neue Codes geprüft wird (Standard: 15)

Ausführen:
    python kingshot_autoredeemer.py
"""

import hashlib
import json
import time
import requests
from datetime import datetime
from pathlib import Path

# ─── KONFIGURATION ────────────────────────────────────────────────────────────

PLAYER_ID = "307980766"  # ← hier eintragen!

INTERVAL_MINUTES = 15   # Prüfintervall in Minuten

# ─── INTERNA (nicht ändern nötig) ─────────────────────────────────────────────

LOGIN_URL  = "https://kingshot-giftcode.centurygame.com/api/player"
REDEEM_URL = "https://kingshot-giftcode.centurygame.com/api/gift_code"
CODES_API  = "https://kingshot.net/api/gift-codes"

ENCRYPT_KEY = "mN4!pQs6JrYwV9"

STATE_FILE  = Path(__file__).parent / "seen_codes.json"
LOG_FILE    = Path(__file__).parent / "redeemer.log"

RESULT_MESSAGES = {
    "SUCCESS":            "✅ Erfolgreich eingelöst",
    "RECEIVED":           "⏭️  Bereits eingelöst",
    "SAME TYPE EXCHANGE": "✅ Erfolgreich eingelöst (gleicher Typ)",
    "TIME ERROR":         "⌛ Code abgelaufen",
    "USED":               "🚫 Einlöselimit erreicht",
    "TIMEOUT RETRY":      "🔄 Server-Timeout, nochmal versucht",
}

# ─── HILFSFUNKTIONEN ──────────────────────────────────────────────────────────

def log(msg: str):
    """Schreibt eine Zeile mit Zeitstempel in Konsole und Logdatei."""
    entry = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(entry)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(entry + "\n")


def load_seen_codes() -> set:
    """Lädt bereits gesehene/eingelöste Codes aus der lokalen JSON-Datei."""
    if STATE_FILE.exists():
        try:
            return set(json.loads(STATE_FILE.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()


def save_seen_codes(codes: set):
    """Speichert die gesehenen Codes in der JSON-Datei."""
    STATE_FILE.write_text(json.dumps(sorted(codes)), encoding="utf-8")


def sign_payload(data: dict) -> dict:
    """Signiert den Request-Payload mit MD5 (wie die offizielle Webseite)."""
    sorted_keys = sorted(data.keys())
    encoded = "&".join(
        f"{k}={json.dumps(data[k]) if isinstance(data[k], dict) else data[k]}"
        for k in sorted_keys
    )
    signature = hashlib.md5(f"{encoded}{ENCRYPT_KEY}".encode()).hexdigest()
    return {"sign": signature, **data}


def api_post(url: str, payload: dict, retries: int = 3, retry_delay: int = 3):
    """Sendet einen signierten POST-Request mit automatischem Retry."""
    signed = sign_payload(payload)
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(url, json=signed, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                msg = data.get("msg", "")
                if isinstance(msg, str) and msg.strip(".") == "TIMEOUT RETRY":
                    if attempt < retries:
                        log(f"  ↩ Server fordert Retry (Versuch {attempt}/{retries}) ...")
                        time.sleep(retry_delay)
                        continue
                return data
            log(f"  ⚠ HTTP {resp.status_code} bei Versuch {attempt}")
        except requests.RequestException as e:
            log(f"  ⚠ Netzwerkfehler (Versuch {attempt}): {e}")
        if attempt < retries:
            time.sleep(retry_delay)
    return None

# ─── KERNLOGIK ────────────────────────────────────────────────────────────────

def fetch_active_codes() -> list[str]:
    """Holt aktive Gift Codes von kingshot.net."""
    try:
        resp = requests.get(CODES_API, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        # API gibt Liste von Objekten oder direkt Strings zurück – beide Formate abfangen
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
        log(f"⚠ Codes konnten nicht abgerufen werden: {e}")
        return []


def redeem_code(player_id: str, code: str) -> str:
    """
    Löst einen einzelnen Code für einen Account ein.
    Gibt den rohen Ergebnis-String der API zurück.
    """
    # 1) Login (verifiziert die Player-ID und holt den Nickname)
    login_resp = api_post(LOGIN_URL, {"fid": player_id, "time": int(time.time() * 1000)})
    if not login_resp:
        return "REQUEST_FAILED"
    if login_resp.get("code") != 0:
        log(f"  ✗ Login fehlgeschlagen: {login_resp.get('msg', '?')}")
        return "LOGIN_FAILED"

    nickname = login_resp.get("data", {}).get("nickname", "Unbekannt")
    log(f"  👤 Eingeloggt als: {nickname} ({player_id})")

    # 2) Code einlösen
    redeem_resp = api_post(REDEEM_URL, {
        "fid": player_id,
        "cdk": code,
        "time": int(time.time() * 1000),
    })
    if not redeem_resp:
        return "REQUEST_FAILED"

    return str(redeem_resp.get("msg", "UNKNOWN")).strip(".")


def check_and_redeem():
    """Hauptroutine: neue Codes holen und einlösen."""
    log("🔍 Prüfe auf neue Gift Codes ...")
    seen = load_seen_codes()

    active_codes = fetch_active_codes()
    if not active_codes:
        log("   Keine Codes von der API erhalten.")
        return

    new_codes = [c for c in active_codes if c not in seen]

    if not new_codes:
        log(f"   Keine neuen Codes (bekannt: {len(seen)}, aktiv: {len(active_codes)}).")
        return

    log(f"🎁 {len(new_codes)} neue Code(s) gefunden: {', '.join(new_codes)}")

    for code in new_codes:
        log(f"\n▶ Löse ein: {code}")
        result_raw = redeem_code(PLAYER_ID, code)
        friendly   = RESULT_MESSAGES.get(result_raw, f"Unbekannte Antwort: {result_raw}")
        log(f"  → {friendly}")

        # Code als gesehen markieren (unabhängig vom Ergebnis)
        seen.add(code)
        save_seen_codes(seen)

        time.sleep(1.5)  # kurze Pause zwischen Codes

# ─── EINSTIEGSPUNKT ───────────────────────────────────────────────────────────

def main():
    if PLAYER_ID == "DEINE_PLAYER_ID_HIER":
        print("❌ Bitte trage zuerst deine Player-ID in die Variable PLAYER_ID ein!")
        return

    log("=" * 55)
    log(f"  Kingshot Auto-Redeemer gestartet")
    log(f"  Player-ID : {PLAYER_ID}")
    log(f"  Intervall : alle {INTERVAL_MINUTES} Minuten")
    log("=" * 55)

    while True:
        try:
            check_and_redeem()
        except Exception as e:
            log(f"❌ Unerwarteter Fehler: {e}")

        next_check = datetime.fromtimestamp(time.time() + INTERVAL_MINUTES * 60)
        log(f"\n⏰ Nächste Prüfung um {next_check.strftime('%H:%M:%S')} Uhr\n")
        time.sleep(INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    main()
