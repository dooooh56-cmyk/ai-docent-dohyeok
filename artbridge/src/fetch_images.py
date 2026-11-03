"""Re-download rights-approved catalog images and keep only files matching the recorded hash."""

import argparse
import hashlib
import json
import time
from pathlib import Path

import requests

from src.catalog import approved_rows, load_catalog

MAX_BYTES = 20 * 1024 * 1024
USER_AGENT = "ArtBridge/0.1 (personal research; catalog image restore)"


def download_bytes(url, session, timeout=30):
    with session.get(url, timeout=timeout, stream=True) as response:
        response.raise_for_status()
        content = bytearray()
        for chunk in response.iter_content(65536):
            content.extend(chunk)
            if len(content) > MAX_BYTES:
                raise ValueError("image exceeds 20MB")
    return bytes(content)


EMUSEUM_LIST = Path("data/raw/emuseum_list.jsonl")


def source_url(row, _cache={}):
    """eMuseum image URLs are committed with their embedded key redacted; the usable URL is in the local raw list."""
    url = row["image_source_url"]
    if "serviceKey=%5Bredacted%5D" not in url:
        return url
    if not _cache:
        if not EMUSEUM_LIST.is_file():
            raise ValueError(f"{EMUSEUM_LIST} not found; run: uv run python -m src.collect.run_emuseum")
        with EMUSEUM_LIST.open(encoding="utf-8") as source:
            _cache.update((record["id"], record.get("imgUri", "")) for record in map(json.loads, source))
    original = _cache.get(row["artwork_id"].removeprefix("EMUSEUM_"), "")
    if not original or "%5Bredacted%5D" in original:
        raise ValueError("no usable image URL in the local eMuseum list; rerun: uv run python -m src.collect.run_emuseum --refresh")
    return original


def fetch_catalog_images(rows, purpose="local_research", delay=0.5, session=None):
    session = session or requests.Session()
    session.headers.setdefault("User-Agent", USER_AGENT)
    report = []
    for row in approved_rows(rows, purpose):
        path = Path(row["image_path"])
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == row["image_sha256"]:
            report.append({"artwork_id": row["artwork_id"], "status": "present"})
            continue
        try:
            content = download_bytes(source_url(row), session)
        except (requests.RequestException, ValueError) as error:
            report.append({"artwork_id": row["artwork_id"], "status": "failed", "error": type(error).__name__ if "%5Bredacted%5D" in row["image_source_url"] else str(error)})
            continue
        finally:
            time.sleep(delay)
        digest = hashlib.sha256(content).hexdigest()
        if digest != row["image_sha256"]:
            report.append({"artwork_id": row["artwork_id"], "status": "hash_mismatch", "error": f"got {digest}"})
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(path.suffix + ".part")
        partial.write_bytes(content)
        partial.replace(path)
        report.append({"artwork_id": row["artwork_id"], "status": "downloaded"})
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Restore rights-approved catalog images from their recorded source URLs")
    parser.add_argument("catalog")
    parser.add_argument("--delay", type=float, default=0.5, help="seconds to wait between downloads")
    args = parser.parse_args()
    rows = load_catalog(args.catalog)
    report = fetch_catalog_images(rows, delay=args.delay)
    skipped = len(rows) - len(report)
    for item in report:
        if item["status"] in ("failed", "hash_mismatch"):
            print(f"{item['artwork_id']}: {item['status']} {item['error']}")
    counts = {status: sum(item["status"] == status for item in report) for status in ("present", "downloaded", "hash_mismatch", "failed")}
    print(f"approved {len(report)} (not approved {skipped}): " + ", ".join(f"{key} {value}" for key, value in counts.items()))
    if counts["hash_mismatch"] or counts["failed"]:
        raise SystemExit(1)
