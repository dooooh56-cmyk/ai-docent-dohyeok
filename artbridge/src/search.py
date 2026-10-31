"""Exact cosine search over approved cross-region artwork embeddings."""

import argparse
import json
from os import PathLike

import numpy as np

from src.catalog import load_catalog, usable_image_rows
from src.compare_metadata import compare_metadata

OVERSEAS = {"China", "Japan", "India_Gandhara"}


def normalize_vectors(vectors):
    array = np.asarray(vectors, dtype=np.float64)
    if array.ndim not in (1, 2) or not np.isfinite(array).all():
        raise ValueError("Vectors must be finite one- or two-dimensional arrays")
    norms = np.linalg.norm(array, axis=-1, keepdims=True)
    if np.any(norms == 0):
        raise ValueError("Zero vectors cannot be normalized")
    return array / norms


def cosine_top_k(query_vector, gallery_vectors, artwork_ids, k=5):
    if k < 1:
        raise ValueError("k must be positive")
    ids = list(artwork_ids)
    if len(ids) != len(set(ids)):
        raise ValueError("Gallery artwork IDs must be unique")
    query = normalize_vectors(query_vector)
    if query.ndim != 1:
        raise ValueError("Query must be a one-dimensional vector")
    if not ids:
        if np.asarray(gallery_vectors).size:
            raise ValueError("Gallery vectors and IDs differ in length")
        return []
    gallery = normalize_vectors(gallery_vectors)
    if gallery.ndim != 2 or len(gallery) != len(ids) or gallery.shape[1] != len(query):
        raise ValueError("Gallery dimensions or artwork ID count do not match")
    scores = gallery @ query
    order = np.argsort(-scores, kind="stable")[:k]
    return [{"artwork_id": ids[i], "score": float(scores[i])} for i in order]


def _recommend_vector(query_vector, query_artwork, gallery, k=5, region_filter=None):
    if query_artwork.get("region") != "Korea":
        raise ValueError("Query artwork must be Korean")
    if region_filter is not None and region_filter not in OVERSEAS:
        raise ValueError("Invalid overseas region filter")
    query_id = query_artwork.get("artwork_id")
    query_group = query_artwork.get("split_group_id")
    query_hash = query_artwork.get("image_sha256")
    candidates = [row for row in gallery if row.get("region") in OVERSEAS
                  and (region_filter is None or row.get("region") == region_filter)
                  and row.get("artwork_id") != query_id
                  and not (query_group and row.get("split_group_id") == query_group)
                  and not (query_hash and row.get("image_sha256") == query_hash)]
    scores = cosine_top_k(query_vector, [r["vector"] for r in candidates], [r["artwork_id"] for r in candidates], k)
    by_id = {row["artwork_id"]: row for row in candidates}
    return [{**{key: value for key, value in by_id[item["artwork_id"]].items() if key != "vector"}, "score": item["score"], "metadata_comparison": compare_metadata(query_artwork, by_id[item["artwork_id"]], ("period", "material", "iconography", "pose"))} for item in scores]


def recommend_cross_region(query_image, query_artwork, gallery, model, k=5, region_filter=None):
    from src.embed import embed_image, load_image
    if query_artwork.get("region") != "Korea":
        raise ValueError("Query artwork must be Korean")
    image = load_image(query_image) if isinstance(query_image, (str, bytes, PathLike)) else query_image
    image_model, processor = model
    return _recommend_vector(embed_image(image, image_model, processor), query_artwork, gallery, k, region_filter)


def _load_saved_gallery(catalog_path, embeddings_path):
    rows = usable_image_rows(load_catalog(catalog_path), "local_research")
    catalog = {r["artwork_id"]: r for r in rows}
    if len(catalog) != len(rows):
        raise ValueError("Duplicate artwork IDs in catalog")
    with np.load(embeddings_path, allow_pickle=False) as saved:
        ids = saved["artwork_ids"].tolist()
        vectors = saved["vectors"]
        manifest = json.loads(str(saved["manifest"]))
    if len(ids) != len(vectors) or len(set(ids)) != len(ids):
        raise ValueError("Invalid embedding ID mapping")
    if set(ids) != set(catalog):
        raise ValueError("Approved catalog and embedding IDs differ; regenerate embeddings")
    if any(aid not in catalog or manifest.get("image_sha256", {}).get(aid) != catalog[aid].get("image_sha256") for aid in ids):
        raise ValueError("Embedding image hashes no longer match the approved catalog")
    gallery = [{**catalog[aid], "vector": vector} for aid, vector in zip(ids, vectors)]
    return catalog, ids, vectors, gallery, manifest


def search_saved_embeddings(catalog_path, embeddings_path, query_id, k=5, region_filter=None):
    catalog, ids, vectors, gallery, manifest = _load_saved_gallery(catalog_path, embeddings_path)
    if query_id not in catalog or query_id not in ids:
        raise ValueError("Query is not an approved catalog artwork with an embedding")
    query_vector = vectors[ids.index(query_id)]
    return {"model_id": manifest["model_id"], "data_version": manifest["data_version"], "results": _recommend_vector(query_vector, catalog[query_id], gallery, k, region_filter)}


def search_uploaded_image(catalog_path, embeddings_path, image, image_hash, model, processor, k=5, region_filter=None):
    from src.embed import embed_image
    _, _, _, gallery, manifest = _load_saved_gallery(catalog_path, embeddings_path)
    if getattr(model.config, "name_or_path", None) != manifest["model_id"]:
        raise ValueError("Query model and saved gallery model do not match")
    query = {"artwork_id": "uploaded_query", "region": "Korea", "image_sha256": image_hash}
    return {"model_id": manifest["model_id"], "data_version": manifest["data_version"], "results": _recommend_vector(embed_image(image, model, processor), query, gallery, k, region_filter)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Search saved embeddings for a Korean catalog artwork")
    parser.add_argument("catalog")
    parser.add_argument("embeddings")
    parser.add_argument("query_id")
    parser.add_argument("--region", choices=sorted(OVERSEAS))
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args()
    print(json.dumps(search_saved_embeddings(args.catalog, args.embeddings, args.query_id, args.k, args.region), ensure_ascii=False, indent=2))
