"""승인된 스킬 반영 제안만 적용(안전장치 6: 사람 승인·백업).

- --approve 로 사람이 고른 항목 ID와 --confirm "승인함" 이 모두 있어야 실행한다. 자동 실행 경로는 없다.
- 제안서 작성 이후 SKILL.md가 바뀌었으면 중단한다(해시 비교).
- '제외' 항목은 승인해도 적용하지 않는다. 적용 직전에 근거 카드가 여전히 '원문 대조 완료'인지 다시 본다.
- 적용 전 SKILL.md를 _backup/<스킬명>_<시각>/SKILL.md 로 보관하고, 변경 이력을 _state/skill_changelog.md에 남긴다.

사용: python apply_skill_update.py --proposal _proposals/x.json --approve P1,P3 --confirm "승인함"
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import _resolve, load_config, now, sha256_file, stamp, state_dir  # noqa: E402
from make_card import load_cards  # noqa: E402

PHRASE = "승인함"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proposal", required=True)
    ap.add_argument("--approve", required=True)
    ap.add_argument("--confirm", default="")
    a = ap.parse_args()
    if a.confirm != PHRASE:
        sys.exit(f'사람 승인 확인 문구가 없음: --confirm "{PHRASE}"')
    cfg = load_config()
    meta = json.loads(Path(a.proposal).read_text(encoding="utf-8"))
    sp = Path(meta["skill_path"])
    if sha256_file(sp) != meta["skill_sha256"]:
        sys.exit("[중단] 제안서 작성 이후 SKILL.md가 바뀜 — 제안서를 다시 만들 것")
    want = a.approve.split(",")
    items = {it["id"]: it for it in meta["items"]}
    cards = load_cards(cfg)
    chosen = []
    for pid in want:
        it = items.get(pid)
        if it is None:
            sys.exit(f"[중단] 없는 항목 {pid}")
        if it["status"] != "적용 대상":
            sys.exit(f"[중단] {pid}는 '제외' 항목: {'; '.join(it['exclude_reasons'])}")
        bad = [c for c in it["card_ids"] if cards.get(c, {}).get("verification") != "원문 대조 완료"]
        if bad:
            sys.exit(f"[중단] {pid}의 근거 카드가 원문 대조 미통과: {bad}")
        chosen.append(it)

    text = sp.read_text(encoding="utf-8")
    for it in chosen:
        if text.count(it["before"]) != 1:
            sys.exit(f"[중단] {it['id']}: 변경 전 문구를 1회로 특정 못함(앞 항목 적용으로 바뀌었을 수 있음)")
        if it["type"] == "수정":
            text = text.replace(it["before"], it["after"])
        elif it["type"] == "삭제":
            text = text.replace(it["before"], "")
        else:
            text = text.replace(it["before"], it["before"] + "\n" + it["after"])

    bdir = _resolve(cfg, "backup_dir") / f"{meta['skill']}_{stamp()}"
    bdir.mkdir(parents=True)
    shutil.copy2(sp, bdir / "SKILL.md")
    sp.write_text(text, encoding="utf-8")

    log = state_dir(cfg) / "skill_changelog.md"
    with open(log, "a", encoding="utf-8") as f:
        f.write(f"\n## {now()} {meta['skill']}\n- 백업: `{bdir / 'SKILL.md'}`\n- 제안서: `{a.proposal}`\n")
        for it in chosen:
            f.write(f"- {it['id']} {it['type']} (근거 {', '.join(it['card_ids'])}): {it.get('reason', '')}\n")
    print(f"적용 {len(chosen)}건. 백업: {bdir / 'SKILL.md'}  이력: {log}")


if __name__ == "__main__":
    main()
