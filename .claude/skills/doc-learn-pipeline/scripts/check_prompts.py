"""프롬프트 템플릿 점검(안전장치 7: 외부 전송 통제).

jev 라우팅에 쓰이는 단계 프롬프트에 문서 본문·인용문·사건명·당사자명·파일명이 들어가지 않았는지 검사한다.

검사 항목
  T1 허용되지 않은 자리표시자({stage_id} {task_type} {file_ids} {tier} 외)
  T2 사건번호 형태(예: 2024가합12345)
  T3 따옴표·낫표 안의 10자 이상 문구(인용문 의심)
  T4 카드의 인용·조항 문언·요지·사건번호와 10자 이상 겹침
  T5 config.sensitive_terms(당사자명·사건명 등 사용자가 등록한 금지어)
  T6 manifest의 파일명·폴더명과 그 3자 이상 토막(파일명에 사건명·당사자명이 들어 있을 수 있음).
     단, 경중표 등 고정 문구(allowed_vocab)에 이미 있는 일반어(예: '계약서')는 제외
  T7 파일 번호 목록 형식(F0001,F0002 …만 허용)
  T8 300자 넘는 줄(본문 붙여넣기 의심)

사용: python check_prompts.py                 # 템플릿 전체 점검
      python check_prompts.py --text "…"      # 렌더링된 프롬프트 점검
종료 코드: 통과 0, 위반 1
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import SKILL_DIR, UNKNOWN, load_config, load_manifest  # noqa: E402

ALLOWED = {"stage_id", "task_type", "file_ids", "tier"}
CASE_NO = re.compile(r"\d{2,4}\s*[가-힣]{1,3}\s*\d{2,7}")
QUOTED = re.compile(r"[\"“「『'‘]([^\"”」』'’]{10,})[\"”」』'’]")
FILE_IDS = re.compile(r"F\d{4,}(,F\d{4,})*")


def load_templates() -> dict[str, str]:
    text = (SKILL_DIR / "references" / "stage-prompts.md").read_text(encoding="utf-8")
    return dict(re.findall(r"```prompt (\S+)\n(.*?)\n```", text, re.S))


def _cards_text(cfg) -> list[str]:
    try:
        from make_card import load_cards
    except Exception:
        return []
    out = []
    for c in load_cards(cfg).values():
        out += [q["text"] for q in c["quotes"]] + list(c["summary"])
        for x in c["extra"].get("조항", []) if isinstance(c["extra"].get("조항"), list) else []:
            out.append(x.get("문언", ""))
        if c["extra"].get("사건번호") not in (None, UNKNOWN):
            out.append(str(c["extra"]["사건번호"]))
    return [s for s in out if s and s != UNKNOWN]


def _nospace(s: str) -> str:
    return re.sub(r"\s+", "", s)


def check_text(text: str, cfg: dict, file_ids: str | None = None, template: bool = False,
               allowed_vocab: str = "") -> list[str]:
    v = []
    for ph in re.findall(r"\{(\w+)\}", text):
        if ph not in ALLOWED:
            v.append(f"T1 허용되지 않은 자리표시자 {{{ph}}}")
    body = re.sub(r"\{\w+\}", "", text) if template else text
    if file_ids is not None:
        body = body.replace(file_ids, "")
        if not FILE_IDS.fullmatch(file_ids):
            v.append("T7 파일 번호 목록 형식 오류(F0001,F0002 형식만 허용)")
    if m := CASE_NO.search(body):
        v.append(f"T2 사건번호 형태 '{m.group(0)}'")
    for m in QUOTED.finditer(body):
        v.append(f"T3 따옴표 안 긴 문구(인용 의심) '{m.group(1)[:15]}…'")
    nb = _nospace(body)
    for s in _cards_text(cfg):
        ns = _nospace(s)
        for i in range(0, max(len(ns) - 9, 0)):
            if ns[i:i + 10] in nb:
                v.append(f"T4 카드 내용과 겹침 '{ns[i:i + 10]}…'")
                break
    for term in cfg.get("sensitive_terms", []):
        if term and term in body:
            v.append(f"T5 금지어 '{term}'")
    names = set()
    for rec in load_manifest(cfg).values():
        for part in Path(rec["rel"]).with_suffix("").parts:
            names.add(part)
            names.update(re.split(r"[_\s·()\[\]{}.,-]+", part))
    for tok in sorted(t for t in names if len(t) >= 3 and t in body and t not in allowed_vocab):
        v.append(f"T6 파일·폴더 이름 '{tok}'")
    for line in body.splitlines():
        if len(line) > 300:
            v.append(f"T8 {len(line)}자 줄(본문 의심)")
    return v


def severity_text() -> str:
    """경중표 원문. 단계 프롬프트·jev state의 고정 문구 출처."""
    from common import severity_table_path
    return severity_table_path().read_text(encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text")
    a = ap.parse_args()
    cfg = load_config()
    bad = 0
    if a.text is not None:
        v = check_text(a.text, cfg)
        print("렌더링된 프롬프트:", "통과" if not v else "위반")
        for x in v:
            print("  -", x)
        bad += bool(v)
    else:
        from common import read_severity_table
        fixed = severity_text()
        for sid, row in read_severity_table().items():
            txt = row["단계 작업"] + "\n" + row.get("작업 설명(jev 전달)", "")
            v = check_text(txt, cfg, allowed_vocab=fixed)
            print(f"경중표 {sid} 작업 설명: {'통과' if not v else '위반'}")
            for x in v:
                print("  -", x)
            bad += bool(v)
        for sid, tpl in load_templates().items():
            v = check_text(tpl, cfg, template=True)
            print(f"{sid}: {'통과' if not v else '위반'}")
            for x in v:
                print("  -", x)
            bad += bool(v)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
