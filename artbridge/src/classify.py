"""Classify full raw metadata into target sets using recorded query rules."""

import argparse
from pathlib import Path

import pandas as pd

MET_COLUMNS = ["Object ID", "Is Public Domain", "Department", "Object Name", "Title", "Culture", "Period", "Dynasty",
               "Artist Display Name", "Artist Nationality", "Object Date", "Object Begin Date", "Object End Date",
               "Medium", "Dimensions", "Classification", "Credit Line", "Link Resource", "Tags", "Metadata Date"]


def load_raw(source, path, codes_path=None):
    if source == "met":
        return pd.read_csv(path, dtype=str, usecols=MET_COLUMNS, encoding="utf-8-sig")
    raw = pd.read_json(path, lines=True, dtype=str).fillna("")
    codes = pd.read_csv(codes_path, dtype=str, encoding="utf-8-sig").fillna("")
    for field, column in (("nationalityCode", "nationality_label"), ("purposeCode", "purpose_label"), ("materialCode", "material_label")):
        labels = codes[codes["code_field"] == field].set_index("code")["label"]
        raw[column] = raw[field].map(labels).fillna("") if field in raw else ""
    return raw


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
    parser = argparse.ArgumentParser(description="Classify raw institution metadata with recorded query rules")
    parser.add_argument("raw", help="Met Open Access CSV, or eMuseum list JSON Lines")
    parser.add_argument("--source", choices=("met", "emuseum"), default="met")
    parser.add_argument("--codes", default="data/raw/emuseum_codes.csv", help="eMuseum code labels from emuseum_codes.py")
    parser.add_argument("--rules", default="data/classify_rules.csv")
    parser.add_argument("--output")
    args = parser.parse_args()
    args.output = args.output or f"data/classified/{args.source}_classified.csv"
    raw = load_raw(args.source, args.raw, args.codes)
    result = classify(raw, load_rules(args.rules, args.source))
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False, encoding="utf-8-sig")
    summary = result.groupby("set_name").size().rename("total").to_frame()
    if "Is Public Domain" in result:
        summary["public_domain"] = result.groupby("set_name")["Is Public Domain"].agg(lambda s: (s == "True").sum())
    print(f"raw {len(raw)} rows -> {args.output}")
    print(summary.to_string())
