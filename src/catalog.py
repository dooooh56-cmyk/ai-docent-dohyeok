"""Load a catalog and enforce recorded rights for local research use."""

import csv
import hashlib
from pathlib import Path

REQUIRED = {"artwork_id", "region", "object_page_url", "image_path", "rights_status", "image_license", "license_url", "rights_checked_at", "image_credit"}
REGIONS = {"Korea", "China", "Japan", "India_Gandhara"}


def load_catalog(path):
    path = Path(path)
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        missing = REQUIRED - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"Missing catalog columns: {', '.join(sorted(missing))}")
        rows = list(reader)
    with (path.parent / "license_log.csv").open(encoding="utf-8-sig", newline="") as source:
        approvals = {}
        for approval in csv.DictReader(source):
            key = approval.get("artwork_id", "")
            if not key or key in approvals:
                raise ValueError(f"Missing or duplicate rights record: {key}")
            approvals[key] = approval
    for row in rows:
        approval = approvals.get(row.get("artwork_id"), {})
        evidence = ("image_source_url", "image_sha256", "image_license", "license_url", "rights_checked_at", "image_credit")
        matches = all(row.get(key) and row.get(key) == approval.get(key) for key in evidence)
        row["rights_status"] = approval.get("rights_status", "") if matches else ""
        row["rights_approved_by"] = approval.get("rights_approved_by", "")
        row["rights_purpose"] = approval.get("rights_purpose", "")
    return rows


def validate_catalog(rows):
    errors = []
    seen = set()
    for row in rows:
        artwork_id = row.get("artwork_id", "")
        if not artwork_id or artwork_id in seen:
            errors.append(f"Missing or duplicate artwork_id: {artwork_id}")
        seen.add(artwork_id)
        if row.get("region") not in REGIONS:
            errors.append(f"{artwork_id}: invalid region")
        if not row.get("object_page_url"):
            errors.append(f"{artwork_id}: missing object page")
        image_path = row.get("image_path", "")
        if not image_path or not Path(image_path).is_file():
            errors.append(f"{artwork_id}: image file missing")
    return errors


def usable_image_rows(rows, purpose):
    if purpose != "local_research":
        raise ValueError(f"Unsupported purpose: {purpose}")
    required = ("artwork_id", "image_path", "object_page_url", "image_license", "license_url", "rights_checked_at", "image_credit", "image_sha256")
    usable = []
    for row in rows:
        if row.get("rights_status") != "approved_local" or not row.get("rights_approved_by") or row.get("rights_purpose") != purpose or not all(row.get(key) for key in required):
            continue
        path = Path(row["image_path"])
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == row["image_sha256"]:
            usable.append(row)
    return usable
