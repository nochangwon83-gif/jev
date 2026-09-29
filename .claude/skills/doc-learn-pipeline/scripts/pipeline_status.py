"""상태 복구(안전장치 8): manifest.jsonl의 파일별 상태로 어디서 멈췄는지와 다음 할 일을 보여준다.

각 단계 스크립트는 상태를 보고 대상만 고르므로, 중단된 뒤에는 여기 나온 명령을 다시 실행하면 이어진다.
  new/changed → classify_plan.py      planned → (CSV 승인 후) apply_plan.py
  applied     → 카드 작성(make_card)   carded  → verify_cards / notes_scaffold
  missing     → make_card.py --refresh 로 카드에 '원본 없음' 표시

또한 undo.log에서 적용했으나 되돌리지 않은 배치, 원본 대조 미통과 카드를 보여준다.

사용: python pipeline_status.py [--corpus legal|novel]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import load_config, load_manifest, read_undo_log, state_dir  # noqa: E402
from make_card import load_cards  # noqa: E402

NEXT = {
    "new": "python classify_plan.py --corpus {c} --mode auto",
    "changed": "python classify_plan.py --corpus {c} --mode auto (그리고 기존 카드는 개정 대상)",
    "planned": "계획 CSV 승인 후 python apply_plan.py <plan.csv>",
    "applied": "카드 작성(run_stage.py --stage S2l/S2n --files …)",
    "carded": "python verify_cards.py --all 후 notes_scaffold.py",
    "missing": "python make_card.py --refresh",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus")
    a = ap.parse_args()
    cfg = load_config()
    recs = [r for r in load_manifest(cfg).values() if not a.corpus or r["corpus"] == a.corpus]
    by = defaultdict(list)
    for r in recs:
        by[(r["corpus"], r["status"])].append(r["file_id"])
    print("# 파이프라인 상태\n")
    for (corpus, st), ids in sorted(by.items()):
        print(f"- {corpus} / {st}: {len(ids)}건 ({','.join(ids[:10])}{' …' if len(ids) > 10 else ''})")
        if st in NEXT:
            print(f"    다음: {NEXT[st].format(c=corpus)}")
    log = read_undo_log(cfg)
    undone = {e["batch"] for e in log if e["op"] == "undo"}
    open_batches = Counter(e["batch"] for e in log if e["op"] in ("copy", "move") and e["batch"] not in undone)
    print("\n# 되돌릴 수 있는 적용 배치")
    for b, n in open_batches.items():
        print(f"- {b}: {n}건  (python undo.py --batch {b})")
    dec = state_dir(cfg) / "jev_decisions.jsonl"
    if dec.exists():
        rows = [json.loads(l) for l in dec.read_text(encoding="utf-8").splitlines() if l.strip()]
        print("\n# jev 판단 기록(단계별 최종 등급 건수)")
        for (stage, tier), n in sorted(Counter((r["stage"], r["final_tier"]) for r in rows).items()):
            print(f"- {stage} → {tier}: {n}건")
        print(f"- jev가 직접 답한 판단: {sum(1 for r in rows if r.get('response'))}건 / 전체 {len(rows)}건")
    cards = load_cards(cfg)
    pending = [c["card_id"] for c in cards.values() if c["verification"] != "원문 대조 완료"]
    print(f"\n# 카드: {len(cards)}장, 원문 대조 미통과·미완료 {len(pending)}장 {pending}")


if __name__ == "__main__":
    main()
