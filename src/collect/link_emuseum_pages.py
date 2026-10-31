"""Link eMuseum API candidates to their official eMuseum object pages."""

import csv
import html
import json
import re
import time
from datetime import date
from pathlib import Path

import requests

PAGE_URL = "https://www.emuseum.go.kr/detail?relicId={record_id}"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
INPUT_PATH = PROJECT_ROOT / "data" / "emuseum_candidates.csv"
OUTPUT_PATH = PROJECT_ROOT / "data" / "emuseum_page_links.csv"
FIELD_LABELS = {
    "명칭": "page_title",
    "다른명칭": "page_title_other",
    "국적/시대": "page_nationality_period",
    "분류": "page_classification",
    "재질": "page_material",
    "크기": "page_size",
}


def _page_lines(page: str) -> list[str]:
    text = re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.S)
    text = html.unescape(re.sub(r"<[^>]+>", "\n", text))
    return [line.strip() for line in text.splitlines() if line.strip()]


def parse_object_page(page: str) -> dict:
    """Read the first detail block as shown on the page; missing fields stay empty."""
    lines = _page_lines(page)
    fields = {name: "" for name in [*FIELD_LABELS.values(), "page_accession_number",
                                    "page_image_rights_statement", "page_original_resolution"]}
    for index, line in enumerate(lines[:-1]):
        key = FIELD_LABELS.get(line)
        if key and not fields[key]:
            fields[key] = lines[index + 1]
        elif line == "소장품번호" and not fields["page_accession_number"]:
            fields["page_accession_number"] = " ".join(lines[index + 1:index + 3])
        elif line.startswith("저작권 보호분야") and not fields["page_image_rights_statement"]:
            fields["page_image_rights_statement"] = f"{lines[index - 1]} / {line}"
        elif line.startswith("원본 해상도") and not fields["page_original_resolution"]:
            fields["page_original_resolution"] = line.removeprefix("원본 해상도").strip()
    return fields


def link_candidate(row: dict, page: str, accessed_at: str) -> dict:
    record = json.loads(row["source_record_json"])
    fields = parse_object_page(page)
    expected_number = f"{record.get('museumName3', '')} {record.get('relicNo', '')}".strip()
    problems = []
    if fields["page_accession_number"] != expected_number:
        problems.append(f"소장품번호 불일치(API {expected_number})")
    if fields["page_title"] != row["title_original"]:
        problems.append(f"명칭 불일치(API {row['title_original']})")
    if not fields["page_image_rights_statement"]:
        problems.append("페이지에서 공공누리 표기를 찾지 못함")
    return {
        "artwork_id": row["artwork_id"],
        "api_record_id": row["api_record_id"],
        "object_page_url": PAGE_URL.format(record_id=row["api_record_id"]),
        **fields,
        "page_accessed_at": accessed_at,
        "link_status": "matched" if not problems else "needs_review",
        "notes": "; ".join(problems),
    }


def main() -> None:
    with INPUT_PATH.open(encoding="utf-8-sig", newline="") as source:
        candidates = list(csv.DictReader(source))
    accessed_at = date.today().isoformat()
    links = []
    for row in candidates:
        response = requests.get(PAGE_URL.format(record_id=row["api_record_id"]), timeout=30)
        response.raise_for_status()
        links.append(link_candidate(row, response.text, accessed_at))
        time.sleep(1)
    with OUTPUT_PATH.open("w", newline="", encoding="utf-8-sig") as output:
        writer = csv.DictWriter(output, fieldnames=links[0].keys())
        writer.writeheader()
        writer.writerows(links)
    matched = sum(link["link_status"] == "matched" for link in links)
    print(f"Linked {matched}/{len(links)} candidates: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
