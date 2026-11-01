"""Local ArtBridge demo using catalog images and saved embeddings."""

import hashlib
import io
import json
from pathlib import Path

import numpy as np
import requests
import streamlit as st
from PIL import Image, UnidentifiedImageError

from src.catalog import load_catalog, usable_image_rows
from src.search import search_saved_embeddings, search_uploaded_image

ROOT = Path(__file__).resolve().parent
CATALOG = ROOT / "data" / "metadata.csv"
MODELS = {"DINOv2": ROOT / "embeddings" / "dinov2.npz", "CLIP": ROOT / "embeddings" / "clip.npz"}
MODEL_IDS = {"DINOv2": "facebook/dinov2-base", "CLIP": "openai/clip-vit-base-patch32"}
REGIONS = {"전체": None, "중국": "China", "일본": "Japan", "인도/간다라": "India_Gandhara"}
FIELD_NAMES = {"period": "시대", "material": "재질", "iconography": "도상", "pose": "자세"}
REGION_NAMES = {"China": "중국", "Japan": "일본", "India_Gandhara": "인도/간다라"}


def get_query_image(rows, input_mode):
    if input_mode == "카탈로그":
        korean = [row for row in rows if row.get("region") == "Korea"]
        if not korean:
            st.info("사용 가능한 한국 작품이 없습니다.")
            return None, None, None
        query = st.selectbox("기준이 될 한국 작품", korean, format_func=lambda row: f"{row['title_original']} ({row['artwork_id']})")
        return query, None, None

    st.caption("사용 가능한 한국 작품 이미지를 선택하세요. 질의 이미지는 파일로 저장하지 않습니다.")
    uploaded = st.file_uploader("이미지 파일", type=("jpg", "jpeg", "png")) if input_mode == "파일 업로드" else None
    url = st.text_input("이미지 URL") if input_mode == "이미지 URL" else ""
    if not st.button("유사 작품 찾기"):
        return None, None, None
    if input_mode == "파일 업로드":
        if uploaded is None:
            st.info("이미지 파일을 선택하세요.")
            return None, None, None
        content = uploaded.getvalue()
        if len(content) > 20 * 1024 * 1024:
            raise ValueError("이미지는 20MB 이하여야 합니다.")
    else:
        content = read_image_url(url)
    with Image.open(io.BytesIO(content)) as source:
        image = source.convert("RGB")
    return {"artwork_id": "uploaded_query", "region": "Korea"}, image, hashlib.sha256(content).hexdigest()


def run_recommendation(query, model_name, region, image=None, image_hash=None):
    if image is None:
        return search_saved_embeddings(CATALOG, MODELS[model_name], query["artwork_id"], 5, region)
    with np.load(MODELS[model_name], allow_pickle=False) as saved:
        revision = json.loads(str(saved["manifest"]))["checkpoint_revision"]
    if not revision:
        raise ValueError("저장된 임베딩의 모델 리비전이 없습니다.")
    model, processor = load_model(model_name, revision)
    return search_uploaded_image(CATALOG, MODELS[model_name], image, image_hash, model, processor, 5, region)


@st.cache_resource
def load_model(model_name, revision):
    from transformers import AutoImageProcessor, AutoModel
    model_id = MODEL_IDS[model_name]
    return AutoModel.from_pretrained(model_id, revision=revision).eval(), AutoImageProcessor.from_pretrained(model_id, revision=revision)


def read_image_url(url):
    if not url.startswith(("https://", "http://")):
        raise ValueError("이미지 URL은 http 또는 https로 시작해야 합니다.")
    with requests.get(url, timeout=20, stream=True) as response:
        response.raise_for_status()
        content = bytearray()
        for chunk in response.iter_content(65536):
            content.extend(chunk)
            if len(content) > 20 * 1024 * 1024:
                raise ValueError("이미지는 20MB 이하여야 합니다.")
    return bytes(content)


def render_results(result):
    st.subheader("유사 작품 Top-5")
    st.caption("점수는 선택한 이미지 모델에서 계산한 상대적인 코사인 유사도입니다.")
    if not result["results"]:
        st.info("선택한 권역에 검색 가능한 작품이 없습니다.")
    for item in result["results"]:
        with st.container(border=True):
            left, right = st.columns([1, 2])
            with left:
                st.image(str(ROOT / item["image_path"]), width="stretch")
            with right:
                st.markdown(f"**{item['title_original']}**")
                st.write(f"{REGION_NAMES.get(item['region'], item['region'])} · 유사도 {item['score']:.3f}")
                for field in item["metadata_comparison"]:
                    st.write(f"{FIELD_NAMES[field['field']]}: {field['query_original'] or '미기재'} ↔ {field['candidate_original'] or '미기재'} ({field['status']})")
                st.link_button("공식 작품 페이지", item["object_page_url"])
                st.caption(f"이미지 출처: {item['image_credit']} · {item['image_license']}")


def main():
    st.set_page_config(page_title="ArtBridge", layout="wide")
    st.title("ArtBridge")
    st.write("한국 불교 조각과 시각적으로 닮은 해외 소장품을 살펴보세요.")
    try:
        rows = usable_image_rows(load_catalog(CATALOG), "local_research")
        input_mode = st.radio("입력 방식", ("카탈로그", "파일 업로드", "이미지 URL"), horizontal=True)
        model_name = st.selectbox("이미지 모델", list(MODELS))
        region_label = st.selectbox("비교 권역", list(REGIONS))
        query, image, image_hash = get_query_image(rows, input_mode)
        if not query:
            return
        if image is None:
            left, right = st.columns([1, 2])
            with left:
                st.image(str(ROOT / query["image_path"]), caption=query["title_original"], width="stretch")
            with right:
                st.write(f"시대: {query.get('period_original') or '미기재'}")
                st.write(f"재질: {query.get('material_original') or '미기재'}")
                st.link_button("기준 작품 원문 보기", query["object_page_url"])
                st.caption(f"이미지 출처: {query['image_credit']} · {query['image_license']}")
        else:
            st.image(image, caption="입력 이미지", width=300)
        result = run_recommendation(query, model_name, REGIONS[region_label], image, image_hash)
        render_results(result)
    except requests.RequestException:
        st.error("이미지 URL을 불러오지 못했습니다. 주소와 네트워크를 확인하세요.")
    except (OSError, ValueError, KeyError, UnidentifiedImageError) as error:
        st.error(f"카탈로그 또는 임베딩을 불러오지 못했습니다: {error}")


if __name__ == "__main__":
    main()
