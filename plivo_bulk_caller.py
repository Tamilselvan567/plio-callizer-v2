#!/usr/bin/env python3
"""
Plivo Bulk Caller
-----------------
Reads a CSV file with columns: lead_name, phone_number
Triggers the Plivo AgentFlow API for each lead, one by one.

CSV format:
    lead_name,phone_number
    Amrritha,8754079478
    John,9876543210
    ...

Usage:
    python plivo_bulk_caller.py --csv leads.csv [--delay 5] [--dry-run]
"""

import csv
import time
import argparse
import sys
import json
import base64
import urllib.request
import urllib.error
from datetime import datetime

# ─── CONFIG ──────────────────────────────────────────────────────────────────
PLIVO_URL = (
    "https://agentflow.plivo.com/v1/account/MAOTM0NWMZY2YXOWM4YJ"
    "/flow/59df8ab3-6ee1-4cf1-97ec-21608863f189"
)
PLIVO_AUTH_ID    = "MAOTM0NWMZY2YXOWM4YJ"
PLIVO_AUTH_TOKEN = "NmI0ODMzYTAzN2U2NGM4ZGEyMDAxZGFmZGNkNjlm"
DEFAULT_DELAY_SECONDS = 1 # wait between calls to avoid rate-limiting
# ─────────────────────────────────────────────────────────────────────────────


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def trigger_call(lead_name: str, phone_number: str, dry_run: bool) -> dict:
    """Fire the Plivo API for a single lead. Returns result dict."""
    payload = json.dumps({
        "lead_name": lead_name,
        "phone_number": phone_number
    }).encode("utf-8")

    if dry_run:
        log(f"[DRY-RUN] Would call → name={lead_name!r}  phone={phone_number}")
        return {"status": "dry-run", "lead_name": lead_name, "phone_number": phone_number}

    credentials = base64.b64encode(f"{PLIVO_AUTH_ID}:{PLIVO_AUTH_TOKEN}".encode()).decode()
    req = urllib.request.Request(
        PLIVO_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Basic {credentials}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            result = json.loads(body) if body.strip() else {}
            log(f"✅  SUCCESS → {lead_name} ({phone_number})  | HTTP {resp.status}")
            return {"status": "success", "http_status": resp.status,
                    "lead_name": lead_name, "phone_number": phone_number, "response": result}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        log(f"❌  HTTP ERROR {e.code} → {lead_name} ({phone_number}) | {body[:200]}")
        return {"status": "error", "http_status": e.code,
                "lead_name": lead_name, "phone_number": phone_number, "error": body}
    except Exception as e:
        log(f"❌  EXCEPTION → {lead_name} ({phone_number}) | {e}")
        return {"status": "error", "lead_name": lead_name,
                "phone_number": phone_number, "error": str(e)}


def read_leads(csv_path: str) -> list[dict]:
    """Parse CSV; accepts lead_name / phone_number columns (case-insensitive)."""
    leads = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = [h.strip().lower() for h in reader.fieldnames or []]

        # flexible column name matching
        name_col = next((h for h in reader.fieldnames
                         if h.strip().lower() in ("lead_name", "name", "lead name")), None)
        phone_col = next((h for h in reader.fieldnames
                          if h.strip().lower() in ("phone_number", "phone", "mobile",
                                                    "contact", "number")), None)

        if not name_col or not phone_col:
            print(f"ERROR: CSV must have name + phone columns. Found: {reader.fieldnames}")
            sys.exit(1)

        for i, row in enumerate(reader, start=2):        # row 1 = header
            name = row[name_col].strip()
            phone = row[phone_col].strip()
            if not name or not phone:
                log(f"⚠️  Skipping row {i}: empty name or phone")
                continue
            # normalize to E.164: add India country code if missing (10-digit numbers)
            if not phone.startswith("+") and not phone.startswith("91") and len(phone) == 10:
                phone = "91" + phone
            leads.append({"lead_name": name, "phone_number": phone})

    return leads


def main():
    parser = argparse.ArgumentParser(description="Bulk-trigger Plivo calls from a CSV")
    parser.add_argument("--csv",      required=True,  help="Path to leads CSV file")
    parser.add_argument("--delay",    type=float, default=DEFAULT_DELAY_SECONDS,
                        help=f"Seconds to wait between calls (default: {DEFAULT_DELAY_SECONDS})")
    parser.add_argument("--dry-run",  action="store_true",
                        help="Print what would be sent without actually calling the API")
    parser.add_argument("--start-at", type=int, default=1,
                        help="Skip to this row number (1-based) — resume from a failure")
    args = parser.parse_args()

    leads = read_leads(args.csv)
    total = len(leads)

    if total == 0:
        log("No leads found in CSV. Exiting.")
        sys.exit(0)

    log(f"Loaded {total} lead(s) from '{args.csv}'")
    log(f"Delay between calls: {args.delay}s  |  Dry-run: {args.dry_run}")
    log("─" * 60)

    results = []
    success = 0
    failed  = 0

    for idx, lead in enumerate(leads, start=1):
        if idx < args.start_at:
            continue

        log(f"[{idx}/{total}] Triggering → {lead['lead_name']} | {lead['phone_number']}")
        result = trigger_call(lead["lead_name"], lead["phone_number"], args.dry_run)
        results.append(result)

        if result["status"] in ("success", "dry-run"):
            success += 1
        else:
            failed += 1

        # wait between calls (skip delay after the last one)
        if idx < total:
            time.sleep(args.delay)

    # ── Summary ──────────────────────────────────────────────────────────────
    log("─" * 60)
    log(f"Done. ✅ {success} succeeded  ❌ {failed} failed  (total: {total})")

    if failed:
        log("\nFailed leads:")
        for r in results:
            if r["status"] == "error":
                log(f"  • {r['lead_name']} ({r['phone_number']}) → {r.get('error','unknown error')}")

    # save results log
    results_file = f"plivo_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(results_file, "w") as f:
        json.dump(results, f, indent=2)
    log(f"\nFull results saved to: {results_file}")


if __name__ == "__main__":
    main()
