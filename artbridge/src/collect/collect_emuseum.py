"""Collect the full eMuseum Open API list metadata, page by page, into data/raw/ (resumable JSON Lines)."""

import argparse
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote
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


class ApiError(RuntimeError):
    """A list request that failed; the message names the page and the server's reason, never the key."""


# data.go.kr gateway reasons that retrying will not fix (traffic limit, unregistered or expired key, access denied)
FATAL_REASONS = ("LIMITED_NUMBER_OF_SERVICE_REQUESTS", "SERVICE_KEY_IS_NOT_REGISTERED", "DEADLINE_HAS_EXPIRED",
                 "SERVICE_ACCESS_DENIED", "UNREGISTERED_IP")


def error_reason(text: str) -> str:
    """Pull the reason out of an error body (gateway XML, API XML or anything else) without echoing the key."""
    tags = re.findall(r"<(errMsg|returnAuthMsg|returnReasonCode|resultCode|resultMsg)>(.*?)</\1>", text or "", flags=re.S)
    if tags:
        return " ".join(f"{name}={value.strip()}" for name, value in tags)
    return safe_url(" ".join((text or "").split()))[:200]


def parse_page(text: str) -> tuple[int, list[dict]]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        raise ValueError(f"response is not XML: {error_reason(text)}") from None
    code = root.findtext("resultCode") or ""
    if code not in ("", "0", "00", "0000") or root.find("cmmMsgHeader") is not None or root.findtext("totalCount") is None:
        # the data.go.kr gateway reports limits and key problems as <cmmMsgHeader> XML, sometimes with HTTP 200
        raise ValueError(f"API error: {error_reason(text)}")
    items = [{item.attrib.get("key", ""): item.attrib.get("value", "") for item in record if item.attrib.get("key")}
             for record in root.findall("./list/data")]
    return int(root.findtext("totalCount") or 0), items


def saved_ids(path: Path) -> list[str]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as source:
        return [json.loads(line)["id"] for line in source if line.strip()]


def fetch_page(session, key, page, page_size, filters, retries=6):
    """One list page, retried with growing waits (5, 10, 20 ... up to 300 s) unless the reason is fatal."""
    params = {"serviceKey": key, "numOfRows": page_size, "pageNo": page, **(filters or {})}
    for attempt in range(retries + 1):
        try:
            response = session.get(API_URL, params=params, headers={"Accept": "application/xml"}, timeout=60)
            if response.status_code != 200:
                raise ValueError(f"HTTP {response.status_code}: {error_reason(response.text)}")
            return parse_page(response.text)
        except (requests.RequestException, ValueError) as error:
            reason = str(error) if isinstance(error, ValueError) else type(error).__name__
            reason = reason.replace(key, "[redacted]").replace(quote(key, safe=""), "[redacted]")
            if any(fatal in reason for fatal in FATAL_REASONS):
                raise ApiError(f"page {page}: {reason} (retrying will not help; check the key's daily limit or approval on data.go.kr)") from None
            if attempt == retries:
                raise ApiError(f"page {page}: {reason} (failed {retries + 1} times)") from None
            wait = min(5 * 2 ** attempt, 300)
            print(f"page {page}: {reason}; retry {attempt + 1}/{retries} in {wait}s", flush=True)
            time.sleep(wait)


def collect_all(key: str, path: Path, page_size: int = 100, delay: float = 0.2, filters: dict | None = None):
    """Yield each new page's records. Resumes from the saved record count, so the page size may change between runs;
    records already saved are dropped by id."""
    seen_ids = set(ids := saved_ids(path))
    saved = len(ids)
    page = saved // page_size + 1
    if saved:
        print(f"resuming: {saved} records saved; continuing at page {page} of size {page_size}", flush=True)
    session = requests.Session()
    while True:
        total, items = fetch_page(session, key, page, page_size, filters)
        if items and len(items) < page_size and saved + len(items) < total:
            raise ApiError(f"page {page}: asked for {page_size} rows, got {len(items)} before the end ({saved}/{total}); "
                           "the API probably caps the page size - rerun with a smaller --page-size")
        new = [{"_page": page, "_page_size": page_size, **item} for item in items if item.get("id") not in seen_ids]
        seen_ids.update(item.get("id") for item in new)
        # Image URLs are kept exactly as returned: they embed eMuseum's own key, without which the image server
        # answers HTTP 500. data/raw/ is git-ignored; anything printed or committed goes through safe_url.
        yield new
        saved += len(new)
        print(f"page {page}: {saved}/{total}", flush=True)
        if saved >= total or page * page_size >= total:
            return
        if not items:
            raise ApiError(f"page {page}: empty page before the end ({saved}/{total}); rerun to retry")
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
    try:
        count = append_jsonl(collect_all(api_key(), output, args.page_size, args.delay, {"name": args.name} if args.name else None), output)
    except ApiError as error:
        raise SystemExit(f"stopped: {error}; rerun the same command to resume") from None
    print(f"Added {count} records: {output}")
