"""Diagnose eMuseum image downloads without printing the API key.

Fetches a few list records and tries each image URL two ways: exactly as the API returned it, and with the
serviceKey replaced by the local key (what fetch_emuseum_images does today).
"""

import argparse
from urllib.parse import parse_qsl, urlsplit

import requests

from src.collect.collect_emuseum import API_URL, api_key, parse_page
from src.collect.fetch_emuseum_images import with_key
from src.fetch_images import USER_AGENT


def describe(response):
    return f"HTTP {response.status_code}, {response.headers.get('Content-Type', '')}, {len(response.content)} bytes, starts {response.content[:4]!r}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check how eMuseum image URLs respond")
    parser.add_argument("--name", default="회화")
    parser.add_argument("--count", type=int, default=2)
    args = parser.parse_args()
    key = api_key()
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    response = session.get(API_URL, params={"serviceKey": key, "numOfRows": 10, "pageNo": 1, "name": args.name}, timeout=60)
    response.raise_for_status()
    _, items = parse_page(response.text)
    items = [item for item in items if item.get("imgUri")][:args.count]
    if not items:
        raise SystemExit("No list records with imgUri returned")
    for item in items:
        url = item["imgUri"]
        embedded = dict(parse_qsl(urlsplit(url).query)).get("serviceKey", "")
        print(f"\n{item.get('id')} {item.get('nameKr')}")
        print(f"  host: {urlsplit(url).scheme}://{urlsplit(url).netloc}{urlsplit(url).path}")
        print(f"  embedded serviceKey: {'absent' if not embedded else 'same as local key' if embedded == key else 'DIFFERENT from local key'}")
        for label, target in (("as returned", url), ("with local key", with_key(url, key))):
            try:
                print(f"  {label}: {describe(session.get(target, timeout=60))}")
            except requests.RequestException as error:
                print(f"  {label}: {type(error).__name__}")
