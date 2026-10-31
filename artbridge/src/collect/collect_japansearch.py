"""Collect Japanese Buddhist-art candidates from the ColBase Japan Search API."""

import csv
import json
import time
from datetime import date
from pathlib import Path

import requests

API_URL = "https://jpsearch.go.jp/api/item/search/cobas-default"
POLICY_URL = "https://colbase.nich.go.jp/pages/term?locale=en"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = PROJECT_ROOT / "data" / "colbase_candidates.csv"
QUERY = "仏像"
PAGE_SIZE = 100


def collect_candidates(limit: int = 30) -> list[dict]:
    """Fetch ColBase records; image rights remain per-record review data."""
    rows = []
    offset = 0

    while len(rows) < limit:
        response = requests.get(
            API_URL,
            params={"keyword": QUERY, "size": min(PAGE_SIZE, limit - len(rows)), "from": offset},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        records = payload.get("list", [])
        if not records:
            break

        checked_at = date.today().isoformat()
        for record in records:
            common = record.get("common") or {}
            rights_code = common.get("contentsRightsType", "")
            rights_statement = common.get("contentsRights", "")
            rights_text = rights_statement.get("en") or rights_statement.get("ja") if isinstance(rights_statement, dict) else rights_statement
            rows.append({
                "artwork_id": f"JPS_{record.get('id', '')}",
                "title_original": common.get("title", ""),
                "title_en": common.get("titleEn", ""),
                "region": "",
                "period_original": "; ".join(common.get("temporal") or []),
                "museum": common.get("provider", ""),
                "image_url": "; ".join(common.get("thumbnailUrl") or []),
                "source_url": common.get("linkUrl", ""),
                "metadata_source": "Japan Search / ColBase API",
                "metadata_accessed_at": checked_at,
                "image_license": rights_code,
                "license_statement": rights_text,
                "license_url": POLICY_URL,
                "rights_status": "unverified",
                "rights_checked_at": "",
                "api_rights_accessed_at": checked_at,
                "api_record_url": f"https://jpsearch.go.jp/api/item/{record.get('id', '')}",
                "source_record_json": json.dumps(record, ensure_ascii=False),
            })
            if len(rows) >= limit:
                break

        offset += len(records)
        if offset >= payload.get("hit", 0):
            break
        time.sleep(0.3)

    return rows


def main() -> None:
    rows = collect_candidates()
    if not rows:
        print("No ColBase candidates found.")
        return

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", newline="", encoding="utf-8-sig") as output:
        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"Collected {len(rows)} candidates: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
