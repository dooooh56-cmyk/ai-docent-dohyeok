"""Build readable labels for eMuseum list codes by sampling object pages.

The list API returns only codes (nationalityCode, purposeCode, materialCode). For each distinct code, a few
object pages are read and the label shown there is recorded; codes whose samples disagree are marked so the
label is not trusted silently.
"""

import argparse
import time
from pathlib import Path

import pandas as pd
import requests

from src.collect.emuseum_page import fetch_object_page
from src.collect.fetch_met_images import append_rows
from src.fetch_images import USER_AGENT

CODE_FIELDS = {"nationalityCode": "page_nationality_period", "purposeCode": "page_classification", "materialCode": "page_material"}


CODE_COLUMNS = ["code_field", "code", "label", "status", "sample_labels", "sample_ids", "record_count"]


def label_codes(raw, output_path, samples=2, delay=0.3, session=None):
    """Append one row per code as soon as it is labelled; codes already in the file are skipped, so reruns resume."""
    output_path = Path(output_path)
    known = set()
    if output_path.exists():
        existing = pd.read_csv(output_path, dtype=str, encoding="utf-8-sig")
        known = set(zip(existing["code_field"], existing["code"]))
    session = session or requests.Session()
    session.headers.setdefault("User-Agent", USER_AGENT)
    counts = {"consistent": 0, "conflict": 0, "missing": 0, "already_labelled": len(known)}
    for code_field, label_field in CODE_FIELDS.items():
        if code_field not in raw:
            print(f"warning: list records have no {code_field}; its labels stay empty")
            continue
        for code, group in raw[raw[code_field] != ""].groupby(code_field):
            if (code_field, code) in known:
                continue
            labels, ids = [], list(group["id"][:samples])
            for relic_id in ids:
                try:
                    labels.append(fetch_object_page(relic_id, session)[label_field])
                except requests.RequestException:
                    labels.append("")
                time.sleep(delay)
            found = [label for label in labels if label]
            status = "consistent" if found and len(set(found)) == 1 else "missing" if not found else "conflict"
            print(f"{code_field} {code}: {labels}", flush=True)
            append_rows(output_path, CODE_COLUMNS, [{"code_field": code_field, "code": code, "label": found[0] if found else "",
                                                     "status": status, "sample_labels": " | ".join(labels),
                                                     "sample_ids": " ".join(ids), "record_count": len(group)}])
            counts[status] += 1
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Label eMuseum codes by sampling object pages (resumable)")
    parser.add_argument("raw_jsonl", nargs="?", default="data/raw/emuseum_list.jsonl")
    parser.add_argument("--output", default="data/raw/emuseum_codes.csv")
    parser.add_argument("--samples", type=int, default=2)
    args = parser.parse_args()
    if not Path(args.raw_jsonl).is_file() or not Path(args.raw_jsonl).stat().st_size:
        raise SystemExit(f"{args.raw_jsonl} is missing or empty; run first: uv run python -m src.collect.collect_emuseum")
    raw = pd.read_json(args.raw_jsonl, lines=True, dtype=str).fillna("")
    print(f"{len(raw)} list records; reading sample object pages for each new code", flush=True)
    print(f"-> {args.output}:", label_codes(raw, args.output, args.samples))
