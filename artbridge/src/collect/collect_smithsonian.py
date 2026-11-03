"""Collect Smithsonian Buddhist-art candidates from its Open Access API."""

import csv
import json
import os
from datetime import date
from pathlib import Path

import requests

API_URL = "https://api.si.edu/openaccess/api/v1.0/search"
POLICY_URL = "https://www.si.edu/openaccess/faq"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = PROJECT_ROOT / "data" / "smithsonian_candidates.csv"
QUERIES = ("Buddha", "Bodhisattva")
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


def _first_text(fields: dict, *names: str) -> str:
    for name in names:
        values = fields.get(name) or []
        if values:
            value = values[0]
            return value.get("content", "") if isinstance(value, dict) else str(value)
    return ""


def collect_candidates(api_key: str) -> list[dict]:
    rows = []
    seen = set()
    accessed_at = date.today().isoformat()

    for query in QUERIES:
        response = requests.get(
            API_URL,
            params={"q": query, "rows": 100, "api_key": api_key},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()

        for result in payload.get("response", {}).get("rows", []):
            if result.get("id") in seen:
                continue
            content = result.get("content") or {}
            descriptive = content.get("descriptiveNonRepeating") or {}
            media = (descriptive.get("online_media") or {}).get("media") or []
            if isinstance(media, dict):
                media = [media]
            open_media = [m for m in media if (m.get("usage") or {}).get("access") == "CC0"]
            if not open_media:
                continue

            asset = open_media[0]
            structured = content.get("indexedStructured") or {}
            freetext = content.get("freetext") or {}
            rows.append({
                "artwork_id": f"SI_{result.get('id', '')}",
                "title_original": result.get("title", ""),
                "region": "",
                "period_original": "; ".join(structured.get("date") or []),
                "museum": "; ".join(structured.get("data_source") or []),
                "image_url": asset.get("content", ""),
                "source_url": descriptive.get("record_link", ""),
                "metadata_source": "Smithsonian Open Access API",
                "metadata_accessed_at": accessed_at,
                "image_license": "CC0 (API media usage.access)",
                "license_url": POLICY_URL,
                "rights_status": "unverified",
                "rights_checked_at": "",
                "api_rights_accessed_at": accessed_at,
                "api_record_id": result.get("id", ""),
                "culture_original": "; ".join(structured.get("culture") or []),
                "object_type": "; ".join(structured.get("object_type") or []),
                "material_original": _first_text(freetext, "physical_description"),
                "image_credit": asset.get("credit", ""),
                "source_record_json": json.dumps(result, ensure_ascii=False),
            })
            seen.add(result.get("id"))
            if len(rows) >= LIMIT:
                return rows
    return rows


def main() -> None:
    _load_env_file()
    api_key = os.getenv("SMITHSONIAN_API_KEY")
    if not api_key:
        raise SystemExit("Set SMITHSONIAN_API_KEY after registering at api.data.gov.")

    try:
        rows = collect_candidates(api_key)
    except requests.RequestException as error:
        status = error.response.status_code if error.response is not None else "network error"
        kind = type(error).__name__
        raise SystemExit(f"Smithsonian API request failed ({status}, {kind}); details suppressed.") from None
    if not rows:
        print("No Smithsonian CC0 image candidates found.")
        return
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", newline="", encoding="utf-8-sig") as output:
        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"Collected {len(rows)} candidates: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
