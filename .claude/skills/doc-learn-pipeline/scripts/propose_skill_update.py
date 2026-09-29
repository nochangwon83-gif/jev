"""스킬 반영 제안서 작성(7장). 대상 SKILL.md를 절대 수정하지 않는다.

입력: Claude가 학습노트와 대상 SKILL.md를 대조해 쓴 초안 JSON
  {"skill": "litigation-review",
   "items": [{"id": "P1", "type": "추가|수정|삭제", "before": "...", "after": "...",
              "card_ids": ["C-0001"], "reason": "..."}]}
  추가: before = 새 문구를 뒤에 붙일 기존 문구(기준점), after = 새 문구
  수정: before를 after로 바꾼다    삭제: before를 지운다(after는 빈 값)

검사(하나라도 걸리면 그 항목은 '제외'로 표시)
  - before가 현재 SKILL.md에 정확히 한 번 나오는가
  - 근거 카드가 있고 모두 '원문 대조 완료'인가(안전장치 5)
  - references/user-guidelines.json의 기존 지침과 충돌하는가(충돌·수동 확인은 표시 후 제외)

출력: _proposals/<스킬명>_<날짜>.md(읽기용)와 같은 이름의 .json(apply_skill_update.py 입력)

사용: python propose_skill_update.py --draft 초안.json [--skill-path 경로/SKILL.md]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import SKILL_DIR, UNKNOWN, _resolve, load_config, now, sha256_file  # noqa: E402
from make_card import load_cards  # noqa: E402


def find_skill(cfg: dict, name: str) -> Path | None:
    for d in cfg.get("skill_dirs", []):
        for cand in [Path(d) / name / "SKILL.md", *Path(d).glob(f"**/{name}/SKILL.md")]:
            if cand.exists():
                return cand
    return None


def guideline_hits(skill: str, text: str) -> list[str]:
    rules = json.loads((SKILL_DIR / "references" / "user-guidelines.json").read_text(encoding="utf-8"))["rules"]
    hits = []
    for r in rules:
        if r["skills"] != "*" and skill not in r["skills"]:
            continue
        if r.get("conflict_regex") and re.search(r["conflict_regex"], text):
            hits.append(f"충돌 {r['id']}: {r['지침']}")
        if r.get("trigger_regex") and re.search(r["trigger_regex"], text) and r["require"] not in text:
            hits.append(f"충돌 {r['id']}: {r['지침']} ('{r['require']}' 없음)")
        if r.get("manual_regex") and re.search(r["manual_regex"], text):
            hits.append(f"수동 확인 {r['id']}: {r['지침']}")
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--draft", required=True)
    ap.add_argument("--skill-path")
    a = ap.parse_args()
    cfg = load_config()
    draft = json.loads(Path(a.draft).read_text(encoding="utf-8"))
    skill = draft["skill"]
    sp = Path(a.skill_path) if a.skill_path else find_skill(cfg, skill)
    if sp is None or not sp.exists():
        sys.exit(f"{UNKNOWN}: '{skill}'의 SKILL.md 위치를 찾지 못함. config.json의 skill_dirs를 채우거나 --skill-path를 줄 것.")
    current = sp.read_text(encoding="utf-8")
    cards = load_cards(cfg)

    items = []
    for it in draft["items"]:
        why = []
        if it["type"] not in ("추가", "수정", "삭제"):
            why.append("type 오류")
        n = current.count(it["before"]) if it.get("before") else 0
        if n != 1:
            why.append(f"변경 전 문구가 SKILL.md에 {n}회 나옴(정확히 1회여야 함)")
        if not it.get("card_ids"):
            why.append("근거 카드 없음")
        for cid in it.get("card_ids", []):
            if cid not in cards:
                why.append(f"{cid} 없음")
            elif cards[cid]["verification"] != "원문 대조 완료":
                why.append(f"{cid} 원문 대조 미통과({cards[cid]['verification']})")
        why += guideline_hits(skill, it.get("after", "") + "\n" + it.get("reason", ""))
        items.append(dict(it, status="적용 대상" if not why else "제외", exclude_reasons=why))

    out_dir = _resolve(cfg, "proposals_dir")
    base = out_dir / f"{skill}_{dt.date.today().isoformat()}"
    k = 2
    while base.with_suffix(".json").exists():
        base = out_dir / f"{skill}_{dt.date.today().isoformat()}_{k}"
        k += 1
    meta = {"skill": skill, "skill_path": str(sp), "skill_sha256": sha256_file(sp), "created": now(), "items": items}
    base.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    L = [f"# 스킬 반영 제안서: {skill}", "", f"- 대상: `{sp}`", f"- 작성: {meta['created']}",
         "- 이 제안서는 SKILL.md를 바꾸지 않았다. 승인한 항목만 apply_skill_update.py로 적용한다.", "",
         "| ID | 종류 | 변경 전 | 변경 후 | 근거 카드 | 상태 | 제외 사유 |", "|---|---|---|---|---|---|---|"]
    esc = lambda s: (s or "").replace("|", "\\|").replace("\n", "<br>")  # noqa: E731
    for it in items:
        L.append(f"| {it['id']} | {it['type']} | {esc(it.get('before'))} | {esc(it.get('after'))} | "
                 f"{', '.join(it.get('card_ids', []))} | **{it['status']}** | {esc('; '.join(it['exclude_reasons']))} |")
    L += ["", "## 승인 방법", "", "적용할 항목 ID를 골라 아래처럼 실행한다(제외 항목은 적용되지 않는다).", "",
          f"`python apply_skill_update.py --proposal \"{base.with_suffix('.json')}\" --approve P1,P2 --confirm \"승인함\"`"]
    base.with_suffix(".md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))
    print(f"\n제안서: {base.with_suffix('.md')}")


if __name__ == "__main__":
    main()
