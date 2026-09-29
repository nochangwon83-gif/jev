"""단계 실행 준비: 경중표를 읽어 등급을 정하고, 점검을 통과한 단계 프롬프트를 만든다.

- severity-table.md에서 단계의 배정 등급·strong 고정 여부를 읽는다.
- stage-prompts.md 템플릿에 작업 유형·파일 번호·등급만 채운다.
- 실행 시작 시 모든 템플릿과 렌더링된 프롬프트를 check_prompts로 점검하고, 위반이 있으면 중단한다.
- .env의 JEV_API_KEY는 jev 하위 프로세스 환경에만 넣고 값은 출력하지 않는다.
- --jev-try: jev가 있으면 `jev try "<프롬프트>"`로 등급을 미리 보고 표와 비교한다.
- --record-stats: jev가 있으면 `jev stats` 출력을 _state/jev_stats.log에 단계 이름과 함께 남긴다.
  (설치된 jev에 try/stats 명령이 있는지는 확인 불가 — 실패하면 그대로 보고한다.)

사용: python run_stage.py --stage S2l --files F0001,F0002 [--jev-try] [--record-stats]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from check_prompts import check_text, load_templates  # noqa: E402
from common import UNKNOWN, load_config, load_env, load_manifest, now, read_severity_table, state_dir  # noqa: E402

TIER_MODEL = {"fast": "Haiku", "balanced": "Sonnet", "strong": "Opus", "none": "모델 미사용"}


def jev_env() -> dict:
    env = dict(os.environ)
    key = load_env().get("JEV_API_KEY")
    if key:
        env["JEV_API_KEY"] = key
    return env


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True)
    ap.add_argument("--files", default="")
    ap.add_argument("--jev-try", action="store_true")
    ap.add_argument("--record-stats", action="store_true")
    a = ap.parse_args()

    cfg = load_config()
    table = read_severity_table()
    if a.stage not in table:
        sys.exit(f"경중표에 없는 단계: {a.stage} (있는 단계: {', '.join(table)})")
    row = table[a.stage]
    tier = row["배정 등급"]
    if tier == "long":
        sys.exit("long(Fable) 등급은 비용 확인 전까지 쓰지 않는다(8장 운영 규칙).")

    # 1) 템플릿 전체 점검 — 하나라도 위반이면 어떤 단계도 실행하지 않는다.
    templates = load_templates()
    bad = {sid: v for sid, t in templates.items() if (v := check_text(t, cfg, template=True))}
    if bad:
        sys.exit(f"[중단] 템플릿 점검 위반: {bad}")
    if a.stage not in templates:
        sys.exit(f"[중단] stage-prompts.md에 {a.stage} 템플릿 없음")

    # 2) 파일 번호 확인
    ids = [x for x in a.files.split(",") if x]
    recs = load_manifest(cfg)
    missing = [i for i in ids if i not in recs]
    if missing:
        sys.exit(f"[중단] manifest에 없는 파일 번호: {missing}")
    file_ids = ",".join(ids) if ids else "없음"

    # 3) 렌더링 + 점검
    prompt = templates[a.stage].format(stage_id=a.stage, task_type=row["단계 작업"], file_ids=file_ids, tier=tier)
    v = check_text(prompt, cfg, file_ids=",".join(ids) if ids else None)
    if v:
        sys.exit(f"[중단] 렌더링된 프롬프트 점검 위반: {v}")

    key_set = bool(load_env().get("JEV_API_KEY"))
    jev = shutil.which("jev")
    print(f"단계 {a.stage} — {row['단계 작업']}")
    print(f"  경중 {row['경중']}, 배정 등급 {tier} ({TIER_MODEL.get(tier, UNKNOWN)}), strong 고정: {row['strong 고정']}")
    print(f"  JEV_API_KEY: {'.env에 설정됨' if key_set else '설정 안 됨'} (값은 출력하지 않음)")
    print(f"  jev 실행 파일: {jev or '없음'}")
    print("  프롬프트 점검: 통과")
    print("\n[새 세션에 붙여넣을 프롬프트]\n" + prompt + "\n")
    if tier == "none":
        print("[실행 방법] 모델을 쓰지 않는 단계다. 스크립트만 실행한다.")
    elif row["strong 고정"] == "예":
        print("[실행 방법] 새 세션을 열고 /model 에서 strong(Opus)을 직접 고른 뒤 위 프롬프트를 붙여넣는다.")
    else:
        print(f"[실행 방법] 새 세션(Jev Auto 라우팅)에서 위 프롬프트를 붙여넣는다. 기대 등급: {tier}.")

    result = {"stage": a.stage, "tier": tier, "file_ids": ids, "ts": now(), "jev_try": None}
    if a.jev_try:
        if not jev:
            result["jev_try"] = f"{UNKNOWN}: jev 실행 파일 없음"
        else:
            out = subprocess.run([jev, "try", prompt], capture_output=True, text=True, env=jev_env(), timeout=120)
            txt = (out.stdout + out.stderr).strip()
            found = [t for t in ("fast", "balanced", "strong", "long") if t in txt.lower()]
            if out.returncode != 0:
                result["jev_try"] = f"{UNKNOWN}: jev try 실패(코드 {out.returncode})"
            elif not found:
                result["jev_try"] = f"{UNKNOWN}: 출력에서 등급을 찾지 못함"
            elif tier in found and len(found) == 1:
                result["jev_try"] = f"표와 일치({tier})"
            else:
                result["jev_try"] = f"표와 다름 또는 판독 불명확: 표={tier}, 출력={found}"
            print("\n[jev try 출력]\n" + txt)
        print(f"\n[jev try 판정] {result['jev_try']}")
    if a.record_stats:
        if not jev:
            print(f"[jev stats] {UNKNOWN}: jev 실행 파일 없음")
        else:
            out = subprocess.run([jev, "stats"], capture_output=True, text=True, env=jev_env(), timeout=60)
            with open(state_dir(cfg) / "jev_stats.log", "a", encoding="utf-8") as f:
                f.write(f"\n=== {now()} {a.stage} ===\n{out.stdout}{out.stderr}")
            print(f"[jev stats] 기록함 (종료 코드 {out.returncode})")
    with open(state_dir(cfg) / "stage_runs.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
