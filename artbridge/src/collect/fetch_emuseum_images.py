"""Download eMuseum images for classified sets under the user's bulk open-license approval rule.

The user approved (2026-10-31) using images that the institution itself marks as openly licensed.
For eMuseum that is the object page showing KOGL (공공누리) Type 1; any other type or no mark is skipped.
"""

import argparse
import hashlib
import time
from datetime import date
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pandas as pd
import requests

from src.collect.collect_emuseum import api_key
from src.collect.emuseum_page import PAGE_URL, fetch_object_page
from src.collect.fetch_met_images import CATALOG_FIELDS, LICENSE_FIELDS, append_rows
from src.fetch_images import USER_AGENT, download_bytes

KOGL_TYPE1_URL = "https://www.kogl.or.kr/info/licenseType1.do"
APPROVAL_RULE = "user bulk rule 2026-10-31: institution open-license mark (eMuseum page KOGL Type 1)"
REGIONS = {"한국": "Korea", "중국": "China", "일본": "Japan"}
SIGNATURES = {b"\xff\xd8\xff": ".jpg", b"\x89PNG": ".png", b"GIF8": ".gif"}


def with_key(url, key):
    parts = urlsplit(url)
    query = [(name, key if name.lower() == "servicekey" else value) for name, value in parse_qsl(parts.query, keep_blank_values=True)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def image_suffix(content):
    for signature, suffix in SIGNATURES.items():
        if content.startswith(signature):
            return suffix
    raise ValueError("response is not a JPEG, PNG or GIF image")


def catalog_rows(row, page, image_path, content, today):
    artwork_id = f"EMUSEUM_{row['id']}"
    nationality = page["page_nationality_period"] or row.get("nationality_label", "")
    shared = {"artwork_id": artwork_id, "image_source_url": row["imgUri"], "image_sha256": hashlib.sha256(content).hexdigest(),
              "image_license": "공공누리 제1유형 (출처표시)", "license_url": KOGL_TYPE1_URL, "rights_checked_at": today,
              "image_credit": f"{row.get('museumName2', '')} (e뮤지엄), 공공누리 제1유형".lstrip(" "),
              "rights_status": "approved_local"}
    catalog = {**shared, "set_name": row["set_name"], "title_original": page["page_title"] or row.get("nameKr", ""),
               "region": REGIONS.get(nationality.split(" - ")[0], ""), "culture": nationality,
               "artist": row.get("author", ""), "artist_nationality": "", "object_date": nationality,
               "medium": page["page_material"], "classification": page["page_classification"],
               "department": row.get("museumName2", ""), "object_page_url": PAGE_URL.format(row["id"]),
               "metadata_source": "eMuseum Open API list + object page", "metadata_accessed_at": today,
               "image_path": str(image_path), "image_view_id": f"{artwork_id}_primary", "split_group_id": artwork_id}
    license_row = {**shared, "rights_purpose": "local_research", "rights_approved_by": APPROVAL_RULE}
    return catalog, license_row


def fetch_set(classified, set_name, out_dir, key, limit=None, delay=0.3):
    out_dir = Path(out_dir)
    images = out_dir / "images"
    images.mkdir(parents=True, exist_ok=True)
    catalog_path, license_path, report_path = out_dir / "metadata.csv", out_dir / "license_log.csv", out_dir / "fetch_report.csv"
    done = set(pd.read_csv(catalog_path, dtype=str)["artwork_id"]) if catalog_path.exists() else set()
    rows = classified[(classified["set_name"] == set_name) & ~("EMUSEUM_" + classified["id"]).isin(done)]
    rows = rows.head(limit) if limit else rows
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    today = date.today().isoformat()
    counts = {}
    for row in rows.to_dict("records"):
        status, detail = "saved", ""
        try:
            page = fetch_object_page(row["id"], session)
            if page["page_kogl_type"] != "1":
                status, detail = "skipped_not_kogl_type1", page["page_rights_statement"]
            elif not row.get("imgUri"):
                status = "skipped_no_image"
            else:
                content = download_bytes(with_key(row["imgUri"], key), session)
                image_path = images / f"EMUSEUM_{row['id']}{image_suffix(content)}"
                image_path.write_bytes(content)
                catalog, license_row = catalog_rows(row, page, image_path, content, today)
                append_rows(catalog_path, CATALOG_FIELDS, [catalog])
                append_rows(license_path, LICENSE_FIELDS, [license_row])
        except (requests.RequestException, ValueError) as error:
            # never echo request URLs: they carry the API key
            status, detail = "failed", type(error).__name__ if isinstance(error, requests.RequestException) else str(error)
        append_rows(report_path, ["artwork_id", "set_name", "status", "detail", "checked_at"],
                    [{"artwork_id": f"EMUSEUM_{row['id']}", "set_name": set_name, "status": status, "detail": detail, "checked_at": today}])
        counts[status] = counts.get(status, 0) + 1
        time.sleep(delay)
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download KOGL Type 1 eMuseum images for classified sets")
    parser.add_argument("classified_csv", nargs="?", default="data/classified/emuseum_classified.csv")
    parser.add_argument("--sets", nargs="+", required=True)
    parser.add_argument("--out-dir", default="data/collection")
    parser.add_argument("--limit", type=int, help="max new objects per set (for trial runs)")
    parser.add_argument("--delay", type=float, default=0.3)
    args = parser.parse_args()
    classified = pd.read_csv(args.classified_csv, dtype=str, encoding="utf-8-sig").fillna("")
    key = api_key()
    for set_name in args.sets:
        print(set_name, fetch_set(classified, set_name, args.out_dir, key, args.limit, args.delay))
