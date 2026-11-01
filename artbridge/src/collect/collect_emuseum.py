"""Collect the full eMuseum Open API list metadata, page by page, into data/raw/ (resumable JSON Lines)."""

import argparse
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

API_URL = "https://apis.data.go.kr/1371027/openapi/list"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = PROJECT_ROOT / "data" / "raw" / "emuseum_list.jsonl"


def load_env_file() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            os.environ.setdefault(key, value)


def api_key() -> str:
    load_env_file()
    key = os.getenv("EMUSEUM_API_KEY")
    if not key:
        raise SystemExit("Set EMUSEUM_API_KEY in artbridge/.env after registering for the eMuseum API at data.go.kr.")
    return key


def safe_url(value: str) -> str:
    """Redact only the serviceKey value; the rest of the URL (e.g. imageId) is kept byte for byte."""
    return re.sub(r"(?i)(servicekey=)[^&#]*", r"\g<1>%5Bredacted%5D", value)


def parse_page(text: str) -> tuple[int, list[dict]]:
    root = ET.fromstring(text)
    code = root.findtext("resultCode") or ""
    if code not in ("", "0", "00", "0000"):
        raise ValueError(f"eMuseum API error {code}: {root.findtext('resultMsg')}")
    items = [{item.attrib.get("key", ""): item.attrib.get("value", "") for item in record if item.attrib.get("key")}
             for record in root.findall("./list/data")]
    return int(root.findtext("totalCount") or 0), items


def last_page(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(encoding="utf-8") as source:
        lines = [line for line in source if line.strip()]
    return json.loads(lines[-1])["_page"] if lines else 0


def collect_all(key: str, start_page: int = 1, page_size: int = 100, delay: float = 0.2, filters: dict | None = None):
    """Yield each page's records as a list; stops at totalCount or the first short page."""
    session = requests.Session()
    page, seen = start_page, (start_page - 1) * page_size
    while True:
        params = {"serviceKey": key, "numOfRows": page_size, "pageNo": page, **(filters or {})}
        response = session.get(API_URL, params=params, headers={"Accept": "application/xml"}, timeout=60)
        response.raise_for_status()
        total, items = parse_page(response.text)
        # Image URLs are kept exactly as returned: they embed eMuseum's own key, without which the image server
        # answers HTTP 500. data/raw/ is git-ignored; anything printed or committed goes through safe_url.
        yield [{"_page": page, **item} for item in items]
        seen += len(items)
        print(f"page {page}: {seen}/{total}", flush=True)
        if not items or len(items) < page_size or seen >= total:
            return
        page += 1
        time.sleep(delay)


def append_jsonl(pages, path: Path) -> int:
    """Append one whole page at a time so an interrupted run resumes at a page boundary."""
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    for records in pages:
        with path.open("a", encoding="utf-8") as output:
            output.write("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records))
        count += len(records)
    return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect all eMuseum list records (API key from artbridge/.env)")
    parser.add_argument("--output", default=str(OUTPUT_PATH))
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--delay", type=float, default=0.2)
    parser.add_argument("--name", help="optional name filter; omit to collect everything")
    args = parser.parse_args()
    output = Path(args.output)
    start = last_page(output) + 1
    if start > 1:
        print(f"Resuming after page {start - 1} (records of that page are already saved)")
    try:
        count = append_jsonl(collect_all(api_key(), start, args.page_size, args.delay, {"name": args.name} if args.name else None), output)
    except requests.RequestException as error:
        status = error.response.status_code if error.response is not None else "network error"
        raise SystemExit(f"eMuseum API request failed ({status}, {type(error).__name__}); details suppressed.") from None
    print(f"Added {count} records: {output}")
