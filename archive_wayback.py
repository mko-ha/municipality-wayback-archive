import argparse
import csv
import json
import os
import socket
import time
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

JST = timezone(timedelta(hours=9))


def load_json(path, default):
    if not os.path.exists(path):
        return default

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_items(csv_path):
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))

    rows = [r for r in rows if any(c.strip() for c in r)]

    if not rows:
        return []

    # 1行目にURLがなければヘッダー扱い
    start_row = 0
    if not any(c.strip().startswith(("http://", "https://")) for c in rows[0]):
        start_row = 1

    data_rows = rows[start_row:]

    # URL列を自動検出
    url_col = None
    max_cols = max(len(r) for r in data_rows)

    for col in range(max_cols):
        for r in data_rows[:30]:
            if col < len(r) and r[col].strip().startswith(("http://", "https://")):
                url_col = col
                break
        if url_col is not None:
            break

    if url_col is None:
        raise RuntimeError("CSV内にURL列が見つかりません")

    items = []

    for i, r in enumerate(data_rows):
        if url_col >= len(r):
            continue

        url = r[url_col].strip()

        if not url.startswith(("http://", "https://")):
            continue

        labels = []
        for j, cell in enumerate(r):
            if j != url_col and cell.strip():
                labels.append(cell.strip())

        pref = labels[0] if len(labels) >= 1 else ""
        name = labels[1] if len(labels) >= 2 else ""

        items.append(
            {
                "index": i,
                "pref": pref,
                "name": name,
                "url": url,
            }
        )

    return items


def save_to_wayback(url, timeout_sec):
    save_url = "https://web.archive.org/save/" + quote(url, safe=":/?&=%#")

    req = Request(
        save_url,
        headers={
            "User-Agent": "municipality-archive-bot/1.0"
        },
    )

    try:
        with urlopen(req, timeout=timeout_sec) as res:
            return True, f"OK {res.status}"

    except HTTPError as e:
        # 429は「本日既に保存済み」の場合があるため、成功扱いにする
        if e.code in (200, 201, 202, 302, 409, 429):
            return True, f"OK HTTP {e.code}"

        return False, f"HTTP {e.code}"

    except (socket.timeout, TimeoutError):
        return False, "TIMEOUT"

    except URLError as e:
        reason = str(e.reason)

        if "timed out" in reason.lower():
            return False, "TIMEOUT"

        return False, f"URLERROR {reason}"

    except Exception as e:
        return False, f"ERROR {type(e).__name__}: {e}"


def append_log(path, kind, item, result):
    exists = os.path.exists(path)

    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)

        if not exists:
            writer.writerow(
                [
                    "datetime_jst",
                    "kind",
                    "index",
                    "pref",
                    "name",
                    "url",
                    "result",
                ]
            )

        writer.writerow(
            [
                datetime.now(JST).isoformat(timespec="seconds"),
                kind,
                item.get("index", ""),
                item.get("pref", ""),
                item.get("name", ""),
                item.get("url", ""),
                result,
            ]
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="municipalities.csv")
    parser.add_argument("--state", default="state.json")
    parser.add_argument("--failed", default="archive_failed.json")
    parser.add_argument("--log", default="archive_log.csv")
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--sleep-sec", type=int, default=25)
    parser.add_argument("--timeout-sec", type=int, default=180)

    args = parser.parse_args()

    items = load_items(args.csv)

    if not items:
        raise RuntimeError("処理対象URLがありません")

    state = load_json(args.state, {"next_index": 0})
    next_index = int(state.get("next_index", 0))

    if next_index >= len(items):
        next_index = 0

    failed_list = load_json(args.failed, [])

    failed_by_url = {}
    for x in failed_list:
        url = x.get("url")
        if url:
            failed_by_url[url] = x

    retry_items = list(failed_by_url.values())

    # 失敗分だけで詰まらないよう、バッチの半分までを再試行に使う
    if retry_items:
        retry_quota = min(len(retry_items), max(1, args.batch_size // 2))
    else:
        retry_quota = 0

    new_quota = args.batch_size - retry_quota

    batch = []

    for item in retry_items[:retry_quota]:
        batch.append(("RETRY", item))

    new_items = []
    cursor = next_index

    while len(new_items) < new_quota and len(new_items) < len(items):
        new_items.append(items[cursor])
        cursor += 1

        if cursor >= len(items):
            cursor = 0

    for item in new_items:
        batch.append(("NEW", item))

    processed_new = 0

    for n, (kind, item) in enumerate(batch):
        ok, result = save_to_wayback(item["url"], args.timeout_sec)

        print(
            f"[{item.get('index')}] {item.get('pref', '')} {item.get('name', '')} "
            f"{kind} {result} {item.get('url')}"
        )

        append_log(args.log, kind, item, result)

        if ok:
            failed_by_url.pop(item["url"], None)
        else:
            failed_item = failed_by_url.get(item["url"], item)
            failed_item["last_result"] = result
            failed_item["last_attempt_jst"] = datetime.now(JST).isoformat(timespec="seconds")
            failed_item["attempts"] = int(failed_item.get("attempts", 0)) + 1
            failed_by_url[item["url"]] = failed_item

        if kind == "NEW":
            processed_new += 1

        if n < len(batch) - 1:
            time.sleep(args.sleep_sec)

    next_index += processed_new

    while next_index >= len(items):
        next_index -= len(items)

    state["next_index"] = next_index

    save_json(args.state, state)
    save_json(args.failed, list(failed_by_url.values()))

    print(f"Processed: {len(batch)}")
    print(f"Next index: {next_index}")
    print(f"Failed queue: {len(failed_by_url)}")


if __name__ == "__main__":
    main()
