"""Classify full raw metadata into target sets using recorded query rules."""

import argparse
from pathlib import Path

import pandas as pd

MET_COLUMNS = ["Object ID", "Is Public Domain", "Department", "Object Name", "Title", "Culture", "Period", "Dynasty",
               "Artist Display Name", "Artist Nationality", "Object Date", "Object Begin Date", "Object End Date",
               "Medium", "Dimensions", "Classification", "Credit Line", "Link Resource", "Tags", "Metadata Date"]


def load_rules(path, source):
    rules = pd.read_csv(path, dtype=str)
    rules = rules[rules["source"] == source]
    if rules.empty or rules["set_name"].duplicated().any():
        raise ValueError(f"Missing or duplicate rules for source: {source}")
    return rules


def classify(raw, rules):
    raw = raw.fillna("")
    matched = []
    for rule in rules.itertuples():
        rows = raw.query(rule.query, engine="python")
        matched.append(rows.assign(set_name=rule.set_name, rule_query=rule.query))
    return pd.concat(matched, ignore_index=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Classify raw Met Open Access metadata with recorded query rules")
    parser.add_argument("raw_csv")
    parser.add_argument("--rules", default="data/classify_rules.csv")
    parser.add_argument("--output", default="data/classified/met_classified.csv")
    args = parser.parse_args()
    raw = pd.read_csv(args.raw_csv, dtype=str, usecols=MET_COLUMNS, encoding="utf-8-sig")
    result = classify(raw, load_rules(args.rules, "met"))
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False, encoding="utf-8-sig")
    summary = result.groupby("set_name")["Is Public Domain"].agg(total="size", public_domain=lambda s: (s == "True").sum())
    print(f"raw {len(raw)} rows -> {args.output}")
    print(summary.to_string())
