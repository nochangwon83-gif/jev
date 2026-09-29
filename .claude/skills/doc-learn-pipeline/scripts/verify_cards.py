"""원문 대조(안전장치 5)와 학습노트 추적성 검사.

카드 검사
  - 원본이 있고 해시가 카드 기록과 같은지 확인한다.
  - 인용(quotes)과 계약서 조항 문언(extra.조항[].문언)을 원본에서 다시 찾는다.
      정확 일치     : 공백을 하나로 모은 뒤 그대로 있음
      공백 무시 일치 : 공백을 모두 뺀 뒤에만 있음(PDF 줄바꿈 등) — 통과로 보되 보고서에 구분 표시
  - 위치(loc)가 적혀 있으면 그 위치의 조각 안에 있어야 한다. loc이 '확인 불가'면 본문 일치만 보고
    '위치 확인 불가'로 표시한다.
  - 모두 통과 → verification='원문 대조 완료'. 하나라도 실패 → '검증 미완료'(해당 인용 대조='확인 불가').
학습노트 검사(--notes 폴더)
  - 제목·빈 줄·표 구분선·주석을 뺀 모든 문장에 [C-0001] 형식 카드 ID가 있어야 한다.
  - 인용된 카드가 존재하고 '원문 대조 완료'여야 한다.

사용: python verify_cards.py --all | --sample 5 [--seed 1] | --cards C-0001,C-0002   [--notes 폴더]
종료 코드: 모두 통과 0, 하나라도 실패 1
"""
from __future__ import annotations

import argparse
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import UNKNOWN, load_config, sha256_file, stamp, state_dir  # noqa: E402
from extract_text import ExtractError, extract  # noqa: E402
from make_card import load_cards, save_card  # noqa: E402

TAG = re.compile(r"\[C-\d{4}\]")


def norm(s: str) -> str:
    s = s.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    return re.sub(r"\s+", " ", s).strip()


def nospace(s: str) -> str:
    return re.sub(r"\s+", "", norm(s))


def find(quote: str, loc: str, segs: list[dict]) -> str:
    """판정 문자열을 돌려준다. '실패'로 시작하면 불통과."""
    full = " ".join(s["text"] for s in segs)
    if norm(quote) in norm(full):
        kind = "정확 일치"
    elif nospace(quote) in nospace(full):
        kind = "공백 무시 일치"
    else:
        return "실패: 원문에서 찾지 못함"
    if loc == UNKNOWN:
        return f"{kind}, 위치 {UNKNOWN}"
    target = [s for s in segs if s["loc"] == loc]
    if not target:
        return f"실패: 위치 '{loc}'를 원문에서 특정하지 못함({kind})"
    t = target[0]["text"]
    if norm(quote) in norm(t) or nospace(quote) in nospace(t):
        return f"{kind}, 위치 일치"
    return f"실패: 본문엔 있으나 위치 '{loc}'와 다름"


def verify_card(card: dict) -> tuple[bool, list[str]]:
    lines, ok = [], True
    src = Path(card["source_path"])
    if not src.exists():
        return False, ["실패: 원본 없음"]
    if sha256_file(src) != card["source_sha256"]:
        return False, ["실패: 원본 해시가 카드 기록과 다름(원본 변경)"]
    try:
        segs = extract(src)
    except ExtractError as e:
        return False, [f"실패: {e}"]
    targets = [(q, "인용") for q in card["quotes"]]
    if card["type"] == "계약서" and isinstance(card["extra"].get("조항"), list):
        targets += [({"text": x.get("문언", ""), "loc": x.get("loc", UNKNOWN), "_obj": x}, "조항")
                    for x in card["extra"]["조항"]]
    for q, kind in targets:
        if not q["text"] or q["text"] == UNKNOWN:
            r = f"실패: {kind} 문언이 비었거나 {UNKNOWN}"
        else:
            r = find(q["text"], q["loc"], segs)
        passed = not r.startswith("실패")
        ok &= passed
        mark = r if passed else UNKNOWN
        (q["_obj"] if "_obj" in q else q)["check"] = mark
        lines.append(f"{kind} [{q['loc']}] {q['text'][:30]}… → {r}")
    return ok, lines


def check_notes(notes_dir: Path, cards: dict) -> tuple[bool, list[str]]:
    ok, out = True, []
    for p in sorted(notes_dir.glob("*.md")):
        in_code, n_sent, bad = False, 0, []
        raw = p.read_text(encoding="utf-8").splitlines()
        sep = re.compile(r"\|?[\s|:-]+\|?")
        for i, line in enumerate(raw, 1):
            s = line.strip()
            if s.startswith("```"):
                in_code = not in_code
                continue
            if in_code or not s or s.startswith(("#", "<!--")) or sep.fullmatch(s):
                continue
            if s.startswith("|") and i < len(raw) and sep.fullmatch(raw[i].strip() or "x"):
                continue  # 표 머리행(다음 줄이 구분선)
            for sent in [x for x in re.split(r"(?<=[.!?])\s+", s) if x.strip()]:
                n_sent += 1
                ids = TAG.findall(sent)
                if not ids:
                    bad.append(f"  {i}행: 카드 ID 없음 — {sent[:40]}")
                for tag in ids:
                    cid = tag[1:-1]
                    if cid not in cards:
                        bad.append(f"  {i}행: 없는 카드 {cid}")
                    elif cards[cid]["verification"] != "원문 대조 완료":
                        bad.append(f"  {i}행: {cid}가 '{cards[cid]['verification']}' — 반영 제외 대상")
        ok &= not bad
        out.append(f"{p.name}: 문장 {n_sent}개, 문제 {len(bad)}건")
        out += bad
    return ok, out


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--all", action="store_true")
    g.add_argument("--sample", type=int)
    g.add_argument("--cards")
    ap.add_argument("--seed", type=int)
    ap.add_argument("--notes")
    a = ap.parse_args()

    cfg = load_config()
    cards = load_cards(cfg)
    report, all_ok = [f"# 원문 대조 보고 {stamp()}", ""], True

    if a.all or a.sample or a.cards:
        ids = sorted(cards)
        if a.cards:
            ids = a.cards.split(",")
        elif a.sample:
            ids = random.Random(a.seed).sample(ids, min(a.sample, len(ids)))
        for cid in ids:
            card = cards[cid]
            ok, lines = verify_card(card)
            card["verification"] = "원문 대조 완료" if ok else "검증 미완료"
            save_card(cfg, card)
            all_ok &= ok
            report += [f"## {cid} → {card['verification']}"] + [f"- {l}" for l in lines] + [""]

    if a.notes:
        ok, lines = check_notes(Path(a.notes), load_cards(cfg))
        all_ok &= ok
        report += ["## 학습노트 추적성", ""] + [f"- {l}" for l in lines]

    text = "\n".join(report) + "\n"
    out = state_dir(cfg) / f"verify_{stamp()}.md"
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"결과: {'통과' if all_ok else '실패 있음'}  (보고 파일: {out})")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
