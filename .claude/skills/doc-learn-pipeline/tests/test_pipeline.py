"""9장 안전장치 8개와 주요 규칙을 가상 샘플로 확인하는 테스트.

사용: python -m unittest tests/test_pipeline.py   (스킬 폴더에서)
PDF 관련 확인은 pypdf가 있을 때만 의미가 있다(없으면 PDF 본문은 '확인 불가'로 처리됨).
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL / "scripts"


def read_csv(p: Path) -> list[dict]:
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name) / "demo"
        self.base.mkdir()
        subprocess.run([sys.executable, str(SKILL / "tests" / "make_samples.py"), str(self.base)],
                       check=True, capture_output=True)
        # 실제 .env의 키·실제 API를 쓰지 않도록 빈 env 파일과 닿지 않는 주소를 지정한다.
        self.env = dict(os.environ, DLP_CONFIG=str(self.base / "config.json"),
                        DLP_ENV_FILE=str(self.base / "no.env"), TYPESAFE_BASE_URL="http://127.0.0.1:9")
        for k in ("JEV_API_KEY", "TYPESAFE_API_KEY"):
            self.env.pop(k, None)
        self.originals = {p: sha(p) for p in self.base.rglob("*")
                          if p.is_file() and p.name != "config.json"}
        self.run_ok("scan.py", "--corpus", "legal")
        self.run_ok("scan.py", "--corpus", "novel")

    def tearDown(self):
        self.tmp.cleanup()

    def sh(self, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / args[0]), *args[1:]],
                              capture_output=True, text=True, env=self.env, cwd=SCRIPTS)

    def run_ok(self, *args):
        r = self.sh(*args)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def plan(self, corpus: str, approve=None) -> Path:
        out = self.base / f"plan_{corpus}.csv"
        self.run_ok("classify_plan.py", "--corpus", corpus, "--mode", "auto", "--out", str(out))
        rows = read_csv(out)
        for r in rows:
            r["승인"] = "Y" if approve is None or r["번호"] in approve else ""
        with open(out, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=rows[0].keys())
            w.writeheader()
            w.writerows(rows)
        return out

    def originals_intact(self):
        for p, h in self.originals.items():
            self.assertTrue(p.exists(), p)
            self.assertEqual(sha(p), h, p)

    def card(self, name: str, draft: dict):
        p = self.base / f"{name}.json"
        p.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
        return self.sh("make_card.py", "--draft", str(p))

    # 1 미리보기 우선 + 2 원본 보존 + 3 되돌리기 + 4 해시 검증
    def test_plan_apply_undo(self):
        plan = self.plan("legal", approve={"F0001", "F0002"})
        dest_root = self.base / "legal" / "_정리본"
        self.assertFalse(dest_root.exists(), "계획 단계에서 파일을 만들면 안 됨")
        r = self.run_ok("apply_plan.py", str(plan))
        self.assertIn("승인 2행", r.stdout)
        self.assertEqual(len([p for p in dest_root.rglob("*") if p.is_file()]), 2)
        batch = r.stdout.split("undo.py --batch ")[1].split()[0]
        self.run_ok("undo.py", "--batch", batch)
        self.assertEqual([p for p in dest_root.rglob("*") if p.is_file()], [])
        self.originals_intact()

    def test_no_overwrite(self):
        plan = self.plan("legal", approve={"F0006"})
        row = next(r for r in read_csv(plan) if r["번호"] == "F0006")
        existing = Path(row["제안 경로"])
        existing.parent.mkdir(parents=True)
        existing.write_text("기존 파일", encoding="utf-8")
        self.run_ok("apply_plan.py", str(plan))
        self.assertEqual(existing.read_text(encoding="utf-8"), "기존 파일")
        self.assertTrue(existing.with_name(f"{existing.stem} (2){existing.suffix}").exists())

    def test_source_changed_after_scan_stops(self):
        plan = self.plan("novel", approve={"F0009"})
        src = next(p for p in self.originals if p.name.startswith("천검록"))
        src.write_text(src.read_text(encoding="utf-8") + "추가\n", encoding="utf-8")
        r = self.sh("apply_plan.py", str(plan))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("원본이 바뀜", r.stdout + r.stderr)

    def test_move_needs_explicit_phrase(self):
        plan = self.plan("novel")
        r = self.sh("apply_plan.py", str(plan), "--move")
        self.assertNotEqual(r.returncode, 0)
        self.originals_intact()

    def test_dest_outside_dest_root_refused(self):
        plan = self.plan("novel", approve={"F0009"})
        rows = read_csv(plan)
        for r in rows:
            r["제안 경로"] = str(self.base / "novel" / "무협" / "덮어쓰기시도.txt")
        with open(plan, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=rows[0].keys())
            w.writeheader()
            w.writerows(rows)
        r = self.sh("apply_plan.py", str(plan))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("정리본 폴더", r.stdout + r.stderr)

    # 5 원문 대조
    def test_card_verification_and_tamper(self):
        ok = {"file_id": "F0009", "field": "웹소설", "type": "웹소설", "summary": ["도입부 요약."],
              "quotes": [{"text": "강호에 피바람이 불었다.", "loc": "줄 2"}], "topics": ["무협/도입부"], "extra": {}}
        self.assertEqual(self.card("ok", ok).returncode, 0)
        self.run_ok("verify_cards.py", "--all")
        bad = dict(ok, file_id="F0010", quotes=[{"text": "원문에 없는 문장이다.", "loc": "줄 2"}])
        self.assertEqual(self.card("bad", bad).returncode, 0)
        r = self.sh("verify_cards.py", "--all")
        self.assertEqual(r.returncode, 1)
        c2 = json.loads((self.base / "work/_output/cards/C-0002.json").read_text(encoding="utf-8"))
        self.assertEqual(c2["verification"], "검증 미완료")
        self.assertEqual(c2["quotes"][0]["check"], "확인 불가")

    def test_wrong_location_fails(self):
        d = {"file_id": "F0009", "field": "웹소설", "type": "웹소설", "summary": ["요약."],
             "quotes": [{"text": "강호에 피바람이 불었다.", "loc": "줄 3"}], "topics": ["t"], "extra": {}}
        self.card("loc", d)
        self.assertEqual(self.sh("verify_cards.py", "--all").returncode, 1)

    def test_novel_long_quote_rejected(self):
        d = {"file_id": "F0009", "field": "웹소설", "type": "웹소설", "summary": ["요약."],
             "quotes": [{"text": "가" * 41, "loc": "줄 2"}], "topics": ["t"], "extra": {}}
        r = self.card("long", d)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("상한", r.stdout + r.stderr)

    def test_unknown_fields_marked(self):
        d = {"file_id": "F0009", "field": "웹소설", "type": "웹소설", "summary": ["요약."],
             "quotes": [{"text": "강호에 피바람이 불었다."}], "topics": ["t"], "extra": {}}
        self.card("unk", d)
        c = json.loads((self.base / "work/_output/cards/C-0001.json").read_text(encoding="utf-8"))
        self.assertEqual(c["quotes"][0]["loc"], "확인 불가")
        self.assertEqual(c["extra"]["전개 패턴"], "확인 불가")

    def test_card_update_rules(self):
        d = {"file_id": "F0009", "field": "웹소설", "type": "웹소설", "summary": ["요약."],
             "quotes": [{"text": "강호에 피바람이 불었다.", "loc": "줄 2"}], "topics": ["t"], "extra": {}}
        self.card("a", d)
        src = next(p for p in self.originals if p.name.startswith("천검록"))
        src.write_text(src.read_text(encoding="utf-8") + "추가\n", encoding="utf-8")
        r = self.run_ok("make_card.py", "--refresh")
        self.assertIn("원본 변경", r.stdout)
        self.run_ok("scan.py", "--corpus", "novel")
        self.assertEqual(self.card("a", d).returncode, 0)  # 해시 바뀜 → 개정
        self.assertTrue((self.base / "work/_output/cards/_history/C-0001_v1.json").exists())
        src.unlink()
        r = self.run_ok("make_card.py", "--refresh")
        self.assertIn("원본 없음", r.stdout)
        self.assertTrue((self.base / "work/_output/cards/C-0001.json").exists())

    def test_notes_need_card_ids(self):
        d = {"file_id": "F0009", "field": "웹소설", "type": "웹소설", "summary": ["도입부는 짧다."],
             "quotes": [{"text": "강호에 피바람이 불었다.", "loc": "줄 2"}], "topics": ["무협/도입부"], "extra": {}}
        self.card("n", d)
        self.run_ok("verify_cards.py", "--all")
        self.run_ok("notes_scaffold.py")
        notes = self.base / "work/_output/notes"
        self.run_ok("verify_cards.py", "--notes", str(notes))
        note = next(notes.glob("*.md"))
        note.write_text(note.read_text(encoding="utf-8") + "- 근거 없는 문장.\n", encoding="utf-8")
        self.assertEqual(self.sh("verify_cards.py", "--notes", str(notes)).returncode, 1)

    # 6 사람 승인
    def test_skill_proposal_never_edits_and_apply_needs_approval(self):
        d = {"file_id": "F0009", "field": "웹소설", "type": "웹소설", "summary": ["요약."],
             "quotes": [{"text": "강호에 피바람이 불었다.", "loc": "줄 2"}], "topics": ["t"], "extra": {}}
        self.card("s", d)
        self.run_ok("verify_cards.py", "--all")
        sk = self.base / "skills" / "webnovel-writer"
        sk.mkdir(parents=True)
        (sk / "SKILL.md").write_text("# x\n- 총기는 영문으로 표기한다.\n- 도입부.\n", encoding="utf-8")
        before = sha(sk / "SKILL.md")
        draft = {"skill": "webnovel-writer", "items": [
            {"id": "P1", "type": "추가", "before": "- 도입부.", "after": "- 짧은 문장으로 연다.", "card_ids": ["C-0001"]},
            {"id": "P2", "type": "수정", "before": "- 총기는 영문으로 표기한다.", "after": "- 총기 이름은 한글로 표기한다.",
             "card_ids": ["C-0001"]}]}
        dp = self.base / "prop.json"
        dp.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
        self.run_ok("propose_skill_update.py", "--draft", str(dp), "--skill-path", str(sk / "SKILL.md"))
        self.assertEqual(sha(sk / "SKILL.md"), before)
        meta = json.loads(next((self.base / "work/_proposals").glob("*.json")).read_text(encoding="utf-8"))
        self.assertEqual([i["status"] for i in meta["items"]], ["적용 대상", "제외"])
        prop = str(next((self.base / "work/_proposals").glob("*.json")))
        self.assertNotEqual(self.sh("apply_skill_update.py", "--proposal", prop, "--approve", "P1").returncode, 0)
        self.assertNotEqual(self.sh("apply_skill_update.py", "--proposal", prop, "--approve", "P2",
                                     "--confirm", "승인함").returncode, 0)
        self.assertEqual(sha(sk / "SKILL.md"), before)
        self.run_ok("apply_skill_update.py", "--proposal", prop, "--approve", "P1", "--confirm", "승인함")
        self.assertIn("짧은 문장으로 연다", (sk / "SKILL.md").read_text(encoding="utf-8"))
        self.assertEqual(len(list((self.base / "work/_backup").rglob("SKILL.md"))), 1)

    # 7 외부 전송 통제
    def test_prompt_templates_and_violations(self):
        self.run_ok("check_prompts.py")
        r = self.sh("check_prompts.py", "--text", "2099가합00001 사건 요약")
        self.assertEqual(r.returncode, 1)
        r = self.sh("check_prompts.py", "--text", "천검록 파일 요약")
        self.assertIn("T6", r.stdout)
        r = self.run_ok("run_stage.py", "--stage", "S2l", "--files", "F0001,F0002")
        self.assertIn("대상 파일 번호: F0001,F0002", r.stdout)
        self.assertNotIn("공사도급계약서", r.stdout)

    def test_severity_table_drives_stage(self):
        r = self.run_ok("run_stage.py", "--stage", "S1a", "--files", "F0001", "--router", "table")
        self.assertIn("최종 등급: fast", r.stdout)
        r = self.run_ok("run_stage.py", "--stage", "S5")  # 키 없음 → 경중표 기준값
        self.assertIn("JEV_API_KEY 없음", r.stdout)
        self.assertIn("최종 등급: strong", r.stdout)

    # jev 직접 판단: TypeSafe API를 흉내 낸 로컬 서버로 요청 형식·판단 반영·실행을 확인
    def _mock_jev(self, tier, conf, severity):
        import http.server
        import threading
        seen = {}

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                seen["path"] = self.path
                seen["auth"] = self.headers.get("Authorization")
                seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                out = json.dumps({"model": "jev-test", "usage": {}, "answers": {
                    "tier": {"type": "choice", "choice": tier, "confidence": conf,
                             "probabilities": {t: (conf if t == tier else (1 - conf) / 2)
                                               for t in ("fast", "balanced", "strong")}},
                    "severity": {"type": "score", "score": severity, "confidence": 0.9,
                                 "legend": {}, "probabilities": {}}}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *a):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        (self.base / "fake.env").write_text("JEV_API_KEY=test-key\n", encoding="utf-8")
        self.env.update(DLP_ENV_FILE=str(self.base / "fake.env"),
                        TYPESAFE_BASE_URL=f"http://127.0.0.1:{srv.server_address[1]}")
        self.env.pop("HTTP_PROXY", None)
        self.env.pop("http_proxy", None)
        self.env["NO_PROXY"] = self.env["no_proxy"] = "127.0.0.1,localhost"
        return seen

    def test_jev_decides_tier_and_request_has_no_content(self):
        seen = self._mock_jev("fast", 0.9, 0.8)
        r = self.run_ok("run_stage.py", "--stage", "S1b", "--files", "F0002,F0009")
        self.assertIn("jev 응답 받음", r.stdout)
        self.assertIn("최종 등급: fast (haiku)", r.stdout)  # 경중표 기준 balanced → jev가 fast로 판단
        self.assertEqual(seen["path"], "/v1/systemone")
        self.assertEqual(seen["auth"], "Bearer test-key")
        body = seen["body"]
        self.assertEqual(body["model"], "jev-latest")
        self.assertEqual(body["questions"]["tier"]["type"], "choice")
        self.assertEqual(body["questions"]["severity"]["type"], "score")
        self.assertEqual(body["state"]["inputs"]["file_count"], 2)
        sent = json.dumps(body, ensure_ascii=False)
        for name in ("공사도급계약서", "천검록", "F0002", "가상현장", "강호"):
            self.assertNotIn(name, sent)  # 파일명·파일 번호·본문 모두 전송 안 함
        dec = (self.base / "work/_state/jev_decisions.jsonl").read_text(encoding="utf-8")
        self.assertIn('"final_tier": "fast"', dec)

    def test_jev_low_confidence_never_downgrades(self):
        self._mock_jev("fast", 0.4, 0.8)
        r = self.run_ok("run_stage.py", "--stage", "S1b", "--files", "F0002")
        self.assertIn("최종 등급: balanced", r.stdout)
        self.assertIn("낮추지 않음", r.stdout)

    def test_jev_severity_score_raises_tier(self):
        self._mock_jev("fast", 0.9, 2.9)
        r = self.run_ok("run_stage.py", "--stage", "S1a", "--files", "F0002")
        self.assertIn("최종 등급: strong", r.stdout)

    def test_pinned_stage_stays_strong(self):
        self._mock_jev("fast", 0.99, 0.5)
        r = self.run_ok("run_stage.py", "--stage", "S2l", "--files", "F0002")
        self.assertIn("최종 등급: strong (opus)", r.stdout)
        self.assertIn("strong 고정 단계", r.stdout)

    def test_execute_launches_claude_with_chosen_model(self):
        self._mock_jev("balanced", 0.9, 1.6)
        bindir = self.base / "bin"
        bindir.mkdir()
        log = self.base / "claude_args.json"
        fake = bindir / "claude"
        fake.write_text(f"#!{sys.executable}\nimport json,sys\njson.dump(sys.argv[1:], open({str(log)!r}, 'w'))\n",
                        encoding="utf-8")
        fake.chmod(0o755)
        self.env["PATH"] = f"{bindir}{os.pathsep}{self.env['PATH']}"
        self.run_ok("run_stage.py", "--stage", "S2n", "--files", "F0009", "--execute")
        args = json.loads(log.read_text(encoding="utf-8"))
        self.assertEqual(args[:2], ["--model", "sonnet"])
        self.assertIn("대상 파일 번호: F0009", args[2])

    # 8 상태 복구
    def test_resume_skips_applied(self):
        plan = self.plan("novel")
        self.run_ok("apply_plan.py", str(plan))
        r = self.run_ok("apply_plan.py", str(plan))
        self.assertIn("적용 0건, 이미 적용되어 건너뜀 3건", r.stdout)
        r = self.run_ok("pipeline_status.py")
        self.assertIn("novel / applied: 3건", r.stdout)


if __name__ == "__main__":
    unittest.main()
