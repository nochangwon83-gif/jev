"""경중표 기준 등급 jev 보정 — jev가 판단하고 사람이 승인한 행만 반영한다.

propose  단계마다 jev에 --repeats번(기본 3) 같은 질문을 해 기준 등급·경중 수정안을 만든다.
         경중표는 바꾸지 않는다. 결과: _proposals/severity-table_<날짜>.md(읽기용)와 .json(apply 입력)
         jev에는 단계 작업 설명만 보낸다(파일 정보 없음, 전송 전 check_prompts 점검 — jev_route.ask_jev).
         다음 행은 '제외'로 표시해 승인해도 적용되지 않는다.
           - jev 응답 실패가 한 번이라도 있음
           - 반복 답의 등급이 서로 다름(판단이 흔들림)
           - 최저 신뢰도 < jev_min_confidence(기본 0.6)
           - strong 고정 행(S2l·S5): 정책으로 고정한 등급이라 보정 대상이 아님
           - 모델 미사용 행(S0)
         제안 등급 = jev 일치 등급. 단, jev 경중 점수 평균이 더 높은 등급을 가리키면 높은 쪽(run_stage와 같은 규칙).
apply    사람이 고른 행만 경중표에 쓴다. --approve 와 --confirm "승인함" 이 모두 있어야 한다.
         제안서 작성 뒤 경중표가 바뀌었으면 중단한다. 쓰기 전 경중표를 _backup/에 보관하고
         _state/severity_changelog.md에 이력을 남긴다.

사용: python calibrate_table.py propose [--repeats 3]
      python calibrate_table.py apply --proposal <json> --approve S1a,S3 --confirm "승인함"
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (_resolve, load_config, now, read_severity_table, severity_table_path,  # noqa: E402
                    sha256_file, stamp, state_dir, writable_severity_table_path)
from jev_route import TIERS, ask_jev, build_request  # noqa: E402

PHRASE = "승인함"
SEVERITY_LABELS = ["없음", "낮음", "중간", "높음"]
CALIBRATION_NOTE = "기준 등급 보정: 특정 파일이 아니라 이 단계의 일반적인 작업을 판단한다."


def calibration_request(row: dict) -> dict:
    req = build_request(row, [])
    req["state"]["inputs"] = {"note": CALIBRATION_NOTE}
    return req


def judge_row(sid: str, row: dict, cfg: dict, repeats: int) -> dict:
    out = {"stage": sid, "task": row["단계 작업"], "current_tier": row["배정 등급"],
           "current_severity": row["경중"], "answers": [], "exclude_reasons": []}
    if row["배정 등급"] == "none":
        out["exclude_reasons"].append("모델 미사용 단계")
    if row["strong 고정"] == "예":
        out["exclude_reasons"].append("strong 고정 행(정책) — 보정 대상 아님")
    if out["exclude_reasons"]:
        out["status"] = "제외"
        return out

    req = calibration_request(row)
    for _ in range(repeats):
        resp, status = ask_jev(req, cfg)
        a = (resp or {}).get("answers", {})
        t, s = a.get("tier") or {}, a.get("severity") or {}
        out["answers"].append({"status": status, "tier": t.get("choice"), "confidence": t.get("confidence"),
                               "severity": s.get("score")})
    ans = out["answers"]
    if any(x["tier"] not in TIERS or not isinstance(x["confidence"], (int, float)) for x in ans):
        out["exclude_reasons"].append("jev 응답 실패: " + "; ".join(sorted({x["status"] for x in ans})))
        out["status"] = "제외"
        return out
    tiers = {x["tier"] for x in ans}
    min_conf = min(x["confidence"] for x in ans)
    sevs = [x["severity"] for x in ans if isinstance(x["severity"], (int, float))]
    mean_sev = sum(sevs) / len(sevs) if sevs else None
    out.update(min_confidence=round(min_conf, 3), mean_severity=None if mean_sev is None else round(mean_sev, 3))
    if len(tiers) > 1:
        out["exclude_reasons"].append(f"반복 답 불일치 {sorted(tiers)}")
    if min_conf < cfg.get("jev_min_confidence", 0.6):
        out["exclude_reasons"].append(f"최저 신뢰도 {min_conf:.2f} < {cfg.get('jev_min_confidence', 0.6)}")
    tier = ans[0]["tier"]
    if mean_sev is not None:
        level = max(0, min(3, round(mean_sev)))
        implied = ["fast", "fast", "balanced", "strong"][level]
        if TIERS.index(implied) > TIERS.index(tier):
            tier = implied
        out["proposed_severity"] = SEVERITY_LABELS[level]
    else:
        out["proposed_severity"] = row["경중"]
    out["proposed_tier"] = tier
    if out["exclude_reasons"]:
        out["status"] = "제외"
    elif tier == row["배정 등급"] and out["proposed_severity"] == row["경중"]:
        out["status"] = "변경 없음"
    else:
        out["status"] = "적용 대상"
    return out


def propose(cfg: dict, repeats: int) -> None:
    table_path = severity_table_path()
    rows = [judge_row(sid, row, cfg, repeats) for sid, row in read_severity_table().items()]
    out_dir = _resolve(cfg, "proposals_dir")
    base = out_dir / f"severity-table_{dt.date.today().isoformat()}"
    k = 2
    while base.with_suffix(".json").exists():
        base = out_dir / f"severity-table_{dt.date.today().isoformat()}_{k}"
        k += 1
    meta = {"table_path": str(table_path), "table_sha256": sha256_file(table_path), "created": now(),
            "repeats": repeats, "rows": rows}
    base.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    L = ["# 경중표 기준 등급 jev 보정 제안서", "", f"- 대상: `{table_path}`", f"- 작성: {meta['created']}",
         f"- 단계마다 jev에 {repeats}회 질문. 경중표는 아직 바뀌지 않았다.", "",
         "| 단계 | 작업 | 현재 경중/등급 | jev 제안 경중/등급 | jev 답(등급·신뢰도·경중점수) | 상태 | 제외 사유 |",
         "|---|---|---|---|---|---|---|"]
    for r in rows:
        answers = "<br>".join(f"{a['tier']}·{a['confidence']}·{a['severity']}" for a in r["answers"]) or "-"
        prop = f"{r.get('proposed_severity', '-')}/{r.get('proposed_tier', '-')}"
        L.append(f"| {r['stage']} | {r['task']} | {r['current_severity']}/{r['current_tier']} | {prop} | {answers} | "
                 f"**{r['status']}** | {'; '.join(r['exclude_reasons'])} |")
    targets = [r["stage"] for r in rows if r["status"] == "적용 대상"]
    L += ["", "## 승인 방법", "",
          f"적용 대상: {', '.join(targets) if targets else '없음'}. 반영할 행을 골라 실행한다(제외 행은 적용되지 않는다).", "",
          f"`python calibrate_table.py apply --proposal \"{base.with_suffix('.json')}\" --approve "
          f"{','.join(targets) or 'S1a'} --confirm \"{PHRASE}\"`"]
    base.with_suffix(".md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))
    print(f"\n제안서: {base.with_suffix('.md')}")
    print("[승인 지점] 제안서를 검토하고 반영할 단계를 골라 apply를 실행한다.")


def apply(cfg: dict, proposal: str, approve: str, confirm: str) -> None:
    if confirm != PHRASE:
        sys.exit(f'사람 승인 확인 문구가 없음: --confirm "{PHRASE}"')
    meta = json.loads(Path(proposal).read_text(encoding="utf-8"))
    table_path = Path(meta["table_path"])
    if sha256_file(table_path) != meta["table_sha256"]:
        sys.exit("[중단] 제안서 작성 이후 경중표가 바뀜 — propose를 다시 실행할 것")
    rows = {r["stage"]: r for r in meta["rows"]}
    chosen = []
    for sid in [x for x in approve.split(",") if x]:
        r = rows.get(sid)
        if r is None:
            sys.exit(f"[중단] 제안서에 없는 단계 {sid}")
        if r["status"] != "적용 대상":
            sys.exit(f"[중단] {sid}는 '{r['status']}' 행: {'; '.join(r['exclude_reasons']) or '바꿀 내용 없음'}")
        chosen.append(r)

    # 스킬 폴더가 읽기 전용이면 작업 폴더의 사본에 쓴다(내용은 제안서 때와 같음을 위에서 확인).
    table_path = writable_severity_table_path()
    lines = table_path.read_text(encoding="utf-8").split("\n")
    header = next(l for l in lines if l.startswith("| 단계ID |"))
    cols = [c.strip() for c in header.strip().strip("|").split("|")]
    i_sev, i_tier, i_why = cols.index("경중"), cols.index("배정 등급"), cols.index("근거")
    today = dt.date.today().isoformat()
    for r in chosen:
        idx = next(n for n, l in enumerate(lines) if l.startswith(f"| {r['stage']} |"))
        cells = [c.strip() for c in lines[idx].strip().strip("|").split("|")]
        cells[i_sev], cells[i_tier] = r["proposed_severity"], r["proposed_tier"]
        cells[i_why] += (f" / jev 보정 {today}(이전 {r['current_severity']}/{r['current_tier']}, "
                         f"최저 신뢰도 {r['min_confidence']}, {meta['repeats']}회 일치)")
        lines[idx] = "| " + " | ".join(cells) + " |"

    bdir = _resolve(cfg, "backup_dir") / f"severity-table_{stamp()}"
    bdir.mkdir(parents=True)
    shutil.copy2(table_path, bdir / table_path.name)
    table_path.write_text("\n".join(lines), encoding="utf-8")
    log = state_dir(cfg) / "severity_changelog.md"
    with open(log, "a", encoding="utf-8") as f:
        f.write(f"\n## {now()} 경중표 jev 보정 반영\n- 백업: `{bdir / table_path.name}`\n- 제안서: `{proposal}`\n")
        for r in chosen:
            f.write(f"- {r['stage']}: {r['current_severity']}/{r['current_tier']} → "
                    f"{r['proposed_severity']}/{r['proposed_tier']} (최저 신뢰도 {r['min_confidence']})\n")
    print(f"반영 {len(chosen)}행: {', '.join(r['stage'] for r in chosen)}")
    print(f"백업: {bdir / table_path.name}\n이력: {log}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("propose")
    p.add_argument("--repeats", type=int, default=3)
    q = sub.add_parser("apply")
    q.add_argument("--proposal", required=True)
    q.add_argument("--approve", required=True)
    q.add_argument("--confirm", default="")
    a = ap.parse_args()
    cfg = load_config()
    if a.cmd == "propose":
        propose(cfg, max(1, a.repeats))
    else:
        apply(cfg, a.proposal, a.approve, a.confirm)


if __name__ == "__main__":
    main()
