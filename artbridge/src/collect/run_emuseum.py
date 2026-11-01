"""Run the whole eMuseum pipeline: list -> code labels -> classification -> KOGL Type 1 images.

Every step resumes where it stopped, so the same command can be rerun after an interruption or from a scheduler.
A finished list is marked with a .done file and not collected again unless --refresh is given.
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.classify import classify, load_raw, load_rules
from src.collect.collect_emuseum import api_key, collect_list as collect_records, parse_filters, partition_name
from src.collect.emuseum_codes import label_codes
from src.collect.fetch_emuseum_images import fetch_set
from src.collect.pipeline import run_pipeline, step

RAW = Path("data/raw")
LIST_PATH = RAW / "emuseum_list.jsonl"
CODES_PATH = RAW / "emuseum_codes.csv"
CLASSIFIED_PATH = Path("data/classified/emuseum_classified.csv")


def collect_list(key, refresh, page_size, partitions):
    """Collect the list, either in one query or as several filtered partitions that all append to LIST_PATH."""
    if refresh:
        for stale in RAW.glob(LIST_PATH.stem + "*"):
            stale.unlink()
    for filters in partitions or [None]:
        name = partition_name(filters)
        done = LIST_PATH.with_name(LIST_PATH.stem + (f".{name}" if name else "") + ".done")
        label = f"partition {name}" if name else "list"
        if done.exists():
            print(f"skip: {label} already complete ({done.read_text(encoding='utf-8').strip()}); use --refresh to collect again")
            continue
        print(f"collecting {label}", flush=True)
        added, total = collect_records(key, LIST_PATH, page_size, filters=filters)
        done.write_text(json.dumps({"finished_at": datetime.now().isoformat(timespec="seconds"), "total": total, "added": added}) + "\n",
                        encoding="utf-8")
        print(f"{label} complete: totalCount {total} ({added} new records this run)")
    records = sum(1 for line in LIST_PATH.open(encoding="utf-8") if line.strip())
    gaps = sum(sum(1 for _ in path.open(encoding="utf-8")) - 1 for path in RAW.glob(LIST_PATH.stem + "*_gaps.csv"))
    print(f"list file: {records} records" + (f"; {gaps} offsets skipped (see {LIST_PATH.stem}*_gaps.csv)" if gaps else ""))


def run(args):
    key = api_key()
    step("1/4 list")
    collect_list(key, args.refresh, args.page_size, [parse_filters(spec.split(",")) for spec in args.partition])
    step("2/4 code labels")
    raw = pd.read_json(LIST_PATH, lines=True, dtype=str).fillna("")
    print(label_codes(raw, CODES_PATH))
    step("3/4 classify")
    result = classify(load_raw("emuseum", LIST_PATH, CODES_PATH), load_rules(args.rules, "emuseum"))
    CLASSIFIED_PATH.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(CLASSIFIED_PATH, index=False, encoding="utf-8-sig")
    print(result.groupby("set_name").size().to_string())
    step("4/4 images")
    for set_name in args.sets:
        print(set_name, fetch_set(result.fillna(""), set_name, args.out_dir, args.limit, args.delay, args.recheck_skipped), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the full eMuseum collection pipeline (resumable)")
    parser.add_argument("--sets", nargs="+", default=["joseon_painting", "foreign_painting"])
    parser.add_argument("--out-dir", default="data/collection")
    parser.add_argument("--rules", default="data/classify_rules.csv")
    parser.add_argument("--limit", type=int, help="max new images per set (for trial runs)")
    parser.add_argument("--delay", type=float, default=0.3)
    parser.add_argument("--page-size", type=int, default=100,
                        help="list rows per request; larger means fewer requests. Stops with a message if the API caps it")
    parser.add_argument("--partition", action="append", default=[], metavar="KEY=VALUE[,KEY=VALUE]",
                        help="collect the list as filtered partitions (repeat per partition) when one query cannot be paged to the end")
    parser.add_argument("--refresh", action="store_true", help="collect the list again from page 1 (for periodic updates)")
    parser.add_argument("--recheck-skipped", action="store_true", help="re-read object pages previously skipped for rights")
    run_pipeline("emuseum", run, parser.parse_args())
