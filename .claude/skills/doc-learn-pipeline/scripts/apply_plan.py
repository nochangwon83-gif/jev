"""승인된 분류 계획 적용. 기본은 복사다.

안전장치
  1 미리보기 우선 : '승인' 열이 Y인 행만 적용한다.
  2 원본 보존     : 원본을 지우거나 덮어쓰지 않는다. 대상에 같은 이름이 있으면 ' (2)'를 붙인다.
                    이동은 --move와 --confirm-move "이동에 동의"를 함께 줄 때만 한다.
  3 되돌리기      : 모든 조작을 undo.log에 배치 번호와 함께 남긴다(undo.py로 역실행).
  4 해시 검증     : 복사 전 원본 해시가 스캔 때와 같은지, 복사 후 복사본 해시가 원본과 같은지 확인하고
                    다르면 즉시 중단한다.
  8 상태 복구     : 이미 적용된 행은 건너뛰므로 중단 후 같은 명령을 다시 실행하면 이어서 진행한다.

사용: python apply_plan.py <plan.csv> [--move --confirm-move "이동에 동의"]
"""
from __future__ import annotations

import argparse
import csv
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (load_config, load_manifest, log_undo, sha256_file, stamp,  # noqa: E402
                    unique_dest, update_status)

APPROVED = {"Y", "y", "예", "O", "o", "승인"}
MOVE_PHRASE = "이동에 동의"


def is_under(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan")
    ap.add_argument("--move", action="store_true")
    ap.add_argument("--confirm-move", default="")
    a = ap.parse_args()
    if a.move and a.confirm_move != MOVE_PHRASE:
        sys.exit(f'이동은 --confirm-move "{MOVE_PHRASE}" 를 함께 줄 때만 한다. 기본은 복사.')
    op = "move" if a.move else "copy"

    cfg = load_config()
    recs = load_manifest(cfg)
    with open(a.plan, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    approved = [r for r in rows if r.get("승인", "").strip() in APPROVED]
    print(f"계획 {len(rows)}행 중 승인 {len(approved)}행, 조작: {'이동' if a.move else '복사'}")
    if not approved:
        return

    batch = stamp()
    done = skipped = 0
    for row in approved:
        fid = row["번호"]
        rec = recs.get(fid)
        if rec is None:
            sys.exit(f"[중단] {fid}: manifest에 없음")
        if rec["status"] == "applied" and rec.get("dest") and Path(rec["dest"]).exists():
            skipped += 1  # 이전 실행에서 이미 적용됨
            continue
        if rec["status"] != "planned":
            sys.exit(f"[중단] {fid}: 상태가 planned가 아님({rec['status']}). scan/classify부터 다시 할 것.")
        src = Path(rec["path"])
        if str(src) != row["원래 경로"]:
            sys.exit(f"[중단] {fid}: CSV의 원래 경로가 manifest와 다름. 원래 경로 열은 고치지 말 것.")
        if not src.exists():
            sys.exit(f"[중단] {fid}: 원본이 없음 {src}")
        if sha256_file(src) != rec["sha256"]:
            sys.exit(f"[중단] {fid}: 스캔 이후 원본이 바뀜. scan.py를 다시 실행할 것.")

        dest_root = Path(cfg["dest_roots"][rec["corpus"]])
        dest = Path(row["제안 경로"])
        if not is_under(dest, dest_root):
            sys.exit(f"[중단] {fid}: 제안 경로가 정리본 폴더({dest_root}) 밖임")
        if dest.resolve() == src.resolve():
            sys.exit(f"[중단] {fid}: 제안 경로가 원본과 같음")
        dest = unique_dest(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)

        shutil.copy2(src, dest)
        log_undo(cfg, {"batch": batch, "op": op, "file_id": fid, "src": str(src), "dest": str(dest),
                       "sha256": rec["sha256"], "prev_status": rec["status"]})
        got = sha256_file(dest)
        if got != rec["sha256"]:
            sys.exit(f"[중단] {fid}: 복사본 해시 불일치({got[:12]}…). undo.py --batch {batch} 로 되돌릴 것.")
        if a.move:
            os.remove(src)  # 사용자가 이동을 명시했고 복사본 해시가 확인된 뒤에만
        update_status(cfg, fid, "applied", dest=str(dest), batch=batch)
        done += 1
        print(f"  {fid} {'이동' if a.move else '복사'} 완료, 해시 일치: {dest}")

    print(f"\n배치 {batch}: 적용 {done}건, 이미 적용되어 건너뜀 {skipped}건")
    if done:
        print(f"되돌리기: python undo.py --batch {batch}")


if __name__ == "__main__":
    main()
