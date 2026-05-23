#!/usr/bin/env python3
"""
kalshi_creds.py — credentials, loaded at runtime. NO key is stored in this file,
so the repo is safe to push (even publicly).

Resolution order:
  KEY_ID : $KALSHI_KEY_ID                              else .secrets/key_id.txt
  PEM    : $KALSHI_PEM (full PEM text)
           else $KALSHI_PEM_PATH (path to a .pem)      else .secrets/kalshi_key.pem

Local  : keep your key in .secrets/ (gitignored) — already set up.
Cloud  : set GitHub repo secrets KALSHI_KEY_ID and KALSHI_PEM (the workflow maps
         them to these env vars).
Demo   : KALSHI_DEMO_KEY_ID / KALSHI_DEMO_PEM(_PATH).
"""
import os
import sys

_DIR = os.path.dirname(os.path.abspath(__file__))
_SECRETS = os.path.join(_DIR, ".secrets")


def _read(path):
    try:
        return open(path).read() if path and os.path.exists(path) else None
    except Exception:
        return None


KEY_ID = (os.environ.get("KALSHI_KEY_ID")
          or _read(os.path.join(_SECRETS, "key_id.txt")) or "").strip()

PEM = (os.environ.get("KALSHI_PEM")
       or _read(os.environ.get("KALSHI_PEM_PATH", ""))
       or _read(os.path.join(_SECRETS, "kalshi_key.pem")) or "")

DEMO_KEY_ID = (os.environ.get("KALSHI_DEMO_KEY_ID") or "").strip()
DEMO_PEM = (os.environ.get("KALSHI_DEMO_PEM")
            or _read(os.environ.get("KALSHI_DEMO_PEM_PATH", "")) or "")

if not KEY_ID or not PEM:
    print("⚠ kalshi_creds: no credentials found. Set KALSHI_KEY_ID + KALSHI_PEM "
          "env vars, or put key_id.txt + kalshi_key.pem in .secrets/.", file=sys.stderr)
