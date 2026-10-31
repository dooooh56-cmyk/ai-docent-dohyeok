"""Build readable labels for eMuseum list codes by sampling object pages.

The list API returns only codes (nationalityCode, purposeCode, materialCode). For each distinct code, a few
object pages are read and the label shown there is recorded; codes whose samples disagree are marked so the
label is not trusted silently.
"""

import argparse
import csv
import time
from pathlib import Path

import pandas as pd
import requests

from src.collect.emuseum_page import fetch_object_page
from src.fetch_images import USER_AGENT

CODE_FIELDS = {"nationalityCode": "page_nationality_period", "purposeCode": "page_classification", "materialCode": "page_material"}


def build_code_labels(raw, samples=2, delay=0.3, session=None):
    session = session or requests.Session()
    session.headers.setdefault("User-Agent", USER_AGENT)
    rows = []
    for code_field, label_field in CODE_FIELDS.items():
        if code_field not in raw:
            print(f"warning: list records have no {code_field}; its labels stay empty")
            continue
        for code, group in raw[raw[code_field] != ""].groupby(code_field):
            labels, ids = [], list(group["id"][:samples])
            for relic_id in ids:
                try:
                    labels.append(fetch_object_page(relic_id, session)[label_field])
                except requests.RequestException:
                    labels.append("")
                time.sleep(delay)
            found = [label for label in labels if label]
            print(f"{code_field} {code}: {labels}", flush=True)
            rows.append({"code_field": code_field, "code": code, "label": found[0] if found else "",
                         "status": "consistent" if found and len(set(found)) == 1 else "missing" if not found else "conflict",
                         "sample_labels": " | ".join(labels), "sample_ids": " ".join(ids), "record_count": len(group)})
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Label eMuseum codes by sampling object pages")
    parser.add_argument("raw_jsonl", nargs="?", default="data/raw/emuseum_list.jsonl")
    parser.add_argument("--output", default="data/raw/emuseum_codes.csv")
    parser.add_argument("--samples", type=int, default=2)
    args = parser.parse_args()
    if not Path(args.raw_jsonl).is_file() or not Path(args.raw_jsonl).stat().st_size:
        raise SystemExit(f"{args.raw_jsonl} is missing or empty; run first: uv run python -m src.collect.collect_emuseum")
    raw = pd.read_json(args.raw_jsonl, lines=True, dtype=str).fillna("")
    print(f"{len(raw)} list records; reading sample object pages for each code (progress below)", flush=True)
    rows = build_code_labels(raw, args.samples)
    if not rows:
        raise SystemExit("No nationality/purpose/material codes found in the list records; nothing written")
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", newline="", encoding="utf-8-sig") as output:
        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)} codes -> {args.output}; " + ", ".join(f"{s} {sum(r['status'] == s for r in rows)}" for s in ("consistent", "conflict", "missing")))
