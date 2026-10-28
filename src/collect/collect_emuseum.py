"""Collect Korean Buddhist-art candidates from the eMuseum Open API."""

import csv
import json
import os
import xml.etree.ElementTree as ET
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from datetime import date
from pathlib import Path

import requests

API_URL = "https://apis.data.go.kr/1371027/openapi/list"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = PROJECT_ROOT / "data" / "emuseum_candidates.csv"
QUERY = "불상"
LIMIT = 30


def _load_env_file() -> None:
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


def _items(payload: dict | str) -> list[dict]:
    if isinstance(payload, str):
        root = ET.fromstring(payload)
        return [{item.attrib.get("key", ""): item.attrib.get("value", "")
                 for item in record if item.attrib.get("key")}
                for record in root.findall("./list/data")]
    items = payload.get("response", {}).get("body", {}).get("items", {}).get("item", [])
    return items if isinstance(items, list) else [items] if items else []


def _safe_url(value: str) -> str:
    parts = urlsplit(value)
    query = [(key, "[redacted]" if key.lower() == "servicekey" else val)
             for key, val in parse_qsl(parts.query, keep_blank_values=True)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def collect_candidates(api_key: str) -> list[dict]:
    response = requests.get(
        API_URL,
        params={"serviceKey": api_key, "name": QUERY, "numOfRows": LIMIT, "pageNo": 1},
        headers={"Accept": "application/xml"},
        timeout=30,
    )
    response.raise_for_status()
    try:
        payload = response.json()
    except requests.exceptions.JSONDecodeError:
        payload = response.text
    items = _items(payload)
    accessed_at = date.today().isoformat()
    rows = [
        {
            "artwork_id": f"EMUSEUM_{item.get('id', '')}",
            "title_original": item.get("nameKr", ""),
            "region": "",
            "period_original": item.get("period", ""),
            "material_original": item.get("material", ""),
            "museum": item.get("museumName1", ""),
            "accession_number": item.get("relicNo", ""),
            "image_url": _safe_url(item.get("imgUri", "")),
            "source_url": "",
            "metadata_source": "National Museum of Korea eMuseum Open API",
            "metadata_accessed_at": accessed_at,
            "image_license": "",
            "license_url": "https://www.emuseum.go.kr/copyright",
            "rights_status": "unverified",
            "rights_checked_at": "",
            "api_rights_accessed_at": "",
            "api_record_id": item.get("id", ""),
            "source_record_json": json.dumps(
                {key: (_safe_url(value) if "uri" in key.lower() and isinstance(value, str) else value)
                 for key, value in item.items()},
                ensure_ascii=False,
            ),
        }
        for item in items[:LIMIT]
        if item.get("id") and item.get("nameKr")
    ]
    return rows


def main() -> None:
    _load_env_file()
    api_key = os.getenv("EMUSEUM_API_KEY")
    if not api_key:
        raise SystemExit("Set EMUSEUM_API_KEY after registering for the eMuseum API at data.go.kr.")

    try:
        rows = collect_candidates(api_key)
    except requests.RequestException as error:
        status = error.response.status_code if error.response is not None else "network error"
        kind = type(error).__name__
        raise SystemExit(f"eMuseum API request failed ({status}, {kind}); details suppressed.") from None
    if not rows:
        print("No eMuseum candidates found.")
        return
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", newline="", encoding="utf-8-sig") as output:
        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"Collected {len(rows)} candidates: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
