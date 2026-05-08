import argparse
import csv
import json
import os
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone

CSV_FILE = "municipalities_archive_targets.csv"
STATE_FILE = "state.json"
LOG_FILE = "archive_log.csv"

USER_AGENT = "municipality-weekly-wayback-archive/1.0"

LOG_FIELDS = [
    "checked_at_utc",
    "index",
    "prefecture_ja",
    "municipality_ja",
    "target_url",
    "save_url",
    "http_status",
    "result",
    "error",
]

def load_state():
    if not os.path.exists(STATE_FILE):
        return {"next_index": 0}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"next_index": 0}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def append_log(row):
    exists = os.path.exists(LOG_FILE)
    with open(LOG_FILE, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow(row)

def load_targets():
    with open(CSV_FILE, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    targets = []
    for row in rows:
        enabled = str(row.get("enabled", "TRUE")).strip().lower()
        if enabled not in ["true", "1", "yes", "y"]:
            continue

        url = (row.get("url") or "").strip()
        if not url:
            continue

        targets.append({
            "prefecture_ja": row.get("prefecture_ja", ""),
            "municipality_ja": row.get("municipality_ja", ""),
            "url": url,
        })

    return targets

def build_save_url(target_url):
    # web.archive.org/save/ の後ろにURLを置く形式。
    # : / ? & = # はURLとして読めるように残す。
    encoded = urllib.parse.quote(target_url, safe=":/?&=%#")
    return f"https://web.archive.org/save/{encoded}"

def request_wayback(save_url, timeout):
    req = urllib.request.Request(
        save_url,
        headers={"User-Agent": USER_AGENT},
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.getcode(), "OK", ""
    except urllib.error.HTTPError as e:
        code = e.code
        if code in [401, 403, 429]:
            return code, "ACCESS_RESTRICTED_OR_RATE_LIMITED", str(e)[:500]
        if code in [404, 410]:
            return code, "NOT_FOUND", str(e)[:500]
        if 500 <= code <= 599:
            return code, "SERVER_ERROR", str(e)[:500]
        return code, "HTTP_ERROR", str(e)[:500]
    except TimeoutError as e:
        return "", "TIMEOUT", str(e)[:500]
    except Exception as e:
        msg = str(e)
        if "timed out" in msg.lower():
            return "", "TIMEOUT", msg[:500]
        return "", "ERROR", msg[:500]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=int(os.environ.get("BATCH_SIZE", "12")))
    parser.add_argument("--sleep-sec", type=int, default=int(os.environ.get("SLEEP_SEC", "8")))
    parser.add_argument("--timeout-sec", type=int, default=int(os.environ.get("TIMEOUT_SEC", "75")))
    args = parser.parse_args()

    targets = load_targets()
    if not targets:
        raise SystemExit("No enabled targets found.")

    state = load_state()
    next_index = int(state.get("next_index", 0)) % len(targets)

    processed = 0

    for _ in range(args.batch_size):
        index = next_index % len(targets)
        target = targets[index]
        target_url = target["url"]
        save_url = build_save_url(target_url)

        checked_at = datetime.now(timezone.utc).isoformat()

        status, result, error = request_wayback(save_url, timeout=args.timeout_sec)

        append_log({
            "checked_at_utc": checked_at,
            "index": index,
            "prefecture_ja": target["prefecture_ja"],
            "municipality_ja": target["municipality_ja"],
            "target_url": target_url,
            "save_url": save_url,
            "http_status": status,
            "result": result,
            "error": error,
        })

        print(f"[{index}] {target['prefecture_ja']} {target['municipality_ja']} {result} {status} {target_url}")

        next_index = (next_index + 1) % len(targets)
        state["next_index"] = next_index
        save_state(state)

        processed += 1

        # 429が出たら連続送信を避ける。
        if result == "ACCESS_RESTRICTED_OR_RATE_LIMITED" and str(status) == "429":
            print("Rate limited. Stop this run.")
            break

        if processed < args.batch_size:
            time.sleep(args.sleep_sec)

    print(f"Processed: {processed}")
    print(f"Next index: {state['next_index']}")

if __name__ == "__main__":
    main()
