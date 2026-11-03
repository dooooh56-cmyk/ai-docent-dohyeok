"""Create and save DINOv2 or CLIP image embeddings for approved catalog rows."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import PIL
from PIL import Image
import torch
import transformers
from transformers import AutoImageProcessor, AutoModel, CLIPModel
from transformers.utils import cached_file

from src.catalog import load_catalog, usable_image_rows, validate_catalog


def load_image(path):
    with Image.open(path) as image:
        return image.convert("RGB")


def embed_image(image, model, processor):
    inputs = processor(images=image, return_tensors="pt")
    with torch.inference_mode():
        if isinstance(model, CLIPModel):
            result = model.get_image_features(**inputs)
            vector = result if isinstance(result, torch.Tensor) else result.pooler_output
        else:
            vector = model(**inputs).last_hidden_state[:, 0, :]
    return vector[0].detach().cpu().numpy()


def embed_catalog(rows, model_id):
    usable = usable_image_rows(rows, "local_research")
    if not usable:
        raise ValueError("No approved local images are available")
    processor = AutoImageProcessor.from_pretrained(model_id)
    model = AutoModel.from_pretrained(model_id).eval()
    vectors, artwork_ids, failures = [], [], []
    for row in usable:
        try:
            vector = embed_image(load_image(row["image_path"]), model, processor)
            if not np.isfinite(vector).all() or not np.linalg.norm(vector):
                raise ValueError("invalid embedding")
            vectors.append(vector)
            artwork_ids.append(row["artwork_id"])
        except (OSError, ValueError) as error:
            failures.append({"artwork_id": row["artwork_id"], "error": str(error)})
    if not vectors:
        raise ValueError(f"No images embedded; failures: {failures}")
    config_path = Path(cached_file(model_id, "config.json", local_files_only=True))
    revision = config_path.parent.name if config_path.parent.parent.name == "snapshots" else getattr(model.config, "_commit_hash", None)
    manifest = {"model_id": model_id, "checkpoint_revision": revision, "processor": processor.to_dict(), "torch_version": torch.__version__, "transformers_version": transformers.__version__, "pillow_version": PIL.__version__, "numpy_version": np.__version__, "embedding_dimension": int(vectors[0].shape[0]), "image_sha256": {row["artwork_id"]: row["image_sha256"] for row in usable if row["artwork_id"] in artwork_ids}, "created_at": datetime.now(timezone.utc).isoformat(), "failures": failures}
    return np.stack(vectors), artwork_ids, manifest


def save_embeddings(vectors, artwork_ids, model_id, manifest, output_path):
    if len(vectors) != len(artwork_ids):
        raise ValueError("Embedding count and artwork ID count differ")
    if not manifest.get("data_version"):
        raise ValueError("manifest must include data_version")
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, vectors=vectors, artwork_ids=np.asarray(artwork_ids), manifest=json.dumps({**manifest, "model_id": model_id}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Embed approved catalog images")
    parser.add_argument("catalog")
    parser.add_argument("--model", required=True, choices=("facebook/dinov2-base", "openai/clip-vit-base-patch32"))
    parser.add_argument("--data-version", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    rows = load_catalog(args.catalog)
    errors = validate_catalog(rows)
    if errors:
        raise SystemExit("\n".join(errors))
    vectors, ids, manifest = embed_catalog(rows, args.model)
    manifest["data_version"] = args.data_version
    save_embeddings(vectors, ids, args.model, manifest, args.output)
    print(f"Saved {len(ids)} embeddings; {len(manifest['failures'])} failed: {args.output}")
