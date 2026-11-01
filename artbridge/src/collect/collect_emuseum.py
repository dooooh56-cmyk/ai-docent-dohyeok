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


class FatalApiError(ApiError):
    """A failure that retrying or smaller pages cannot fix (limits, key problems, capped page size)."""


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
    """One list page, retried with growing waits (5, 10, 20 ... up to 300 s). Fatal reasons stop at once; a request
    the gateway calls invalid is tried only twice, since the caller can split it into smaller pages."""
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
                raise FatalApiError(f"page {page}: {reason} (retrying will not help; check the key's daily limit or approval on data.go.kr)") from None
            limit = 1 if "INVALID_REQUEST_PARAMETER" in reason else retries
            if attempt >= limit:
                raise ApiError(f"page {page} (size {page_size}): {reason} (failed {attempt + 1} times)") from None
            wait = min(5 * 2 ** attempt, 300)
            print(f"page {page} (size {page_size}): {reason}; retry {attempt + 1}/{limit} in {wait}s", flush=True)
            time.sleep(wait)


# This many single rows refused in a row means the query cannot be paged further, not that a few records are bad.
MAX_CONSECUTIVE_GAPS = 20


def partition_name(filters: dict | None) -> str:
    return "_".join(f"{key}-{value}" for key, value in sorted((filters or {}).items()))


def smaller_size(size):
    """Next block size when a block keeps failing: the largest of 100, 10, 1 that divides it."""
    return next(candidate for candidate in (100, 10, 1) if candidate < size and size % candidate == 0)


class ListWriter:
    """Appends records (dropping ids already saved), logs offsets that cannot be fetched even one row at a time,
    and keeps the next offset in a progress file so reruns resume there."""

    def __init__(self, path: Path, partition: str = ""):
        stem = path.stem + (f".{partition}" if partition else "")
        self.path, self.progress, self.gaps = path, path.with_name(stem + ".progress"), path.with_name(stem + "_gaps.csv")
        self.consecutive_gaps = 0
        ids = saved_ids(path)
        self.seen = set(ids)
        # without a progress file, an unfiltered run resumes at the saved count (lists written before progress files existed)
        self.next_offset = int(self.progress.read_text()) if self.progress.exists() else 0 if partition else len(ids)
        self.added = 0

    def write(self, records, next_offset):
        new = [record for record in records if record.get("id") not in self.seen]
        self.seen.update(record.get("id") for record in new)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as output:
            output.write("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in new))
        self.progress.write_text(str(next_offset))
        self.next_offset = next_offset
        self.added += len(new)
        if records:
            self.consecutive_gaps = 0

    def gap(self, offset, reason):
        new_file = not self.gaps.exists()
        with self.gaps.open("a", encoding="utf-8") as output:
            if new_file:
                output.write("offset,reason,logged_at\n")
            output.write(f"{offset},\"{reason.replace(chr(34), chr(39))}\",{time.strftime('%Y-%m-%d %H:%M:%S')}\n")


def collect_block(session, key, writer, offset, size, filters):
    """Fetch rows [offset, offset + size). If the block keeps failing, fetch it again in smaller blocks; a single row
    that still fails is logged as a gap and skipped. Returns totalCount (0 if every attempt failed)."""
    try:
        total, items = fetch_page(session, key, offset // size + 1, size, filters)
    except FatalApiError:
        raise
    except ApiError as error:
        if size == 1:
            print(f"offset {offset}: skipped after repeated failure; logged in {writer.gaps.name}", flush=True)
            writer.gap(offset, str(error))
            writer.write([], offset + 1)
            writer.consecutive_gaps += 1
            if writer.consecutive_gaps >= MAX_CONSECUTIVE_GAPS:
                raise FatalApiError(
                    f"offset {offset}: the last {MAX_CONSECUTIVE_GAPS} rows were all refused one by one, so the API most likely "
                    "stops paging this deep into one query. Collect in smaller partitions instead (see probe_emuseum)")
            return 0
        sub = smaller_size(size)
        print(f"offset {offset}: splitting the block of {size} into blocks of {sub}", flush=True)
        total = 0
        for start in range(offset, offset + size, sub):
            if start >= writer.next_offset:
                total = collect_block(session, key, writer, start, sub, filters) or total
        return total
    if items and len(items) < size and offset + len(items) < total:
        raise FatalApiError(f"offset {offset}: asked for {size} rows, got {len(items)} before the end ({total}); "
                            "the API probably caps the page size - rerun with a smaller --page-size")
    # Image URLs are kept exactly as returned: they embed eMuseum's own key, without which the image server
    # answers HTTP 500. data/raw/ is git-ignored; anything printed or committed goes through safe_url.
    writer.write([{"_offset": offset, **item} for item in items], min(offset + size, total) if total else offset + size)
    return total


def collect_list(key: str, path: Path, page_size: int = 100, delay: float = 0.2, filters: dict | None = None):
    """Collect every list record into path; returns (records added this run, totalCount)."""
    writer = ListWriter(path, partition_name(filters))
    offset = writer.next_offset // page_size * page_size
    if writer.next_offset:
        print(f"resuming at offset {writer.next_offset} ({len(writer.seen)} records saved), block size {page_size}", flush=True)
    session = requests.Session()
    total = None
    while total is None or offset < total:
        block_total = collect_block(session, key, writer, offset, page_size, filters)
        total = block_total or total
        print(f"offset {offset + page_size}: {len(writer.seen)} saved / {total}", flush=True)
        if total is None:
            raise ApiError(f"offset {offset}: no block could be fetched, so the total is unknown; rerun to retry")
        offset += page_size
        time.sleep(delay)
    return writer.added, total


def parse_filters(pairs) -> dict:
    if any("=" not in pair for pair in pairs):
        raise SystemExit("filters must look like KEY=VALUE")
    return dict(pair.split("=", 1) for pair in pairs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect all eMuseum list records (API key from artbridge/.env)")
    parser.add_argument("--output", default=str(OUTPUT_PATH))
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--delay", type=float, default=0.2)
    parser.add_argument("--filter", action="append", default=[], metavar="KEY=VALUE",
                        help="API filter for one partition, e.g. purposeCode=PS09...; repeat to combine")
    args = parser.parse_args()
    output = Path(args.output)
    try:
        added, total = collect_list(api_key(), output, args.page_size, args.delay, parse_filters(args.filter))
    except ApiError as error:
        raise SystemExit(f"stopped: {error}; rerun the same command to resume") from None
    print(f"Added {added} records (total {total}): {output}")
