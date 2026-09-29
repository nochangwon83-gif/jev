"""주제별 학습노트 틀 작성(6장).

- '원문 대조 완료' 카드만 topics 키로 묶는다. 미검증 카드는 노트 끝에 '제외' 목록으로만 남긴다.
- 사실란: 카드 요지를 문장마다 카드 ID와 함께 옮긴다(카드에서 직접 확인된 것).
- 패턴란: 근거 카드 수가 pattern_min_cards 미만이면 '사례 적음'으로 적고 일반화하지 않는다.
  그 이상이면 Claude가 채울 자리만 주석으로 남긴다(패턴 문장에도 반드시 근거 카드 ID를 단다).
- 확인 불가란: 위치를 확인하지 못한 인용을 카드 ID와 함께 적는다.
- 이미 있는 노트는 덮어쓰지 않는다(--force 없으면 건너뜀). --force도 이전 판을 _history에 보관한 뒤 쓴다.

사용: python notes_scaffold.py [--field 법무|웹소설] [--force]
그 뒤: python verify_cards.py --notes _output/notes
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import UNKNOWN, load_config, output_dir, stamp  # noqa: E402
from make_card import load_cards  # noqa: E402


def safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--field")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    cfg = load_config()
    notes = output_dir(cfg) / "notes"
    (notes / "_history").mkdir(parents=True, exist_ok=True)

    groups, excluded = defaultdict(list), defaultdict(list)
    for c in load_cards(cfg).values():
        if a.field and c["field"] != a.field:
            continue
        for t in c["topics"]:
            key = (c["field"], t)
            (groups if c["verification"] == "원문 대조 완료" else excluded)[key].append(c)

    for key in sorted(set(groups) | set(excluded)):
        field, topic = key
        cs, ex = groups.get(key, []), excluded.get(key, [])
        path = notes / f"{safe(field)}__{safe(topic)}.md"
        if path.exists() and not a.force:
            print(f"건너뜀(이미 있음): {path.name}")
            continue
        if path.exists():
            shutil.copy2(path, notes / "_history" / f"{path.stem}_{stamp()}.md")
        tags = "".join(f"[{c['card_id']}]" for c in cs)
        L = [f"# 학습노트: {topic} ({field})", "",
             f"<!-- 근거 카드 {len(cs)}건. 모든 문장에 카드 ID를 단다. 카드에 없는 내용은 쓰지 않는다. -->", "",
             "## 사실", ""]
        for c in cs:
            L += [f"- {s.rstrip('.')} [{c['card_id']}]." for s in c["summary"]]
        L += ["", "## 패턴", ""]
        if not cs:
            pass
        elif len(cs) < cfg["pattern_min_cards"]:
            L.append(f"- 사례 적음: 근거 카드 {len(cs)}건이라 패턴으로 일반화하지 않음 {tags}.")
        else:
            L.append(f"<!-- 작성 필요: '패턴(근거 카드 N건): …' 형식으로, 반복이 확인된 경향만 쓴다. 근거 카드 {tags} -->")
        L += ["", f"## {UNKNOWN}", ""]
        unk = [c for c in cs if any(q["loc"] == UNKNOWN for q in c["quotes"])]
        L += [f"- 원문 위치를 확인하지 못한 인용이 있음 [{c['card_id']}]." for c in unk]
        L.append(f"<!-- 카드로 뒷받침되지 않는 일반화는 쓰지 말고 이 절에 '{UNKNOWN}'으로 남긴다. -->")
        if ex:
            L += ["", "<!-- 원문 대조 미통과로 제외된 카드: " + ", ".join(c["card_id"] for c in ex) + " -->"]
        path.write_text("\n".join(L) + "\n", encoding="utf-8")
        print(f"작성: {path}")
    print("\n[승인 지점] 노트를 검토·보완한 뒤 verify_cards.py --notes 로 추적성을 확인한다.")


if __name__ == "__main__":
    main()
