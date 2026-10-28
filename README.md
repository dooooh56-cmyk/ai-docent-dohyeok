# ArtBridge

한국 불교 조각을 기준으로 중국·일본·인도/간다라의 시각적으로 비슷한 소장품을 살펴보는 로컬 데모입니다.

## 실행

프로젝트 루트에서 다음 명령을 실행합니다.

```bash
uv sync
uv run streamlit run app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

카탈로그의 한국 작품을 선택하거나 한국 작품 이미지 파일 또는 이미지 URL을 입력하고 DINOv2 또는 CLIP과 비교 권역을 고르면 코사인 유사도 Top-5와 확인된 메타데이터, 작품 출처를 보여줍니다. 직접 입력한 이미지는 질의 처리에만 사용하고 파일로 저장하지 않습니다. 직접 입력을 처음 실행할 때 선택한 모델 체크포인트를 내려받을 수 있습니다. 점수는 같은 모델 안에서의 상대적인 시각 유사도이며 역사적 관계의 증거가 아닙니다.

현재 카탈로그는 한국 5점, 중국 21점, 일본 10점, 인도/간다라 9점으로 구성됩니다. 원래 수집한 120개 후보 중 포함하지 않은 항목의 사유는 `data/import_report.csv`에 기록되어 있습니다. 권역별 균형과 사람 평가가 아직 충분하지 않습니다.

## 임베딩 다시 만들기

`data/metadata.csv`와 `data/license_log.csv`의 승인 상태 및 이미지 해시를 확인한 후, 동일한 데이터 버전을 사용해 두 모델을 생성합니다. 최초 실행 시 모델 체크포인트를 내려받습니다.

```bash
uv run python -m src.embed data/metadata.csv --model facebook/dinov2-base --data-version catalog-733d356e41c7 --output embeddings/dinov2.npz
uv run python -m src.embed data/metadata.csv --model openai/clip-vit-base-patch32 --data-version catalog-733d356e41c7 --output embeddings/clip.npz
```

현재 버전은 `catalog-733d356e41c7`입니다. 카탈로그가 바뀌면 두 명령에 같은 새 데이터 버전을 지정합니다. 모델 체크포인트·전처리·라이브러리 버전·이미지 해시는 각 결과 파일의 manifest에 저장됩니다. 카탈로그나 이미지가 바뀌면 두 모델의 임베딩을 다시 생성해야 합니다.
