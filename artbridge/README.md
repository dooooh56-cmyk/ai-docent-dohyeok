# ArtBridge

한국 불교 조각을 기준으로 중국·일본·인도/간다라의 시각적으로 비슷한 소장품을 살펴보는 로컬 데모입니다.

## 실행

ArtBridge는 AI 도슨트 저장소의 `artbridge/` 폴더에서 별도로 관리합니다. 아래 명령은 모두 `artbridge/` 폴더에서 실행합니다.

이미지(`data/images/`)와 임베딩(`embeddings/`)은 저장소에 포함하지 않습니다. 새 환경에서는 먼저 권리 승인된 이미지를 기록된 출처 URL에서 다시 받습니다. 받은 파일의 SHA-256이 카탈로그 기록과 다르면 저장하지 않고 실패로 보고하며, 이 경우 권리·출처를 다시 확인해야 합니다. API 키는 필요하지 않습니다.

```bash
uv sync
uv run python -m src.fetch_images data/metadata.csv
```

그다음 아래 "임베딩 다시 만들기"로 두 모델의 임베딩을 생성하고 데모를 실행합니다.

```bash
uv run streamlit run app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

카탈로그의 한국 작품을 선택하거나 한국 작품 이미지 파일 또는 이미지 URL을 입력하고 DINOv2 또는 CLIP과 비교 권역을 고르면 코사인 유사도 Top-5와 확인된 메타데이터, 작품 출처를 보여줍니다. 직접 입력한 이미지는 질의 처리에만 사용하고 파일로 저장하지 않습니다. 직접 입력을 처음 실행할 때 선택한 모델 체크포인트를 내려받을 수 있습니다. 점수는 같은 모델 안에서의 상대적인 시각 유사도이며 역사적 관계의 증거가 아닙니다.

현재 카탈로그는 한국 5점, 중국 21점, 일본 10점, 인도/간다라 9점으로 구성됩니다. 원래 수집한 120개 후보 중 포함하지 않은 항목의 사유는 `data/import_report.csv`에 기록되어 있습니다. 권역별 균형과 사람 평가가 아직 충분하지 않습니다.

## 대량 수집 (메타데이터 전체 → 쿼리 분류 → 공개 이미지)

Met은 Open Access 전체 메타데이터 CSV(약 50만 건, 340MB, `data/raw/`에 저장하며 커밋하지 않음)를 받은 뒤 `data/classify_rules.csv`의 쿼리로 분류합니다. 분류 결과는 `data/classified/met_classified.csv`입니다. 이미지는 분류된 작품 중 Met 객체 API가 현재 `isPublicDomain=true`로 표기한 것만 받고, 사용자 일괄 승인 규칙으로 `data/collection/`의 카탈로그·권리 기록에 추가합니다. 중단 후 다시 실행하면 이미 받은 작품은 건너뜁니다.

```bash
curl -L -o data/raw/MetObjects.csv https://media.githubusercontent.com/media/metmuseum/openaccess/master/MetObjects.csv
```

```bash
uv run python -m src.classify data/raw/MetObjects.csv
```

```bash
uv run python -m src.collect.fetch_met_images data/classified/met_classified.csv --sets korea_painting foreign_painting japan_print
```

### e뮤지엄 (국립중앙박물관 등, API 키 필요)

아래 명령 하나로 네 단계를 순서대로 실행합니다. 어느 단계에서 멈췄든 같은 명령을 다시 실행하면 끝난 부분은 건너뛰고 이어서 진행하며, 실행 기록은 `data/logs/`에 남습니다. 동시에 두 번 실행되지 않도록 `data/raw/run_emuseum.lock`을 사용합니다. 정기 실행으로 바꿀 때는 같은 명령에 `--refresh`(목록을 처음부터 다시 수집)를 붙여 스케줄러에 등록하면 됩니다.

```bash
uv run python -m src.collect.run_emuseum
```

단계별로 따로 실행할 수도 있습니다. 목록 API는 국적·분류·재질을 코드로만 주므로, 코드마다 작품 페이지 2개를 읽어 표시된 이름(예: `PS06001018` → `한국 - 조선`)을 붙인 뒤 분류합니다. 이미지는 작품 페이지가 공공누리 제1유형으로 표기한 것만 받습니다. 목록 수집은 중단돼도 다시 실행하면 이어서 받습니다. API 키는 저장 파일과 오류 메시지에 남기지 않습니다.

```bash
uv run python -m src.collect.collect_emuseum
```

```bash
uv run python -m src.collect.emuseum_codes
```

```bash
uv run python -m src.classify data/raw/emuseum_list.jsonl --source emuseum
```

```bash
uv run python -m src.collect.fetch_emuseum_images --sets joseon_painting foreign_painting
```

## 후보 수집 (API 키)

`src/collect/`의 후보 수집기 중 e뮤지엄(`EMUSEUM_API_KEY`, data.go.kr 발급)과 Smithsonian(`SMITHSONIAN_API_KEY`, api.data.gov 발급)은 API 키가 필요합니다. Met과 Japan Search(ColBase)는 키가 필요하지 않습니다. 키는 `artbridge/.env`에 두며 저장소에 커밋하지 않습니다. 이미지 재다운로드에는 키가 필요하지 않습니다.

## 임베딩 다시 만들기

`data/metadata.csv`와 `data/license_log.csv`의 승인 상태 및 이미지 해시를 확인한 후, 동일한 데이터 버전을 사용해 두 모델을 생성합니다. 최초 실행 시 모델 체크포인트를 내려받습니다.

```bash
uv run python -m src.embed data/metadata.csv --model facebook/dinov2-base --data-version catalog-733d356e41c7 --output embeddings/dinov2.npz
uv run python -m src.embed data/metadata.csv --model openai/clip-vit-base-patch32 --data-version catalog-733d356e41c7 --output embeddings/clip.npz
```

현재 버전은 `catalog-733d356e41c7`입니다. 카탈로그가 바뀌면 두 명령에 같은 새 데이터 버전을 지정합니다. 모델 체크포인트·전처리·라이브러리 버전·이미지 해시는 각 결과 파일의 manifest에 저장됩니다. 카탈로그나 이미지가 바뀌면 두 모델의 임베딩을 다시 생성해야 합니다.
