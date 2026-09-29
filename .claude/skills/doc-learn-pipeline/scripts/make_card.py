"""학습자료 카드 등록·개정·상태 갱신.

  --draft 초안.json   Claude가 원본을 읽고 쓴 초안을 검사해 카드로 등록한다.
                      같은 파일의 카드가 있고 원본 해시가 바뀌었으면 개정한다(이전 판 보관).
  --refresh           모든 카드의 원본 존재·해시를 확인해 '원본 없음'/'원본 변경(개정 필요)'을 표시한다.

카드는 원문 대조 전까지 verification='미완료'다. verify_cards.py가 통과시켜야 '원문 대조 완료'가 된다.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (UNKNOWN, load_config, load_manifest, now, output_dir,  # noqa: E402
                    sha256_file, update_status)

EXTRA_KEYS = {
    "계약서": ["계약 유형", "당사자 입장", "조항", "쟁점"],
    "소송기록": ["사건번호", "서면 종류", "주장·반박 대응", "증거"],
    "웹소설": ["장르", "문체 특징", "전개 패턴", "인물 화술"],
}


def cards_dir(cfg) -> Path:
    d = output_dir(cfg) / "cards"
    (d / "_history").mkdir(parents=True, exist_ok=True)
    return d


def load_cards(cfg) -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(cards_dir(cfg).glob("C-*.json"))}


def save_card(cfg, card: dict) -> Path:
    d = cards_dir(cfg)
    p = d / f"{card['card_id']}.json"
    p.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
    (d / f"{card['card_id']}.md").write_text(render_md(card), encoding="utf-8")
    return p


def render_md(c: dict) -> str:
    L = [f"# {c['card_id']} (v{c['version']})", "",
         f"- 원본: `{c['source_path']}` ({c['file_id']})", f"- 해시: `{c['source_sha256'][:16]}…`",
         f"- 학습일: {c['learned_at']}", f"- 분야/유형: {c['field']} / {c['type']}",
         f"- 검증 상태: **{c['verification']}**", f"- 원본 상태: {c['source_state']}", "", "## 핵심 요지"]
    L += [f"- {s}" for s in c["summary"]]
    L += ["", "## 원문 인용", "", "| 위치 | 인용 | 대조 |", "|---|---|---|"]
    L += [f"| {q['loc']} | {q['text']} | {q.get('check', '미대조')} |" for q in c["quotes"]]
    L += ["", "## 재사용 패턴"] + [f"- {p['pattern']} → `{p['apply_skill']}`" for p in c["patterns"]]
    L += ["", "## 분야별 항목"]
    for k, v in c["extra"].items():
        if k == "조항" and isinstance(v, list):
            L.append("- 조항:")
            L += [f"  - {x.get('번호', UNKNOWN)} ({x.get('loc', UNKNOWN)}): {x.get('문언', UNKNOWN)} — {x.get('check', '미대조')}"
                  for x in v]
        else:
            L.append(f"- {k}: {v if not isinstance(v, list) else ', '.join(map(str, v))}")
    L += ["", f"- 주제: {', '.join(c['topics'])}"]
    return "\n".join(L) + "\n"


def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip()) or v == []


def validate(draft: dict, cfg: dict) -> list[str]:
    errs = []
    if draft.get("type") not in EXTRA_KEYS:
        errs.append(f"type은 {list(EXTRA_KEYS)} 중 하나여야 함")
    summary = draft.get("summary", [])
    if isinstance(summary, str):
        summary = [s for s in re.split(r"(?<=[.!?])\s+", summary) if s.strip()]
    if not summary or len(summary) > 3:
        errs.append("summary는 1~3문장")
    draft["summary"] = summary
    if not draft.get("quotes"):
        errs.append("quotes가 비었음 — 근거 없는 카드는 만들지 않음")
    if draft.get("type") == "웹소설":
        mx, mq = cfg["novel_quote_max_chars"], cfg["novel_max_quotes"]
        if len(draft.get("quotes", [])) > mq:
            errs.append(f"웹소설 인용은 {mq}건 이하")
        for q in draft.get("quotes", []):
            if len(q.get("text", "")) > mx:
                errs.append(f"웹소설 인용 {len(q['text'])}자 > {mx}자 상한: 원문을 길게 복사하지 말 것")
    return errs


def register(draft_path: Path, cfg: dict, revise: bool) -> None:
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    errs = validate(draft, cfg)
    if errs:
        sys.exit("[카드 거부]\n- " + "\n- ".join(errs))
    rec = load_manifest(cfg).get(draft["file_id"])
    if rec is None:
        sys.exit(f"[카드 거부] {draft['file_id']}: manifest에 없음")
    src = Path(rec["path"])
    if not src.exists():
        sys.exit(f"[카드 거부] 원본 없음: {src}")
    digest = sha256_file(src)
    if digest != rec["sha256"]:
        sys.exit("[카드 거부] 스캔 이후 원본이 바뀜 — scan.py를 다시 실행할 것")

    cards = load_cards(cfg)
    existing = next((c for c in cards.values() if c["file_id"] == draft["file_id"]), None)
    if existing and existing["source_sha256"] == digest and not revise:
        sys.exit(f"[카드 거부] {existing['card_id']}가 이미 있음. 같은 원본으로 다시 쓰려면 --revise")
    if existing:
        hist = cards_dir(cfg) / "_history" / f"{existing['card_id']}_v{existing['version']}.json"
        shutil.copy2(cards_dir(cfg) / f"{existing['card_id']}.json", hist)
        card_id, version = existing["card_id"], existing["version"] + 1
    else:
        n = max((int(k[2:]) for k in cards), default=0) + 1
        card_id, version = f"C-{n:04d}", 1

    extra = draft.get("extra", {})
    for k in EXTRA_KEYS[draft["type"]]:
        if _blank(extra.get(k)):
            extra[k] = UNKNOWN
    quotes = [{"text": q["text"], "loc": q.get("loc") or UNKNOWN} for q in draft["quotes"]]
    card = {
        "card_id": card_id, "version": version, "file_id": draft["file_id"],
        "source_path": str(src), "source_sha256": digest, "learned_at": now(),
        "field": draft.get("field") or UNKNOWN, "type": draft["type"], "summary": draft["summary"],
        "quotes": quotes, "patterns": draft.get("patterns") or [{"pattern": UNKNOWN, "apply_skill": UNKNOWN}],
        "topics": draft.get("topics") or [UNKNOWN], "extra": extra,
        "verification": "미완료", "source_state": "정상",
    }
    p = save_card(cfg, card)
    update_status(cfg, draft["file_id"], "carded", card_id=card_id)
    print(f"{'개정' if existing else '등록'}: {card_id} v{version} -> {p}")
    print("[다음] verify_cards.py 로 원문 대조를 해야 '원문 대조 완료'가 된다.")


def refresh(cfg: dict) -> None:
    for c in load_cards(cfg).values():
        src = Path(c["source_path"])
        if not src.exists():
            state = "원본 없음"
        elif sha256_file(src) != c["source_sha256"]:
            state = "원본 변경(개정 필요)"
        else:
            state = "정상"
        if state != c["source_state"]:
            c["source_state"] = state
            if state != "정상":
                c["verification"] = "검증 미완료"
            save_card(cfg, c)
        print(f"{c['card_id']}: {state}")


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--draft")
    g.add_argument("--refresh", action="store_true")
    ap.add_argument("--revise", action="store_true")
    a = ap.parse_args()
    cfg = load_config()
    if a.refresh:
        refresh(cfg)
    else:
        register(Path(a.draft), cfg, a.revise)


if __name__ == "__main__":
    main()
