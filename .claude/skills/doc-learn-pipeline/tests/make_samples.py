"""시연용 가상 샘플 10개와 시연 설정(config.json)을 만든다. 내용은 모두 가상이다.

사용: python make_samples.py <빈 폴더>
만들어지는 것:
  <폴더>/legal/…  7개 (docx 3, 글자 있는 pdf 1, 글자 없는 pdf 1(스캔 PDF 흉내), txt 1, 가짜 hwp 1)
  <폴더>/novel/…  3개 (txt)
  <폴더>/config.json   (roots·dest_roots·state/output 위치를 이 폴더로 지정)
글자 있는 PDF는 reportlab(없으면 LibreOffice)으로 만든다. 둘 다 없으면 그 파일은 txt로 대신 만든다고 알린다.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

CT = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
      '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
      '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
      '<Default Extension="xml" ContentType="application/xml"/>'
      '<Override PartName="/word/document.xml" '
      'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/></Relationships>')


def docx(path: Path, paras: list[str]) -> None:
    body = "".join(f'<w:p><w:r><w:t xml:space="preserve">{escape(p)}</w:t></w:r></w:p>' for p in paras)
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           f"<w:body>{body}</w:body></w:document>")
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CT)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/document.xml", doc)


def blank_pdf(path: Path) -> None:
    """글자 레이어가 없는 1쪽 PDF(스캔 PDF 흉내)."""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R >>",
            b"<< /Length 0 >>\nstream\n\nendstream"]
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(out))


FONTS = [("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0), ("C:/Windows/Fonts/malgun.ttf", None)]


def _reportlab_pdf(path: Path, paras: list[str]) -> bool:
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen import canvas
    except ImportError:
        return False
    font = next(((f, i) for f, i in FONTS if Path(f).exists()), None)
    if font is None:
        return False
    kw = {"subfontIndex": font[1]} if font[1] is not None else {}
    pdfmetrics.registerFont(TTFont("K", font[0], **kw))
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path))
    c.setFont("K", 11)
    y = 800
    for para in paras:  # 공백에서 줄바꿈(원문 대조 시 공백 차이만 생기도록)
        line = ""
        for word in para.split(" "):
            if len(line) + len(word) > 38:
                c.drawString(50, y, line.rstrip())
                y, line = y - 16, ""
            line += word + " "
        c.drawString(50, y, line.rstrip())
        y -= 24
    c.save()
    return True


def text_pdf(path: Path, paras: list[str]) -> bool:
    if _reportlab_pdf(path, paras):
        return True
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return False
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / (path.stem + ".docx")
        docx(src, paras)
        subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", td, str(src)],
                       capture_output=True, timeout=180)
        made = Path(td) / (path.stem + ".pdf")
        if not made.exists():
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(made, path)
    return True


def main():
    base = Path(sys.argv[1]).resolve()
    if base.exists() and any(base.iterdir()):
        sys.exit(f"빈 폴더를 지정할 것: {base}")
    L, N = base / "legal", base / "novel"

    docx(L / "계약서" / "공사도급계약서_가상현장.docx", [
        "공사도급계약서(가상 샘플)",
        "제1조(목적) 이 계약은 도급인과 수급인 사이의 공사도급계약에 관한 사항을 정한다.",
        "제5조(지체상금) 수급인이 준공기한 내에 공사를 완성하지 못한 경우 지체일수 1일마다 계약금액의 1000분의 1을 지체상금으로 도급인에게 지급한다.",
        "지체상금의 총액은 계약금액의 100분의 10을 초과하지 아니한다.",
        "제9조(하자담보) 수급인은 준공일부터 2년간 하자담보책임을 진다.",
    ])
    pdf_paras = ["대출약정서(가상 샘플)",
                 "제3조(기한의 이익 상실) 차주가 이자를 2회 이상 연체한 경우 대주는 차주에 대한 서면 통지로 기한의 이익을 상실시킬 수 있다."]
    if not text_pdf(L / "계약서" / "PF대출약정_가상.pdf", pdf_paras):
        print("PDF 생성 도구(reportlab/soffice) 없음: PF대출약정_가상.pdf 대신 txt로 만듦")
        (L / "계약서" / "PF대출약정_가상.txt").write_text("\n".join(pdf_paras), encoding="utf-8")
    blank_pdf(L / "계약서" / "스캔본_가상.pdf")
    docx(L / "소송기록" / "2099가합00001_준비서면_가상.docx", [
        "준비서면(가상 샘플)", "원고는 기성금 청구에 관하여 다음과 같이 주장을 보완합니다."])
    (L / "소송기록" / "답변서_가상.txt").write_text(
        "답변서(가상 샘플)\n청구취지에 대한 답변\n원고의 청구를 기각한다.\n", encoding="utf-8")
    (L / "소송기록" / "메모_가상.hwp").write_bytes(b"\xd0\xcf\x11\xe0 fake hwp sample (not a real hwp)")
    docx(L / "미분류" / "자료1.docx", [
        "관리형토지신탁계약서(가상 샘플)", "위탁자는 신탁부동산을 수탁자에게 신탁한다."])

    N.mkdir(parents=True)
    for rel, text in {
        "무협/천검록_가상_1화.txt": "1화\n강호에 피바람이 불었다.\n청년은 내공을 끌어올려 초식을 펼쳤다.\n",
        "기타/작품A_가상_3화.txt": "3화\n황녀는 공작가의 영애를 바라보았다.\n황태자의 약혼식이 사흘 뒤였다.\n",
        "판타지/마탑의_견습생_가상_1화.txt": "1화\n마탑의 견습생은 마나를 모았다.\n",
    }.items():
        (N / rel).parent.mkdir(parents=True, exist_ok=True)
        (N / rel).write_text(text, encoding="utf-8")

    skill_config = json.loads((Path(__file__).resolve().parent.parent / "config.json").read_text(encoding="utf-8"))
    cfg = dict(skill_config, roots={"legal": str(L), "novel": str(N)},
               dest_roots={"legal": str(L / "_정리본"), "novel": str(N / "_정리본")},
               state_dir="work/_state", output_dir="work/_output",
               proposals_dir="work/_proposals", backup_dir="work/_backup")
    cfg["_설명"] = "시연용 설정(가상 샘플)."
    (base / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    files = [p for p in base.rglob("*") if p.is_file() and p.name != "config.json"]
    print(f"샘플 {len(files)}개 생성: {base}")
    for p in sorted(files):
        print("  ", p.relative_to(base))


if __name__ == "__main__":
    main()
