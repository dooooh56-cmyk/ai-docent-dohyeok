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
from src.collect.collect_emuseum import api_key, collect_list as collect_records
from src.collect.emuseum_codes import label_codes
from src.collect.fetch_emuseum_images import fetch_set
from src.collect.pipeline import run_pipeline, step

RAW = Path("data/raw")
LIST_PATH = RAW / "emuseum_list.jsonl"
DONE_PATH = RAW / "emuseum_list.done"
CODES_PATH = RAW / "emuseum_codes.csv"
CLASSIFIED_PATH = Path("data/classified/emuseum_classified.csv")


def collect_list(key, refresh, page_size):
    if refresh:
        for stale in (DONE_PATH, LIST_PATH, LIST_PATH.with_suffix(".progress"), LIST_PATH.with_name(LIST_PATH.stem + "_gaps.csv")):
            stale.unlink(missing_ok=True)
    if DONE_PATH.exists():
        print(f"skip: list already complete ({DONE_PATH.read_text(encoding='utf-8').strip()}); use --refresh to collect again")
        return
    added, _ = collect_records(key, LIST_PATH, page_size)
    total = sum(1 for line in LIST_PATH.open(encoding="utf-8") if line.strip())
    DONE_PATH.write_text(json.dumps({"finished_at": datetime.now().isoformat(timespec="seconds"), "records": total}) + "\n", encoding="utf-8")
    gaps = LIST_PATH.with_name(LIST_PATH.stem + "_gaps.csv")
    skipped = sum(1 for _ in gaps.open(encoding="utf-8")) - 1 if gaps.exists() else 0
    print(f"list complete: {total} records ({added} added this run; {skipped} offsets skipped, see {gaps.name})" if skipped
          else f"list complete: {total} records ({added} added this run)")


def run(args):
    key = api_key()
    step("1/4 list")
    collect_list(key, args.refresh, args.page_size)
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
    parser.add_argument("--refresh", action="store_true", help="collect the list again from page 1 (for periodic updates)")
    parser.add_argument("--recheck-skipped", action="store_true", help="re-read object pages previously skipped for rights")
    run_pipeline("emuseum", run, parser.parse_args())
