"""단계 실행: jev가 경중·등급을 판단하고, 확정된 모델로 Claude Code 새 세션을 띄운다.

순서
  1. 경중표(severity-table.md)에서 단계 행을 읽는다.
  2. 모든 템플릿·경중표 설명을 점검하고(안전장치 7), 단계 프롬프트를 작업 유형·파일 번호·등급만으로 만든다.
  3. jev(TypeSafe System One)에 단계 설명과 파일 개수·형식만 보내 경중 점수와 등급을 받는다(jev_route.py).
     키가 없거나 연결이 안 되면 경중표의 기준 등급으로 진행한다(작업을 막지 않음).
  4. 코드 규칙으로 최종 등급을 확정한다(불확실하면 낮추지 않음, strong 고정 단계는 strong).
  5. 판단 기록을 _state/jev_decisions.jsonl에 남긴다.
  6. --execute가 있으면 `claude --model <모델> "<프롬프트>"`로 새 대화형 세션을 띄운다.
     세션 안의 도구 사용·파일 조작은 평소처럼 사용자 승인을 받고, 단계 프롬프트는 승인 지점에서 멈추게 되어 있다.

사용: python run_stage.py --stage S2l --files F0001,F0002 [--router jev|table] [--execute]
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from check_prompts import check_text, load_templates, severity_text  # noqa: E402
from common import SKILL_DIR, UNKNOWN, load_config, load_manifest, now, read_severity_table, state_dir  # noqa: E402
from jev_route import api_key, ask_jev, build_request, decide  # noqa: E402

DEFAULT_MODELS = {"fast": "haiku", "balanced": "sonnet", "strong": "opus"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True)
    ap.add_argument("--files", default="")
    ap.add_argument("--router", choices=["jev", "table"], default="jev",
                    help="jev: jev가 판단(기본). table: 경중표 기준값만 사용")
    ap.add_argument("--execute", action="store_true", help="확정 모델로 Claude Code 새 세션 실행")
    a = ap.parse_args()

    cfg = load_config()
    table = read_severity_table()
    if a.stage not in table:
        sys.exit(f"경중표에 없는 단계: {a.stage} (있는 단계: {', '.join(table)})")
    row = table[a.stage]
    if row["배정 등급"] == "long":
        sys.exit("long(Fable) 등급은 비용 확인 전까지 쓰지 않는다(8장 운영 규칙).")

    # 1) 템플릿·경중표 점검 — 하나라도 위반이면 어떤 단계도 실행하지 않는다.
    fixed = severity_text()
    templates = load_templates()
    bad = {sid: v for sid, t in templates.items() if (v := check_text(t, cfg, template=True))}
    bad |= {f"경중표 {sid}": v for sid, r in table.items()
            if (v := check_text(r["단계 작업"] + "\n" + r.get("작업 설명(jev 전달)", ""), cfg, allowed_vocab=fixed))}
    if bad:
        sys.exit(f"[중단] 점검 위반: {bad}")
    if a.stage not in templates:
        sys.exit(f"[중단] stage-prompts.md에 {a.stage} 템플릿 없음")

    # 2) 파일 번호 확인
    ids = [x for x in a.files.split(",") if x]
    recs = load_manifest(cfg)
    missing = [i for i in ids if i not in recs]
    if missing:
        sys.exit(f"[중단] manifest에 없는 파일 번호: {missing}")

    # 3~4) jev 판단 + 규칙 확정
    request, response, status = None, None, "경중표만 사용(--router table)"
    if a.router == "jev" and row["배정 등급"] != "none":
        request = build_request(row, [recs[i] for i in ids])
        response, status = ask_jev(request, cfg)
    result = decide(row, response, cfg.get("jev_min_confidence", 0.6))
    tier = result["tier"]

    # 5) 렌더링 + 점검
    file_ids = ",".join(ids) if ids else "없음"
    prompt = templates[a.stage].format(stage_id=a.stage, task_type=row["단계 작업"], file_ids=file_ids, tier=tier)
    v = check_text(prompt, cfg, file_ids=",".join(ids) if ids else None, allowed_vocab=fixed)
    if v:
        sys.exit(f"[중단] 렌더링된 프롬프트 점검 위반: {v}")

    models = {**DEFAULT_MODELS, **cfg.get("claude_models", {})}
    model = models.get(tier)
    print(f"단계 {a.stage} — {row['단계 작업']}")
    print(f"  경중표 기준: 경중 {row['경중']}, 등급 {row['배정 등급']}, strong 고정 {row['strong 고정']}")
    print(f"  JEV_API_KEY: {'설정됨' if api_key() else '없음'} (값은 출력하지 않음)")
    print(f"  jev 호출: {status}")
    j = result["jev"]
    if j:
        print(f"  jev 답: 등급 {j['tier']} (신뢰도 {j['confidence']}), 경중 점수 {j['severity']} (0~3)")
        if j.get("probabilities"):
            print("  등급 확률: " + ", ".join(f"{k} {v:.2f}" for k, v in j["probabilities"].items()))
    print(f"  ▶ 최종 등급: {tier} ({model or '모델 미사용'})")
    for r in result["reasons"]:
        print(f"     - {r}")
    print("  프롬프트 점검: 통과")
    print("\n[단계 프롬프트]\n" + prompt + "\n")

    with open(state_dir(cfg) / "jev_decisions.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": now(), "stage": a.stage, "file_ids": ids, "router": a.router,
                            "status": status, "request": request, "response": response,
                            "final_tier": tier, "model": model, "reasons": result["reasons"]},
                           ensure_ascii=False) + "\n")

    if tier == "none":
        print("[실행] 모델을 쓰지 않는 단계다. scan.py 등 스크립트만 실행한다.")
        return
    cmd = ["claude", "--model", model, prompt]
    if not a.execute:
        print("[실행] --execute를 붙이면 아래 명령으로 새 세션을 띄운다:")
        print(f'  claude --model {model} "<위 단계 프롬프트>"   (작업 폴더: {SKILL_DIR})')
        return
    exe = shutil.which("claude")
    if not exe:
        sys.exit(f"[중단] claude 실행 파일 없음({UNKNOWN}). Claude Code를 설치하거나 PATH를 확인할 것.")
    print(f"[실행] Claude Code 새 세션: 모델 {model}")
    sys.exit(subprocess.run([exe, *cmd[1:]], cwd=SKILL_DIR).returncode)


if __name__ == "__main__":
    main()
