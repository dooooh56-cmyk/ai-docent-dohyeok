"""Run the whole Met pipeline: Open Access metadata CSV -> classification -> public-domain images.

Every step resumes where it stopped, so the same command can be rerun after an interruption or from a scheduler.
The metadata CSV is downloaded once and reused unless --refresh is given.
"""

import argparse
from pathlib import Path

import pandas as pd
import requests

from src.classify import classify, load_raw, load_rules
from src.collect.fetch_met_images import fetch_set
from src.collect.pipeline import run_pipeline, step
from src.fetch_images import USER_AGENT

CSV_URL = "https://media.githubusercontent.com/media/metmuseum/openaccess/master/MetObjects.csv"
CSV_PATH = Path("data/raw/MetObjects.csv")
CLASSIFIED_PATH = Path("data/classified/met_classified.csv")


def download_metadata(refresh):
    if CSV_PATH.exists() and not refresh:
        print(f"skip: {CSV_PATH} already downloaded; use --refresh to download the latest")
        return
    partial = CSV_PATH.with_suffix(".csv.part")
    with requests.get(CSV_URL, stream=True, timeout=60, headers={"User-Agent": USER_AGENT}) as response:
        response.raise_for_status()
        total = int(response.headers.get("Content-Length", 0))
        done, reported = 0, 0
        with partial.open("wb") as output:
            for chunk in response.iter_content(1 << 20):
                output.write(chunk)
                done += len(chunk)
                if done - reported >= 50 << 20:
                    print(f"{done >> 20} / {total >> 20} MB", flush=True)
                    reported = done
    if total and done != total:
        raise ValueError(f"metadata download incomplete ({done} of {total} bytes); rerun to retry")
    partial.replace(CSV_PATH)
    print(f"downloaded {done >> 20} MB -> {CSV_PATH}")


def run(args):
    step("1/3 metadata")
    download_metadata(args.refresh)
    step("2/3 classify")
    result = classify(load_raw("met", CSV_PATH), load_rules(args.rules, "met"))
    CLASSIFIED_PATH.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(CLASSIFIED_PATH, index=False, encoding="utf-8-sig")
    summary = result.groupby("set_name")["Is Public Domain"].agg(total="size", public_domain=lambda s: (s == "True").sum())
    print(summary.to_string())
    step("3/3 images")
    classified = pd.read_csv(CLASSIFIED_PATH, dtype=str, encoding="utf-8-sig")
    for set_name in args.sets:
        print(set_name, fetch_set(classified, set_name, args.out_dir, args.limit, args.delay, args.recheck_skipped), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the full Met collection pipeline (resumable)")
    parser.add_argument("--sets", nargs="+", default=["korea_painting", "foreign_painting", "japan_print"])
    parser.add_argument("--out-dir", default="data/collection")
    parser.add_argument("--rules", default="data/classify_rules.csv")
    parser.add_argument("--limit", type=int, help="max new images per set (for trial runs)")
    parser.add_argument("--delay", type=float, default=0.1, help="seconds between objects; the Met asks for at most 80 requests/s")
    parser.add_argument("--refresh", action="store_true", help="download the latest metadata CSV again (for periodic updates)")
    parser.add_argument("--recheck-skipped", action="store_true", help="re-check objects previously skipped as not public domain")
    run_pipeline("met", run, parser.parse_args())
