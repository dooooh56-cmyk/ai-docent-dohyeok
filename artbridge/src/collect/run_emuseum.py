"""Run the whole eMuseum pipeline: list -> code labels -> classification -> KOGL Type 1 images.

Every step resumes where it stopped, so the same command can be rerun after an interruption or from a scheduler.
A finished list is marked with a .done file and not collected again unless --refresh is given.
"""

import argparse
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

from src.classify import classify, load_raw, load_rules
from src.collect.collect_emuseum import api_key, append_jsonl, collect_all, last_page
from src.collect.emuseum_codes import label_codes
from src.collect.fetch_emuseum_images import fetch_set

RAW = Path("data/raw")
LIST_PATH = RAW / "emuseum_list.jsonl"
DONE_PATH = RAW / "emuseum_list.done"
CODES_PATH = RAW / "emuseum_codes.csv"
CLASSIFIED_PATH = Path("data/classified/emuseum_classified.csv")
LOCK_PATH = RAW / "run_emuseum.lock"
LOG_DIR = Path("data/logs")


class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, text):
        for stream in self.streams:
            stream.write(text)
            stream.flush()

    def flush(self):
        for stream in self.streams:
            stream.flush()


def step(name):
    print(f"\n=== {datetime.now():%Y-%m-%d %H:%M:%S} {name}", flush=True)


def collect_list(key, refresh):
    if refresh:
        DONE_PATH.unlink(missing_ok=True)
        LIST_PATH.unlink(missing_ok=True)
    if DONE_PATH.exists():
        print(f"skip: list already complete ({DONE_PATH.read_text(encoding='utf-8').strip()}); use --refresh to collect again")
        return
    start = last_page(LIST_PATH) + 1
    added = append_jsonl(collect_all(key, start), LIST_PATH)
    total = sum(1 for line in LIST_PATH.open(encoding="utf-8") if line.strip())
    DONE_PATH.write_text(json.dumps({"finished_at": datetime.now().isoformat(timespec="seconds"), "records": total}) + "\n", encoding="utf-8")
    print(f"list complete: {total} records ({added} added this run)")


def run(args):
    key = api_key()
    step("1/4 list")
    collect_list(key, args.refresh)
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
        print(set_name, fetch_set(result.fillna(""), set_name, args.out_dir, key, args.limit, args.delay, args.recheck_skipped), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the full eMuseum collection pipeline (resumable)")
    parser.add_argument("--sets", nargs="+", default=["joseon_painting", "foreign_painting"])
    parser.add_argument("--out-dir", default="data/collection")
    parser.add_argument("--rules", default="data/classify_rules.csv")
    parser.add_argument("--limit", type=int, help="max new images per set (for trial runs)")
    parser.add_argument("--delay", type=float, default=0.3)
    parser.add_argument("--refresh", action="store_true", help="collect the list again from page 1 (for periodic updates)")
    parser.add_argument("--recheck-skipped", action="store_true", help="re-read object pages previously skipped for rights")
    args = parser.parse_args()
    if not Path("src/collect/run_emuseum.py").is_file():
        raise SystemExit("Run from the artbridge/ folder: uv run python -m src.collect.run_emuseum")
    RAW.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        lock = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise SystemExit(f"Another run seems active ({LOCK_PATH} exists). If no run is active, delete that file and retry.") from None
    log_path = LOG_DIR / f"run_emuseum_{datetime.now():%Y%m%d_%H%M%S}.log"
    with log_path.open("w", encoding="utf-8") as log:
        sys.stdout = Tee(sys.__stdout__, log)
        print(f"log: {log_path}")
        try:
            run(args)
            print("\nfinished")
        except requests.RequestException as error:
            # never print request URLs: they carry the API key
            status = error.response.status_code if error.response is not None else "network error"
            print(f"\nstopped: request failed ({status}, {type(error).__name__}); rerun the same command to resume")
            exit_code = 1
        except Exception:
            print("\nstopped with an error; rerun the same command to resume after fixing it")
            traceback.print_exc(file=sys.stdout)
            exit_code = 1
        else:
            exit_code = 0
        finally:
            sys.stdout = sys.__stdout__
            os.close(lock)
            LOCK_PATH.unlink(missing_ok=True)
    sys.exit(exit_code)
