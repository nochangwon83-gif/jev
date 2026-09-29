"""실행 준비 점검(스킬 시작 시 Claude가 먼저 실행한다).

확인 항목: Python 버전, 작업 폴더(쓰기 가능 여부), 자료 루트 존재, PDF·hwp 추출 도구, claude 실행 파일,
JEV_API_KEY 유무(값은 출력 안 함), jev(TypeSafe API) 연결(GET /v1/models — 문서 내용은 보내지 않음).

  python doctor.py                 점검만
  python doctor.py --save-key      표준 입력으로 받은 키를 작업 폴더의 .env에 저장(화면에 출력 안 함)
"""
from __future__ import annotations

import argparse
import getpass
import os
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import SKILL_DIR, _writable, load_config, work_dir  # noqa: E402
from extract_text import _pdf_reader  # noqa: E402
from jev_route import DEFAULT_BASE_URL, api_key  # noqa: E402


def save_key() -> None:
    key = (sys.stdin.readline() if not sys.stdin.isatty() else getpass.getpass("JEV_API_KEY: ")).strip()
    if not key or " " in key or not key.isprintable():
        sys.exit("키가 비었거나 형식이 올바르지 않음")
    env = work_dir() / ".env"
    lines = [l for l in (env.read_text(encoding="utf-8").splitlines() if env.exists() else [])
             if not l.startswith("JEV_API_KEY=")]
    env.write_text("\n".join(lines + [f"JEV_API_KEY={key}"]) + "\n", encoding="utf-8")
    try:
        os.chmod(env, 0o600)
    except OSError:
        pass
    print(f"저장함: {env} (값은 출력하지 않음)")


def jev_check() -> str:
    key = api_key()
    if not key:
        return "건너뜀(키 없음)"
    base = (os.environ.get("TYPESAFE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    req = urllib.request.Request(base + "/v1/models", headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return f"연결됨(HTTP {r.status})"
    except urllib.error.HTTPError as e:
        return f"서버 응답 HTTP {e.code}" + (" — 키 확인 필요" if e.code in (401, 403) else "")
    except Exception as e:
        return f"연결 실패: {type(e).__name__}: {e}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save-key", action="store_true")
    a = ap.parse_args()
    if a.save_key:
        save_key()
        return
    cfg = load_config()
    wd = work_dir()
    rows = [
        ("Python", sys.version.split()[0], sys.version_info >= (3, 9)),
        ("스킬 폴더", str(SKILL_DIR), True),
        ("작업 폴더(상태·산출물·.env)", f"{wd} ({'쓰기 가능' if _writable(wd) else '쓰기 불가'})", _writable(wd)),
    ]
    for k, v in cfg["roots"].items():
        rows.append((f"자료 루트 {k}", v, Path(v).is_dir()))
    rows += [
        ("PDF 본문 추출(pypdf)", "있음" if _pdf_reader() else "없음 — pip install pypdf (없으면 PDF 본문 = 확인 불가)", True),
        ("hwp 추출(hwp5txt)", "있음" if shutil.which("hwp5txt") else "없음 — hwp 본문 = 확인 불가", True),
        ("claude 실행 파일(--execute용)", shutil.which("claude") or "없음 — --execute 없이 프롬프트만 출력", True),
        ("JEV_API_KEY", "설정됨" if api_key() else "없음 — doctor.py --save-key 로 저장", bool(api_key())),
    ]
    jc = jev_check()
    rows.append(("jev(TypeSafe API) 연결", jc, jc.startswith("연결됨")))
    print("# doc-learn-pipeline 준비 점검\n")
    for name, val, ok in rows:
        print(f"{'✔' if ok else '✘'} {name}: {val}")
    blockers = [n for n, _, ok in rows if not ok]
    print("\n막힌 항목: " + (", ".join(blockers) if blockers else "없음"))
    if any(n.startswith("jev") or n == "JEV_API_KEY" for n in blockers):
        print("jev가 안 되면 경중표 기준 등급으로 진행하고, 경중표 보정(propose)은 모든 행이 '제외'로 나온다.")


if __name__ == "__main__":
    main()
