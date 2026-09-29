# 단계 프롬프트 템플릿

이 프롬프트는 `run_stage.py --execute`가 jev가 고른 모델로 띄우는 **새 Claude Code 세션의 첫 프롬프트**다.
jev(TypeSafe)에는 이 프롬프트가 아니라 경중표의 작업 설명과 파일 개수·형식만 간다(`jev_route.py`).
그래도 템플릿에는 **작업 유형과 파일 번호만** 넣는다. 문서 본문·인용문·사건명·당사자명·파일명·경로는 넣지 않는다.
본문은 Claude가 세션 안에서 manifest의 파일 번호로 원본을 찾아 직접 읽는다.

허용 자리표시자: `{stage_id}` `{task_type}` `{file_ids}` `{tier}` — 다른 자리표시자는 `check_prompts.py`가 거부한다.
`{task_type}`은 severity-table.md의 '단계 작업' 열 값(고정 문구)으로 채워진다.

```prompt S0
doc-learn-pipeline {stage_id} 단계({task_type})다. 모델 판단 없이 scan.py만 실행하고 보고서를 보여준 뒤 승인 지점에서 멈춘다.
```

```prompt S1a
doc-learn-pipeline {stage_id} 단계({task_type}), 배정 등급 {tier}. 대상 파일 번호: {file_ids}. classify_plan.py --mode title로 계획 CSV를 만들고 신뢰도 미달 행을 표시한 뒤 승인 지점에서 멈춘다.
```

```prompt S1b
doc-learn-pipeline {stage_id} 단계({task_type}), 배정 등급 {tier}. 대상 파일 번호: {file_ids}. classify_plan.py --mode content로 계획 CSV를 만든 뒤 승인 지점에서 멈춘다.
```

```prompt S1c
doc-learn-pipeline {stage_id} 단계({task_type}), 배정 등급 {tier}. 대상 파일 번호: {file_ids}. 계획 CSV의 해당 행만 원본을 직접 읽어 제안 경로와 근거를 고쳐 제안하고 승인 지점에서 멈춘다.
```

```prompt S2n
doc-learn-pipeline {stage_id} 단계({task_type}), 배정 등급 {tier}. 대상 파일 번호: {file_ids}. card-template.md에 따라 초안 JSON을 쓰고 make_card.py로 등록한 뒤 verify_cards.py를 실행하고 멈춘다. 인용은 짧게.
```

```prompt S2l
doc-learn-pipeline {stage_id} 단계({task_type}), 배정 등급 {tier}. 대상 파일 번호: {file_ids}. card-template.md에 따라 초안 JSON을 쓰고 make_card.py로 등록한 뒤 verify_cards.py를 실행하고 멈춘다.
```

```prompt S3
doc-learn-pipeline {stage_id} 단계({task_type}), 배정 등급 {tier}. notes_scaffold.py로 노트 틀을 만들고 카드에 근거한 문장만 보완한 뒤 verify_cards.py --notes를 실행하고 멈춘다.
```

```prompt S4
doc-learn-pipeline {stage_id} 단계({task_type}), 배정 등급 {tier}. 작성 세션과 다른 이 세션에서 verify_cards.py --sample을 실행하고 결과만 보고한다.
```

```prompt S5
doc-learn-pipeline {stage_id} 단계({task_type}), 배정 등급 {tier}. 원문 대조 완료 카드와 학습노트만 근거로 제안 초안 JSON을 쓰고 propose_skill_update.py를 실행한 뒤 승인 지점에서 멈춘다. SKILL.md는 고치지 않는다.
```
