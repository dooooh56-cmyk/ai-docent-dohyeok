"""Find how deep one eMuseum list query can be paged and which filters narrow it, without printing the API key.

1. totalCount with no filter.
2. Single-row requests at increasing offsets: where the API starts refusing.
3. totalCount for nationality/purpose codes whose sampled labels mention the given words, and for their parent
   codes (codes are hierarchical, e.g. PS06001018 under PS06001). A filter the API ignores returns the unfiltered total.
"""

import argparse
import time

import pandas as pd
import requests

from src.collect.collect_emuseum import ApiError, api_key, fetch_page
from src.fetch_images import USER_AGENT

OFFSETS = [1000, 5000, 10000, 15000, 20000, 21000, 25000, 30000, 50000]


def total_for(session, key, filters):
    try:
        total, _ = fetch_page(session, key, 1, 1, filters, retries=1)
        return str(total)
    except ApiError as error:
        return f"refused: {error}"


def row_at(session, key, offset):
    try:
        _, items = fetch_page(session, key, offset + 1, 1, None, retries=1)
        return "ok" if items else "empty"
    except ApiError as error:
        return f"refused: {str(error)[:120]}"


def parents(code):
    """PS06001018 -> PS06001018, PS06001 (codes grow by three digits per level after the first five characters)."""
    out = [code]
    while len(out[-1]) > 7:
        out.append(out[-1][:-3])
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Probe eMuseum list paging depth and filters")
    parser.add_argument("--codes", default="data/raw/emuseum_codes.csv")
    parser.add_argument("--words", nargs="+", default=["회화", "조선"])
    args = parser.parse_args()
    key = api_key()
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    unfiltered = total_for(session, key, None)
    print(f"unfiltered totalCount: {unfiltered}")
    print("\nsingle row at offset:")
    for offset in OFFSETS:
        print(f"  {offset}: {row_at(session, key, offset)}", flush=True)
        time.sleep(0.3)
    codes = pd.read_csv(args.codes, dtype=str, encoding="utf-8-sig").fillna("")
    wanted = codes[codes["code_field"].isin(["nationalityCode", "purposeCode"]) & codes["label"].str.contains("|".join(args.words))]
    print("\nfilter -> totalCount (same as unfiltered = filter ignored):")
    tried = set()
    for row in wanted.itertuples():
        for code in parents(row.code):
            if (row.code_field, code) in tried:
                continue
            tried.add((row.code_field, code))
            label = row.label if code == row.code else "(parent)"
            print(f"  {row.code_field}={code} {label}: {total_for(session, key, {row.code_field: code})}", flush=True)
            time.sleep(0.3)
