---
name: doc-learn-pipeline
description: 법무자료(D:\법무 자료 및 ai산출물)와 웹소설 자료(C:\소설모음)를 ① 분류(제목·내용 모드, 계획 CSV 승인 후 복사) ② 원문 인용·위치가 붙은 학습자료 카드 ③ 카드 ID로 추적되는 주제별 학습노트 ④ 기존 법률·웹소설 스킬 반영 제안서로 만드는 5단계 파이프라인. 단계마다 사용자 승인에서 멈추고, TypeSafe Jev가 단계의 경중을 판단해 모델 등급(haiku/sonnet/opus)을 골라 실행한다. 경중표 기준 등급의 jev 보정(사람 승인)도 한다. "자료 분류해줘", "학습 카드 만들어줘", "학습노트", "스킬에 반영할 제안서", "경중표 보정", "jev 보정", "jev 점검", "doc-learn-pipeline" 요청에 사용.
---

# doc-learn-pipeline

문서·파일을 분류하고 학습한 뒤 기존 법률 스킬과 웹소설 스킬에 **제안서 형태로** 반영하는 스킬이다.
스크립트는 이 스킬 폴더의 `scripts/`에 있고 표준 라이브러리만 쓴다(PDF는 `pypdf`가 있으면 사용, 없으면 PDF 본문 = 확인 불가).

**사용자는 명령어를 치지 않는다.** 사용자가 말로 요청하면 Claude가 아래 명령을 직접 실행하고, ⏸ 승인 지점에서 결과를 보여주고 멈춘다.
명령은 `python "<이 스킬 폴더>/scripts/<파일>.py" …` 형태로 실행한다(Windows에서 `python`이 없으면 `py`).

## 요청별 실행 절차

| 사용자가 이렇게 말하면 | Claude가 실행 |
|---|---|
| (모든 요청의 첫 실행) | `doctor.py` — 준비 점검. 막힌 항목을 사용자에게 알리고, 없어도 되는 항목(pypdf·hwp5txt·jev)이면 그 사실을 밝힌 뒤 계속한다 |
| "jev 점검", "준비됐어?" | `doctor.py` 결과를 표로 보고 |
| "키 저장해줘" | 키는 채팅에 붙이지 말고 사용자가 직접 입력하도록 안내: 터미널에서 `python doctor.py --save-key`. 사용자가 이미 채팅에 키를 줬다면 `echo <키> \| python doctor.py --save-key`로 저장하고 키 재발급을 권한다. 키 값은 절대 다시 출력하지 않는다 |
| "경중표 보정해줘", "jev 보정" | `calibrate_table.py propose` → 수정안 표를 보여주고 ⏸ 어떤 단계를 반영할지 묻는다 → 사용자가 고른 단계만 `calibrate_table.py apply --proposal <json> --approve <단계> --confirm "승인함"` |
| "자료 스캔", "폴더 분석" | `scan.py --corpus legal\|novel --root <폴더> --check-pdf` (처음엔 작은 하위 폴더를 사용자에게 물어 정한다) → ⏸ |
| "분류해줘" | 모드(title/content/auto)를 묻고 `classify_plan.py` → 계획 CSV를 보여주고 ⏸ 사용자가 승인한 행 번호를 CSV '승인' 열에 Y로 적은 뒤 `apply_plan.py` |
| "되돌려줘" | `pipeline_status.py`로 배치 확인 → `undo.py --batch <배치>` |
| "카드 만들어줘", "학습노트", "제안서" | 아래 **모델 등급 선택** 후 해당 단계 수행 |
| "어디까지 했지?" | `pipeline_status.py` |

## 모델 등급 선택 (모델을 쓰는 단계: S1a~S5)

1. `run_stage.py --stage <ID> --files <번호>`를 실행한다(`--execute` 없이). jev가 경중(0~3)과 등급을 판단하고
   코드 규칙으로 확정한 **최종 등급·모델**과 **단계 프롬프트**가 출력된다.
   - 키가 없거나 jev에 연결되지 않으면 경중표 기준 등급으로 진행한다(출력에 사유 표시).
   - jev 신뢰도가 낮으면 경중표보다 낮추지 않고, 경중 점수가 더 높은 등급을 가리키면 높은 쪽을 쓴다.
   - strong 고정 단계(S2l 법률 인용, S5 스킬 반영)는 항상 opus.
   - 판단 근거는 작업 폴더 `_state/jev_decisions.jsonl`에 남는다.
2. **하위 에이전트 도구(Agent/Task)가 있으면** 출력된 모델(haiku/sonnet/opus)을 지정해 하위 에이전트를 띄우고
   단계 프롬프트와 이 SKILL.md의 해당 단계 규칙을 넘긴다. 하위 에이전트는 승인 지점 직전까지 작업하고 결과를 돌려준다.
   그 결과를 사용자에게 보여주고 ⏸ 승인을 받는다(하위 에이전트는 사용자 승인을 대신하지 않는다).
3. 하위 에이전트 도구가 없으면 현재 세션에서 직접 수행하고, "jev가 고른 등급(예: haiku)과 현재 세션 모델이 다르다"는 사실을 사용자에게 알린다.
4. 사용자가 터미널에서 직접 쓰는 경우에만 `--execute`로 `claude --model <모델>` 새 세션을 띄운다(세션 안에서 스킬로 실행할 때는 쓰지 않는다).

## 절대 규칙

1. **원본은 읽기만 한다.** 삭제·덮어쓰기 금지. 이동은 사용자가 명시할 때만(`--move --confirm-move "이동에 동의"`).
2. **승인 지점에서 멈춘다.** ⏸ 표시마다 결과를 보여주고 사용자의 승인을 받은 뒤에만 다음으로 간다. 승인 문구(`--confirm "승인함"`, CSV의 Y)는 사용자가 실제로 승인했을 때만 넣는다.
3. **확인하지 않은 내용을 사실처럼 쓰지 않는다.** 원문에서 확인하지 못한 값은 `확인 불가`로 쓴다.
4. **jev(TypeSafe)로 가는 정보는 단계 작업 설명과 파일 개수·형식만.** 문서 본문·인용문·사건명·당사자명·파일명·파일 번호를 보내지 않는다.
   본문은 세션 안에서 파일 번호 → manifest 경로로 원본을 직접 읽어 처리한다.
5. **기존 스킬(SKILL.md)을 직접 고치지 않는다.** 제안서만 만든다. 적용은 사용자가 항목 ID를 골라 승인할 때만.

## 설정과 작업 폴더

- **작업 폴더**: 상태(`_state`)·산출물(`_output`)·제안서·백업·`.env`·사용자 설정을 두는 곳. 스킬 폴더에 쓸 수 있으면 스킬 폴더,
  읽기 전용이면(업로드해 설치한 스킬) `홈 폴더\.doc-learn-pipeline`. `doctor.py`가 위치를 알려준다.
- `config.json`(스킬 기본값) 위에 작업 폴더의 `config.json`이 덮어쓴다. 경로·금지어·기존 스킬 위치를 바꿀 때는 작업 폴더 쪽에 쓴다.
  키: 자료 루트(`roots`), 정리본 위치(`dest_roots`), 기존 스킬 위치(`skill_dirs`), 금지어(`sensitive_terms`), 상한값, `jev_min_confidence`, `claude_models`.
- `.env`: `JEV_API_KEY=` — 작업 폴더에 둔다(`doctor.py --save-key`). 저장소에 올리지 않는다.
- `references/classification-rules.md`: 분류 체계(기존 상위 폴더 유지) + 키워드 규칙(초안).
- `references/severity-table.md`: 단계별 작업 설명(jev에 전달)과 기준 등급. 보정을 반영하면 작업 폴더의 사본(`severity-table.md`)이 우선한다.
- `references/user-guidelines.json`: 충돌 검사용 기존 지침.

## 단계별 명령과 규칙

### 0. 스캔 (S0, 모델 미사용)
```
python scan.py --corpus legal --check-pdf      # 처음엔 --root 로 작은 폴더 하나부터
```
형식별 개수·hwp 포함 여부·스캔 PDF 의심 건수를 보고한다. ⏸ **보고서를 보여주고 승인받는다.**

### 1. 분류 계획 → 적용 (S1a/S1b/S1c)
```
python classify_plan.py --corpus legal --mode auto     # title | content | auto 중 사용자가 고른다
```
- 모드는 **사용자에게 묻고** 정한다. 기본 제안은 `auto`(제목 모드 후 신뢰도 미달만 내용 모드).
- 신뢰도 미달 행(S1c)은 원본을 직접 읽어 제안 경로·근거를 고쳐 **제안**만 한다.
- ⏸ **계획 CSV를 보여주고, 사용자가 '승인' 열에 Y를 적은 뒤에만** 적용한다.
```
python apply_plan.py <plan.csv>          # 승인 행만, 복사, 해시 검증, undo.log 기록
python undo.py --batch <배치>             # 되돌리기(복사본을 _state/undo_trash로 옮김, 원본 무변경)
```
⏸ 적용 결과를 보고하고 승인받는다.

### 2. 학습자료 카드 (S2l 법무 = strong 고정 / S2n 웹소설 = balanced)
1. 파일 번호로 원본을 직접 읽는다(`python extract_text.py <경로>`로 위치 표기 확인).
2. `references/card-template.md`대로 초안 JSON을 쓴다.
   - 인용은 **원문 그대로**, 위치(`p.N`/`문단 N`/`줄 N`)를 붙인다. 모르면 `확인 불가`.
   - 웹소설 인용은 40자 이하·3건 이하(스크립트가 거부한다). 분석과 짧은 위치 표기 중심.
3. `python make_card.py --draft 초안.json` → `python verify_cards.py --cards C-000N`
   통과해야 `원문 대조 완료`. 실패 인용은 `확인 불가`로 표시되고 반영 제안에서 빠진다.
4. 원본 변경·삭제 반영: `python scan.py …` 후 `python make_card.py --refresh`.
⏸ 카드 목록과 대조 결과를 보여주고 승인받는다.

### 3. 주제별 학습노트 (S3 strong) + 표본 검증 (S4, 다른 세션)
```
python notes_scaffold.py
```
- 사실란은 카드 요지를 카드 ID와 함께 옮긴다. 패턴은 `패턴(근거 카드 N건): … [C-0001][C-0002].` 형식으로만,
  근거 카드가 `pattern_min_cards`(기본 3) 미만이면 `사례 적음`. 카드로 뒷받침되지 않으면 `확인 불가` 절에 둔다.
- **모든 문장에 카드 ID**를 단다.
```
python verify_cards.py --sample 5 --notes ../_output/notes    # 작성한 세션과 다른 세션에서
```
⏸ 노트와 검증 결과를 보여주고 승인받는다.

### 4. 스킬 반영 제안서 (S5 strong 고정)
대상: 법률 `domestic-construction-contract-review`, `overseas-english-contract-review`, `all-party-contract-review`,
`litigation-review`, `litigation-drafting`, `litigation-document-review` / 웹소설 `webnovel-writer`, `novel-agents`.
실제 위치는 `config.json`의 `skill_dirs`에 적는다(모르면 사용자에게 묻는다 — 추측 금지).
1. 학습노트와 대상 SKILL.md를 대조해 제안 초안 JSON을 쓴다(항목마다 변경 전·후 문구와 근거 카드 ID).
2. `python propose_skill_update.py --draft 제안초안.json` → `_proposals/<스킬>_<날짜>.md`
   기존 지침 충돌·원문 대조 미통과 카드·변경 전 문구 불명확 항목은 **표시하고 제외**한다.
⏸ **제안서를 보여주고, 사용자가 항목 ID를 고를 때까지 멈춘다.**
3. 사용자가 고른 항목만: `python apply_skill_update.py --proposal <json> --approve P1,P2 --confirm "승인함"`
   적용 전 SKILL.md를 `_backup/`에 보관하고 `_state/skill_changelog.md`에 기록한다.

## 파일 구조

명세서 3장의 파일에 더해, 되돌리기·승인·점검을 스크립트로 분리했다(★ = 명세서 3장에 없던 추가 파일).

```
doc-learn-pipeline/
  SKILL.md  config.json★  .env.example★  .gitignore★
  references/  classification-rules.md  card-template.md  severity-table.md
               stage-prompts.md★(단계 프롬프트 템플릿)  user-guidelines.json★(충돌 검사용 기존 지침)
  scripts/     scan.py  extract_text.py  apply_plan.py  verify_cards.py
               common.py★  classify_plan.py★  undo.py★  make_card.py★  notes_scaffold.py★
               propose_skill_update.py★  apply_skill_update.py★  check_prompts.py★  run_stage.py★  jev_route.py★  calibrate_table.py★  doctor.py★  pipeline_status.py★
  tests/       make_samples.py★(가상 샘플 10개)  test_pipeline.py★(안전장치 테스트)
  _state/      manifest.jsonl  undo.log  (실행 시 생성, 저장소 제외)
```

테스트: 스킬 폴더에서 `python -m unittest tests/test_pipeline.py`

## 중단 후 재개

`python pipeline_status.py` — 파일별 상태, 되돌릴 수 있는 배치, 미검증 카드를 보여주고 다음 명령을 알려준다.

## 안전장치 대응표 (명세서 9장)

| # | 안전장치 | 구현 |
|---|---|---|
| 1 | 미리보기 우선 | `classify_plan.py`는 CSV만 작성, `apply_plan.py`는 승인 열 Y 행만 적용 |
| 2 | 원본 보존 | 삭제 코드 없음(이동 명시 시만 원본 제거), 같은 이름은 ` (2)` 부여, 정리본 폴더 밖·원본 경로로 쓰기 거부 |
| 3 | 되돌리기 | `undo.log`(배치 단위) + `undo.py`(복사본을 휴지통 폴더로, 이동은 원위치 복원) |
| 4 | 해시 검증 | 적용 전 원본 해시 = 스캔 해시, 적용 후 복사본 해시 = 원본 해시, 다르면 중단 |
| 5 | 원문 대조 | `verify_cards.py`(인용·조항 문언·위치 재확인, 노트 문장별 카드 ID), 미통과 카드는 제안에서 제외 |
| 6 | 사람 승인 | `propose_skill_update.py`는 SKILL.md 무변경, `apply_skill_update.py`는 항목 ID + 확인 문구 필요, 백업·이력. 경중표 보정도 같은 방식(`calibrate_table.py propose/apply`) |
| 7 | 외부 전송 통제 | jev 요청 state는 경중표 작업 설명 + 파일 개수·형식만(`jev_route.build_request`), 전송 직전 `check_prompts.check_text`로 점검해 위반 시 전송 안 함. 단계 프롬프트 템플릿도 T1~T8 점검 |
| 8 | 상태 복구 | `manifest.jsonl` 상태값, 단계 스크립트는 상태로 대상 선택·이미 적용된 행 건너뜀, `pipeline_status.py` |

## 확인 불가 사항 (구축 시점 2026-09-29)

- 실제 Jev API 응답. 구축 환경의 네트워크 정책이 `api.typesafe.ai`·`docs.typesafe.ai`를 막아(프록시 403) 실제 호출은 해 보지 못했다.
  요청 형식은 공식 Python SDK `typesafe-sdk` 0.7.2 소스(PyPI)에서 확인했고, 같은 형식을 흉내 낸 로컬 서버로 테스트했다.
- jev 경중 판단의 정확도(실제 사용 기록 `_state/jev_decisions.jsonl`로 확인·조정 필요).
- `jev` CLI(`jev doctor`/`jev try`/`jev stats`)는 쓰지 않는다. npm `jev-router` 0.3.0에는 그런 명령이 없고(`jev-codex`/`jev-claude`/`jev-explain`만 있음), `jev-auto`는 npm에서 찾을 수 없었다(404).
- 실제 자료 폴더의 형식별 개수(사용자 PC에서 `scan.py --check-pdf`로 집계해야 함).
- hwp 본문 추출(`hwp5txt`가 있을 때만), hwpx 추출은 실제 파일로 시험하지 않음.
- 기존 스킬의 SKILL.md 실제 위치(`skill_dirs`).
