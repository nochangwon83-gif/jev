"""폴더 스캔: 목록·해시를 manifest.jsonl에 기록하고 형식별 개수를 보고한다.

- 새 파일은 status=new, 해시가 바뀐 파일은 changed, 사라진 파일은 missing으로 표시한다.
- 파일을 읽기만 하고 수정·이동·삭제하지 않는다.
- --check-pdf를 주면 PDF마다 글자 추출 가능 여부를 확인해 스캔 PDF 의심 건수를 센다.

사용: python scan.py --corpus legal|novel [--root 경로] [--check-pdf]
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (UNKNOWN, append_manifest, load_config, load_manifest,  # noqa: E402
                    next_file_id, sha256_file, stamp, state_dir)
from extract_text import pdf_has_text  # noqa: E402


def walk(root: Path, exclude: set[str]):
    for p in sorted(root.rglob("*")):
        if p.is_file() and not (set(p.relative_to(root).parts[:-1]) & exclude):
            yield p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True, choices=["legal", "novel"])
    ap.add_argument("--root", help="config의 roots 대신 쓸 경로(작은 폴더로 시작할 때)")
    ap.add_argument("--check-pdf", action="store_true")
    a = ap.parse_args()

    cfg = load_config()
    root = Path(a.root or cfg["roots"][a.corpus])
    if not root.is_dir():
        sys.exit(f"루트 폴더가 없음: {root}")
    exclude = set(cfg["exclude_dirs"])

    recs = load_manifest(cfg)
    by_path = {r["path"]: r for r in recs.values() if r["corpus"] == a.corpus}
    seen, counts, new_ids = set(), Counter(), []
    pdf_scan, pdf_unknown = 0, 0

    for p in walk(root, exclude):
        sp = str(p)
        seen.add(sp)
        ext = p.suffix.lower() or "(확장자 없음)"
        counts[ext] += 1
        if ext == ".pdf" and a.check_pdf:
            r = pdf_has_text(p)
            pdf_scan += r is False
            pdf_unknown += r is None
        st = p.stat()
        digest = sha256_file(p)
        old = by_path.get(sp)
        if old is None:
            fid = next_file_id(recs)
            rec = {"file_id": fid, "corpus": a.corpus, "path": sp, "rel": str(p.relative_to(root)),
                   "root": str(root), "ext": ext, "size": st.st_size, "mtime": int(st.st_mtime),
                   "sha256": digest, "status": "new"}
            recs[fid] = rec
            append_manifest(cfg, rec)
            new_ids.append(fid)
        elif old["status"] == "missing":
            append_manifest(cfg, dict(old, sha256=digest, size=st.st_size, mtime=int(st.st_mtime),
                                      status="changed" if old["sha256"] != digest else "new"))
            new_ids.append(old["file_id"])
        elif old["sha256"] != digest:
            append_manifest(cfg, dict(old, sha256=digest, size=st.st_size, mtime=int(st.st_mtime),
                                      prev_sha256=old["sha256"], status="changed"))
            new_ids.append(old["file_id"])

    missing = [r for r in by_path.values() if r["path"] not in seen and r["status"] != "missing"]
    for r in missing:
        append_manifest(cfg, dict(r, status="missing"))

    lines = [f"# 스캔 보고 ({a.corpus})", "", f"- 루트: `{root}`", f"- 파일 수: {sum(counts.values())}",
             f"- 새로 추가·변경된 파일: {len(new_ids)}", f"- 사라진 파일(원본 없음 표시): {len(missing)}", "",
             "| 형식 | 개수 |", "|---|---|"]
    lines += [f"| {e} | {n} |" for e, n in counts.most_common()]
    hwp = counts[".hwp"] + counts[".hwpx"]
    lines += ["", f"- hwp/hwpx 포함: {'예' if hwp else '아니오'} ({hwp}건)"]
    if a.check_pdf:
        lines.append(f"- 스캔 PDF 의심(앞 3쪽에서 글자 추출 안 됨): {pdf_scan}건"
                     + (f", 판단 {UNKNOWN}: {pdf_unknown}건" if pdf_unknown else ""))
    else:
        lines.append(f"- 스캔 PDF 여부: {UNKNOWN} (--check-pdf 로 다시 실행하면 집계)")
    report = "\n".join(lines) + "\n"
    out = state_dir(cfg) / f"scan_report_{a.corpus}_{stamp()}.md"
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"보고 파일: {out}")
    if new_ids:
        print("다음 단계 대상 파일 번호:", ",".join(new_ids))


if __name__ == "__main__":
    main()
