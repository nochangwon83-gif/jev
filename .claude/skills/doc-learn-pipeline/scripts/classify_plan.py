"""분류 계획 CSV 작성. 파일을 옮기거나 복사하지 않는다(안전장치 1: 미리보기 우선).

모드:
  title   파일명·상위 폴더명·확장자만 본다(빠름).
  content 본문 앞부분(content_mode_max_chars 이내)까지 읽는다.
  auto    title로 판정하고 신뢰도가 title_confidence_threshold 미만인 파일만 content로 다시 판정한다.

대상: manifest에서 status가 new/changed인 파일(중단 후 재실행해도 이미 계획된 파일은 건너뜀).
CSV 열: 번호, 원래 경로, 제안 경로, 분류 근거, 신뢰도, 사용한 모드, 승인
사용자가 '승인' 열에 Y를 적은 행만 apply_plan.py가 적용한다.

사용: python classify_plan.py --corpus legal --mode auto [--out plan.csv] [--files F0001,F0002]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import SKILL_DIR, UNKNOWN, load_config, load_manifest, stamp, state_dir, update_status  # noqa: E402
from extract_text import ExtractError, extract  # noqa: E402

COLUMNS = ["번호", "원래 경로", "제안 경로", "분류 근거", "신뢰도", "사용한 모드", "승인"]


def load_rules(corpus: str) -> list[dict]:
    text = (SKILL_DIR / "references" / "classification-rules.md").read_text(encoding="utf-8")
    block = re.search(r"```json\n(.*?)\n```", text, re.S).group(1)
    return json.loads(block)[corpus]


def judge_title(rec: dict, rules: list[dict]) -> dict[int, tuple[float, str]]:
    name = Path(rec["rel"]).stem
    parents = Path(rec["rel"]).parts[:-1]
    out = {}
    for i, r in enumerate(rules):
        in_name = [k for k in r["title"] if k.lower() in name.lower()]
        in_parent = [k for k in r["title"] if any(k.lower() in p.lower() for p in parents)]
        pat = bool(r.get("pattern")) and re.search(r["pattern"], name) is not None
        if in_name and pat:
            out[i] = (0.9, f"파일명 키워드 {in_name} + 파일명 패턴 일치")
        elif in_name:
            out[i] = (0.75, f"파일명 키워드 {in_name}")
        elif in_parent:
            out[i] = (0.5, f"상위 폴더명 키워드 {in_parent}")
        elif pat:
            out[i] = (0.5, "파일명 패턴만 일치")
    return out


def judge_content(rec: dict, rules: list[dict], max_chars: int) -> tuple[dict[int, tuple[float, str]], str | None]:
    try:
        text = " ".join(s["text"] for s in extract(rec["path"], max_chars))
    except ExtractError as e:
        return {}, str(e)
    if not text.strip():
        return {}, f"글자 없음(스캔 PDF 의심 — OCR 필요 여부 {UNKNOWN})"
    out = {}
    for i, r in enumerate(rules):
        hits = [k for k in r["content"] if k in text]
        if len(hits) >= 2:
            out[i] = (0.8, f"본문 키워드 {hits}")
        elif hits:
            out[i] = (0.6, f"본문 키워드 {hits}")
    return out, None


def decide(rec: dict, rules: list[dict], mode: str, cfg: dict) -> tuple[str, str, float, str]:
    """(제안 상위/하위 경로, 근거, 신뢰도, 사용한 모드)"""
    parts = Path(rec["rel"]).parts
    existing_top = parts[0] if len(parts) > 1 else None
    tops = {r["top"] for r in rules}
    keep_top = existing_top in tops
    idx = [i for i, r in enumerate(rules) if not keep_top or r["top"] == existing_top]
    cand = [rules[i] for i in idx]

    scores, used, notes = {}, mode, []
    if mode in ("title", "auto"):
        scores = judge_title(rec, cand)
        used = "제목"
    best = max(scores.values(), default=(0.0, ""))[0]
    if keep_top and all(r["sub"] == "" for r in cand):
        scores, best = {0: (0.7, "장르 폴더 그대로(하위 폴더 없음)")}, 0.7
    if mode == "content" or (mode == "auto" and best < cfg["title_confidence_threshold"]):
        c, err = judge_content(rec, cand, cfg["content_mode_max_chars"])
        used = "내용" if mode == "content" else "제목→내용"
        if err:
            notes.append(f"본문 {err}")
        for i, v in c.items():
            if v[0] > scores.get(i, (0, ""))[0]:
                scores[i] = v

    if not scores:
        top = existing_top if keep_top else "미분류"
        return f"{top}/미분류", "; ".join(["일치 규칙 없음"] + notes), 0.2, used
    ranked = sorted(scores.items(), key=lambda kv: -kv[1][0])
    i, (conf, why) = ranked[0]
    r = cand[i]
    reasons = [why] + notes
    if len(ranked) > 1 and ranked[1][1][0] == conf and cand[ranked[1][0]] != r:
        conf -= 0.2
        reasons.append(f"동점 규칙 있음({cand[ranked[1][0]]['top']}/{cand[ranked[1][0]]['sub']})")
    if keep_top:
        reasons.insert(0, f"기존 상위 폴더 '{existing_top}' 유지")
    else:
        conf -= 0.1
        reasons.insert(0, "기존 상위 폴더가 규칙에 없음 → 상위 폴더도 제안")
    sub = f"{r['top']}/{r['sub']}" if r["sub"] else r["top"]
    return sub, "; ".join(reasons), round(max(conf, 0.0), 2), used


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True, choices=["legal", "novel"])
    ap.add_argument("--mode", required=True, choices=["title", "content", "auto"])
    ap.add_argument("--out")
    ap.add_argument("--files", help="쉼표로 구분한 파일 번호만 대상으로")
    a = ap.parse_args()

    cfg = load_config()
    rules = load_rules(a.corpus)
    recs = [r for r in load_manifest(cfg).values()
            if r["corpus"] == a.corpus and r["status"] in ("new", "changed")]
    if a.files:
        want = set(a.files.split(","))
        recs = [r for r in recs if r["file_id"] in want]
    if not recs:
        sys.exit("계획할 파일 없음(status new/changed 없음). scan.py를 먼저 실행하거나 상태를 확인할 것.")

    dest_root = Path(cfg["dest_roots"][a.corpus])
    out = Path(a.out) if a.out else state_dir(cfg) / f"plan_{a.corpus}_{stamp()}.csv"
    rows = []
    for rec in sorted(recs, key=lambda r: r["file_id"]):
        sub, why, conf, used = decide(rec, rules, a.mode, cfg)
        dest = dest_root / Path(sub) / Path(rec["rel"]).name
        rows.append({"번호": rec["file_id"], "원래 경로": rec["path"], "제안 경로": str(dest),
                     "분류 근거": why, "신뢰도": f"{conf:.2f}", "사용한 모드": used, "승인": ""})
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    for rec in recs:
        update_status(cfg, rec["file_id"], "planned", plan=str(out))

    low = [r for r in rows if float(r["신뢰도"]) < cfg["title_confidence_threshold"]]
    print(f"분류 계획: {out}  ({len(rows)}행, 신뢰도 미달 {len(low)}행)")
    for r in rows:
        print(f"  {r['번호']}  {r['신뢰도']}  {r['사용한 모드']:<5} {Path(r['원래 경로']).name} -> {r['제안 경로']}")
    print("\n[승인 지점] CSV를 열어 제안 경로를 고치고 적용할 행의 '승인' 열에 Y를 적은 뒤 apply_plan.py를 실행한다.")
    if low:
        print(f"신뢰도 미달 행({UNKNOWN} 가능성 높음): " + ",".join(r["번호"] for r in low))


if __name__ == "__main__":
    main()
