import argparse
import csv
import json
import os
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta


USER_AGENT = "municipality-wayback-archive-bot/1.0"


def now_utc():
    return datetime.now(timezone.utc)


def load_state(path):
    if not os.path.exists(path):
        return {"next_index": 0}

    try:
        with open(path, "r", encoding="utf-8") as f:
            state = json.load(f)

        if not isinstance(state, dict):
            return {"next_index": 0}

        if "next_index" not in state:
            state["next_index"] = 0

        return state

    except Exception:
        return {"next_index": 0}


def save_state(path, state):
    tmp_path = path + ".tmp"

    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    with open(tmp_path, "r", encoding="utf-8") as f:
        json.load(f)

    os.replace(tmp_path, path)


def normalize_url(url):
    url = (url or "").strip()
    if not url:
        return ""

    url = url.split("#", 1)[0].strip()

    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    parsed = urllib.parse.urlsplit(url)

    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"

    if not path.endswith("/") and "." not in path.rsplit("/", 1)[-1]:
        path += "/"

    return urllib.parse.urlunsplit((scheme, netloc, path, "", ""))


def read_targets(csv_path):
    targets = []

    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            url = normalize_url(row.get("url", ""))
            if not url:
                continue

            name = (
                row.get("name")
                or row.get("municipality")
                or row.get("自治体名")
                or row.get("prefecture")
                or ""
            ).strip()

            targets.append({
                "name": name,
                "url": url,
            })

    return targets


def http_get(url, timeout):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
        },
    )

    with urllib.request.urlopen(req, timeout=timeout) as res:
        status = getattr(res, "status", None) or res.getcode()
        body = res.read()
        return status, body


def get_latest_cdx_timestamp(url, timeout):
    params = urllib.parse.urlencode({
        "url": url,
        "output": "json",
        "fl": "timestamp,original,statuscode,mimetype",
        "filter": "statuscode:200",
        "limit": "1",
        "sort": "reverse",
    })

    cdx_url = "https://web.archive.org/cdx/search/cdx?" + params

    try:
        status, body = http_get(cdx_url, timeout)
        if status != 200:
            return None

        data = json.loads(body.decode("utf-8", errors="replace"))

        if not isinstance(data, list) or len(data) < 2:
            return None

        row = data[1]

        if not row:
            return None

        return row[0]

    except Exception:
        return None


def timestamp_to_datetime(ts):
    try:
        return datetime.strptime(ts, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def is_recent_archive(ts, recent_days):
    dt = timestamp_to_datetime(ts)
    if not dt:
        return False

    return dt >= now_utc() - timedelta(days=recent_days)


def save_to_wayback(url, timeout):
    save_url = "https://web.archive.org/save/" + url

    try:
        status, _ = http_get(save_url, timeout)
        return status, None

    except urllib.error.HTTPError as e:
        return e.code, str(e)

    except Exception as e:
        return None, str(e)


def make_batch(targets, start_index, batch_size):
    total = len(targets)
    batch = []

    for i in range(batch_size):
        idx = (start_index + i) % total
        batch.append((idx, targets[idx]))

    return batch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True)
    parser.add_argument("--state", default="state.json")
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--sleep-sec", type=int, default=30)
    parser.add_argument("--timeout-sec", type=int, default=180)
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--recent-days", type=int, default=3)
    args = parser.parse_args()

    targets = read_targets(args.csv)

    if not targets:
        raise RuntimeError("No targets found in CSV")

    state = load_state(args.state)

    total = len(targets)
    next_index = int(state.get("next_index", 0)) % total

    print(f"TOTAL: {total}")
    print(f"START_INDEX: {next_index}")
    print(f"BATCH_SIZE: {args.batch_size}")

    batch = make_batch(targets, next_index, args.batch_size)

    for idx, target in batch:
        name = target["name"]
        url = target["url"]

        label = f"[{idx + 1}/{total}] {name} {url}".strip()
        print(f"START {label}")

        before_ts = get_latest_cdx_timestamp(url, args.timeout_sec)

        if before_ts and is_recent_archive(before_ts, args.recent_days):
            print(f"SKIP_RECENT {label} latest={before_ts}")
            continue

        save_ok = False

        for attempt in range(1, args.max_attempts + 1):
            status, error = save_to_wayback(url, args.timeout_sec)

            if status and 200 <= status < 400:
                print(f"SAVE_REQUEST_OK {label} status={status} attempt={attempt}")
                save_ok = True
                break

            print(f"SAVE_FAILED {label} status={status} attempt={attempt} error={error}")

            if attempt < args.max_attempts:
                time.sleep(args.sleep_sec)

        if not save_ok:
            print(f"GIVE_UP {label}")
            time.sleep(args.sleep_sec)
            continue

        time.sleep(args.sleep_sec)

        after_ts = get_latest_cdx_timestamp(url, args.timeout_sec)

        if after_ts and after_ts != before_ts:
            print(f"ARCHIVED_CONFIRMED {label} latest={after_ts}")
        elif after_ts:
            print(f"PENDING_OR_ALREADY_SAME {label} latest={after_ts}")
        else:
            print(f"PENDING_NOT_REFLECTED {label}")

        time.sleep(args.sleep_sec)

    state["next_index"] = (next_index + args.batch_size) % total
    state["updated_at"] = now_utc().isoformat()

    save_state(args.state, state)

    print(f"NEXT_INDEX: {state['next_index']}")


if __name__ == "__main__":
    main()
