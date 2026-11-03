"""Download Met images for classified sets under the user's bulk open-license approval rule.

The user approved (2026-10-31) using images that the institution itself marks as openly licensed.
For the Met that is a live object-API record with isPublicDomain = true; anything else is skipped.
"""

import argparse
import csv
import hashlib
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests

from src.fetch_images import USER_AGENT, download_bytes

OBJECT_URL = "https://collectionapi.metmuseum.org/public/collection/v1/objects/{}"
POLICY_URL = "https://www.metmuseum.org/policies/image-resources"
APPROVAL_RULE = "user bulk rule 2026-10-31: institution open-license mark (Met isPublicDomain=true)"
CATALOG_FIELDS = ["artwork_id", "set_name", "title_original", "region", "culture", "artist", "artist_nationality", "object_date",
                  "medium", "classification", "department", "object_page_url", "metadata_source", "metadata_accessed_at",
                  "image_path", "image_source_url", "image_credit", "image_license", "license_url", "rights_status",
                  "rights_checked_at", "image_sha256", "image_view_id", "split_group_id"]
LICENSE_FIELDS = ["artwork_id", "image_source_url", "image_sha256", "image_license", "license_url", "rights_checked_at",
                  "image_credit", "rights_status", "rights_purpose", "rights_approved_by"]


def append_rows(path, fields, rows):
    new = not path.exists()
    with path.open("a", encoding="utf-8-sig" if new else "utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        if new:
            writer.writeheader()
        writer.writerows(rows)


def fetch_object(object_id, session):
    response = session.get(OBJECT_URL.format(object_id), timeout=30)
    response.raise_for_status()
    return response.json()


def region_from_culture(culture):
    """Map only an explicit leading Met culture label; anything else stays blank rather than guessed."""
    head = culture.replace("(", " ").replace(",", " ").split()
    return {"Korea": "Korea", "China": "China", "Japan": "Japan"}.get(head[0] if head else "", "")


def catalog_rows(record, set_name, image_path, content, today):
    artwork_id = f"MET_{record['objectID']}"
    shared = {"artwork_id": artwork_id, "image_source_url": record["primaryImageSmall"],
              "image_sha256": hashlib.sha256(content).hexdigest(), "image_license": "CC0 (The Met Open Access)",
              "license_url": POLICY_URL, "rights_checked_at": today,
              "image_credit": f"The Metropolitan Museum of Art, {record.get('creditLine', '')}".rstrip(", "),
              "rights_status": "approved_local"}
    catalog = {**shared, "set_name": set_name, "title_original": record.get("title", ""),
               "region": region_from_culture(record.get("culture", "")), "culture": record.get("culture", ""),
               "artist": record.get("artistDisplayName", ""), "artist_nationality": record.get("artistNationality", ""),
               "object_date": record.get("objectDate", ""), "medium": record.get("medium", ""),
               "classification": record.get("classification", ""), "department": record.get("department", ""),
               "object_page_url": record.get("objectURL", ""), "metadata_source": "Met Collection API v1 objects",
               "metadata_accessed_at": today, "image_path": str(image_path),
               "image_view_id": f"{artwork_id}_primary", "split_group_id": artwork_id}
    license_row = {**shared, "rights_purpose": "local_research", "rights_approved_by": APPROVAL_RULE}
    return catalog, license_row


def finished_ids(catalog_path, report_path, recheck_skipped=False):
    """Saved objects and, unless recheck_skipped, objects skipped for rights or missing images."""
    done = set(pd.read_csv(catalog_path, dtype=str)["artwork_id"]) if catalog_path.exists() else set()
    if report_path.exists() and not recheck_skipped:
        report = pd.read_csv(report_path, dtype=str, encoding="utf-8-sig")
        done |= set(report.loc[report["status"].str.startswith("skipped"), "artwork_id"])
    return done


def fetch_set(classified, set_name, out_dir, limit=None, delay=0.1, recheck_skipped=False):
    out_dir = Path(out_dir)
    images = out_dir / "images"
    images.mkdir(parents=True, exist_ok=True)
    catalog_path, license_path, report_path = out_dir / "metadata.csv", out_dir / "license_log.csv", out_dir / "fetch_report.csv"
    done = finished_ids(catalog_path, report_path, recheck_skipped)
    rows = classified[(classified["set_name"] == set_name) & (classified["Is Public Domain"] == "True")]
    ids = [object_id for object_id in rows["Object ID"] if f"MET_{object_id}" not in done][:limit]
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    today = date.today().isoformat()
    counts = {}
    for object_id in ids:
        status, detail = "saved", ""
        try:
            record = fetch_object(object_id, session)
            if record.get("isPublicDomain") is not True:
                status = "skipped_not_public_domain"
            elif not record.get("primaryImageSmall"):
                status = "skipped_no_image"
            else:
                content = download_bytes(record["primaryImageSmall"], session)
                image_path = images / f"MET_{object_id}{Path(record['primaryImageSmall']).suffix.lower() or '.jpg'}"
                image_path.write_bytes(content)
                catalog, license_row = catalog_rows(record, set_name, image_path, content, today)
                append_rows(catalog_path, CATALOG_FIELDS, [catalog])
                append_rows(license_path, LICENSE_FIELDS, [license_row])
        except (requests.RequestException, ValueError) as error:
            status, detail = "failed", str(error)[:300]
        append_rows(report_path, ["artwork_id", "set_name", "status", "detail", "checked_at"],
                    [{"artwork_id": f"MET_{object_id}", "set_name": set_name, "status": status, "detail": detail, "checked_at": today}])
        counts[status] = counts.get(status, 0) + 1
        time.sleep(delay)
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download open-license Met images for classified sets")
    parser.add_argument("classified_csv")
    parser.add_argument("--sets", nargs="+", required=True)
    parser.add_argument("--out-dir", default="data/collection")
    parser.add_argument("--limit", type=int, help="max new objects per set (for trial runs)")
    parser.add_argument("--delay", type=float, default=0.1, help="seconds between objects; the Met asks for at most 80 requests/s")
    args = parser.parse_args()
    classified = pd.read_csv(args.classified_csv, dtype=str, encoding="utf-8-sig")
    for set_name in args.sets:
        print(set_name, fetch_set(classified, set_name, args.out_dir, args.limit, args.delay))
