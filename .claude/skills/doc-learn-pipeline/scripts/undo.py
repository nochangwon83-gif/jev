"""undo.log 역실행(안전장치 3: 되돌리기).

- 복사 되돌리기: 복사본이 기록된 해시와 같으면 _state/undo_trash/<배치>/ 로 옮긴다(지우지 않음).
  해시가 다르면(복사 후 누가 고친 경우) 건드리지 않고 '확인 필요'로 보고한다.
- 이동 되돌리기: 원래 자리가 비어 있으면 복사본을 원래 자리로 복사·해시 확인한 뒤 복사본을 휴지통 폴더로 옮긴다.
- 원본 파일은 어떤 경우에도 지우지 않는다.

사용: python undo.py --batch 20260929-101500   또는   python undo.py --last
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (load_config, load_manifest, log_undo, read_undo_log, sha256_file,  # noqa: E402
                    state_dir, unique_dest, update_status)


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--batch")
    g.add_argument("--last", action="store_true")
    a = ap.parse_args()

    cfg = load_config()
    log = read_undo_log(cfg)
    undone = {e["batch"] for e in log if e["op"] == "undo"}
    batches = [e["batch"] for e in log if e["op"] in ("copy", "move")]
    batch = a.batch or next((b for b in reversed(batches) if b not in undone), None)
    if batch is None:
        sys.exit("되돌릴 배치 없음")
    if batch in undone:
        sys.exit(f"배치 {batch}는 이미 되돌렸음")
    ops = [e for e in log if e["batch"] == batch and e["op"] in ("copy", "move")]
    if not ops:
        sys.exit(f"배치 {batch} 기록 없음")

    trash = state_dir(cfg) / "undo_trash" / batch
    recs = load_manifest(cfg)
    ok = fail = 0
    for e in reversed(ops):
        dest, src = Path(e["dest"]), Path(e["src"])
        result = ""
        if not dest.exists():
            result = "복사본 없음(이미 치워짐) — 확인 필요"
        elif sha256_file(dest) != e["sha256"]:
            result = "복사본이 적용 후 수정됨 — 건드리지 않음, 확인 필요"
        elif e["op"] == "move":
            if src.exists():
                result = "원래 자리에 파일이 있음 — 건드리지 않음, 확인 필요"
            else:
                shutil.copy2(dest, src)
                if sha256_file(src) != e["sha256"]:
                    sys.exit(f"[중단] {e['file_id']}: 되돌린 원본 해시 불일치")
                t = unique_dest(trash / f"{e['file_id']}_{dest.name}")
                t.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(dest), str(t))
                result = "원래 자리로 복원"
        else:
            t = unique_dest(trash / f"{e['file_id']}_{dest.name}")
            t.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dest), str(t))
            result = f"복사본을 휴지통 폴더로 옮김: {t}"
        success = result.startswith(("원래", "복사본을"))
        ok += success
        fail += not success
        if success and e["file_id"] in recs:
            update_status(cfg, e["file_id"], e.get("prev_status", "planned"), dest=None, batch=None)
        print(f"  {e['file_id']}: {result}")
    log_undo(cfg, {"batch": batch, "op": "undo", "ok": ok, "needs_check": fail})
    print(f"\n배치 {batch} 되돌리기: 완료 {ok}건, 확인 필요 {fail}건. 원본은 건드리지 않았음.")


if __name__ == "__main__":
    main()
