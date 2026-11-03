
import time
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

BASE_URL = "https://collectionapi.metmuseum.org/public/collection"
SEARCH_URL = f"{BASE_URL}/v1.1/search"
OBJECT_URL = f"{BASE_URL}/v1/objects"
MET_OPEN_ACCESS_URL = "https://www.metmuseum.org/policies/image-resources"

KEYWORDS = ["Buddha", "Bodhisattva"]
PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR.mkdir(exist_ok=True)

session = requests.Session()


def search_artwork_ids(keyword: str, limit: int = 50) -> list[int]:
    """검색어에 해당하는 작품 ID 목록을 조회한다."""
    response = session.get(
        SEARCH_URL,
        params={
            "q": keyword,
            "hasImages": "true",
            "limit": limit,
            "offset": 0,
        },
        timeout=20,
    )
    response.raise_for_status()

    data = response.json()
    return data.get("objectIDs") or []


def fetch_artwork(object_id: int) -> Optional[dict]:
    """작품 상세 정보를 가져와 필요한 필드만 추출한다."""
    response = session.get(
        f"{OBJECT_URL}/{object_id}",
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()

    if not data.get("isPublicDomain"):
        return None

    if not data.get("primaryImage"):
        return None

    return {
        "artwork_id": f"MET_{object_id}",
        "title": data.get("title"),
        "culture": data.get("culture"),
        "period": data.get("period"),
        "material": data.get("medium"),
        "object_type": data.get("objectName"),
        "museum": "The Metropolitan Museum of Art",
        "image_url": data.get("primaryImageSmall"),
        "source_url": data.get("objectURL"),
        "image_credit": data.get("creditLine"),
        "image_license": "CC0 (The Met Open Access)",
        "license_url": MET_OPEN_ACCESS_URL,
        "api_is_public_domain": True,
        "rights_status": "unverified",
        "rights_checked_at": "",
        "api_rights_accessed_at": date.today().isoformat(),
        "metadata_accessed_at": date.today().isoformat(),
    }


def main():
    all_ids = set()

    for keyword in KEYWORDS:
        ids = search_artwork_ids(keyword)
        all_ids.update(ids)
        time.sleep(0.5)

    records = []

    for object_id in sorted(all_ids):
        try:
            artwork = fetch_artwork(object_id)

            if artwork is not None:
                records.append(artwork)

            if len(records) >= 30:
                break

        except requests.RequestException as error:
            print(f"조회 실패: {object_id}: {error}")

        finally:
            time.sleep(0.5)

    df = pd.DataFrame(records)

    if df.empty:
        print("수집된 작품이 없습니다.")
        return

    df = df.drop_duplicates(subset=["artwork_id"])

    output_path = OUTPUT_DIR / "met_candidates.csv"
    df.to_csv(output_path, index=False, encoding="utf-8-sig")

    print(f"후보 작품 수집 완료: {len(df)}점")
    print(df[["title", "culture", "period"]].head())
    print(f"저장 경로: {output_path}")


if __name__ == "__main__":
    main()
