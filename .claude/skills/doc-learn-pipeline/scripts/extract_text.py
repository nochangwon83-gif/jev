"""본문 추출: docx, pdf, txt/md, hwpx. hwp는 추출 도구(hwp5txt)가 있을 때만.

결과는 위치 표기가 붙은 조각 목록이다. 위치 표기 형식:
  docx/hwpx: "문단 N"   pdf: "p.N"   txt/md: "줄 N"
추출할 수 없으면 ExtractError를 낸다(사유에 "확인 불가"를 담는다).

사용: python extract_text.py <파일> [--max-chars N]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import UNKNOWN  # noqa: E402


class ExtractError(Exception):
    pass


def _pdf_reader():
    """pypdf의 PdfReader. 없거나 설치가 깨져 import가 실패하면 None.

    깨진 설치(예: cryptography 바인딩 오류)는 BaseException 계열 panic을 낼 수 있어 넓게 잡는다.
    """
    try:
        from pypdf import PdfReader
        return PdfReader
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:
        return None


def _xml_text_runs(xml: str, tag: str) -> list[str]:
    """<w:p> 같은 문단 태그 단위로 <?:t> 텍스트를 이어붙인다."""
    paras = []
    for p in re.findall(rf"<{tag}[ >].*?</{tag}>", xml, re.S):
        t = "".join(re.findall(r"<(?:\w+:)?t(?: [^>]*)?>([^<]*)</(?:\w+:)?t>", p))
        paras.append(_unescape(t))
    return paras


def _unescape(s: str) -> str:
    return (s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
             .replace("&apos;", "'").replace("&amp;", "&"))


def _docx(path: Path) -> list[dict]:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    paras = [p for p in _xml_text_runs(xml, "w:p")]
    return [{"loc": f"문단 {i}", "text": t} for i, t in enumerate(paras, 1) if t.strip()]


def _hwpx(path: Path) -> list[dict]:
    # hwpx(OWPML)는 Contents/section*.xml의 <hp:p> 안 <hp:t>에 글자가 있다.
    # 실제 hwpx 파일로는 이 세션에서 시험하지 못했다(확인 불가) — 첫 실행 때 결과를 확인할 것.
    segs, n = [], 0
    with zipfile.ZipFile(path) as z:
        names = sorted(x for x in z.namelist() if re.match(r"Contents/section\d+\.xml", x))
        for name in names:
            for t in _xml_text_runs(z.read(name).decode("utf-8"), "hp:p"):
                n += 1
                if t.strip():
                    segs.append({"loc": f"문단 {n}", "text": t})
    return segs


def _pdf(path: Path) -> list[dict]:
    PdfReader = _pdf_reader()
    if PdfReader is None:
        if shutil.which("pdftotext"):
            out = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True)
            pages = out.stdout.split("\f")
            return [{"loc": f"p.{i}", "text": t} for i, t in enumerate(pages, 1) if t.strip()]
        raise ExtractError(f"{UNKNOWN}: PDF 추출 도구(pypdf 또는 pdftotext) 없음")
    reader = PdfReader(str(path))
    return [{"loc": f"p.{i}", "text": (pg.extract_text() or "")}
            for i, pg in enumerate(reader.pages, 1) if (pg.extract_text() or "").strip()]


def _txt(path: Path) -> list[dict]:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp949"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ExtractError(f"{UNKNOWN}: 인코딩을 판별할 수 없음")
    return [{"loc": f"줄 {i}", "text": t} for i, t in enumerate(text.splitlines(), 1) if t.strip()]


def _hwp(path: Path) -> list[dict]:
    if not shutil.which("hwp5txt"):
        raise ExtractError(f"{UNKNOWN}: hwp 추출 도구(hwp5txt) 없음 — 사용자 확인 후 도구 결정")
    out = subprocess.run(["hwp5txt", str(path)], capture_output=True, text=True)
    if out.returncode != 0:
        raise ExtractError(f"{UNKNOWN}: hwp5txt 실패")
    return [{"loc": f"문단 {i}", "text": t} for i, t in enumerate(out.stdout.splitlines(), 1) if t.strip()]


HANDLERS = {".docx": _docx, ".pdf": _pdf, ".txt": _txt, ".md": _txt, ".hwpx": _hwpx, ".hwp": _hwp}


def extract(path: Path | str, max_chars: int | None = None) -> list[dict]:
    path = Path(path)
    handler = HANDLERS.get(path.suffix.lower())
    if handler is None:
        raise ExtractError(f"{UNKNOWN}: 지원하지 않는 형식 {path.suffix}")
    try:
        segs = handler(path)
    except ExtractError:
        raise
    except Exception as e:  # 손상 파일 등
        raise ExtractError(f"{UNKNOWN}: 추출 실패 ({type(e).__name__})") from e
    if max_chars is not None:
        out, total = [], 0
        for s in segs:
            if total >= max_chars:
                break
            out.append({"loc": s["loc"], "text": s["text"][: max_chars - total]})
            total += len(out[-1]["text"])
        segs = out
    return segs


def pdf_has_text(path: Path, pages: int = 3) -> bool | None:
    """앞쪽 몇 쪽에서 글자가 나오면 True, 없으면 False(스캔 의심), 판단 불가면 None."""
    PdfReader = _pdf_reader()
    if PdfReader is None:
        return None
    try:
        reader = PdfReader(str(path))
        return any((reader.pages[i].extract_text() or "").strip() for i in range(min(pages, len(reader.pages))))
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--max-chars", type=int)
    a = ap.parse_args()
    try:
        print(json.dumps(extract(a.path, a.max_chars), ensure_ascii=False, indent=1))
    except ExtractError as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
