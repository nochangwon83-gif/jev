"""doc-learn-pipeline 공통 함수: 설정, 해시, manifest, undo.log, 경중표 읽기.

표준 라이브러리만 사용한다(Windows PC에서 별도 설치 없이 동작하도록).
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
UNKNOWN = "확인 불가"

# manifest 상태값. 단계 스크립트는 이 상태를 보고 이어서 실행한다(안전장치 8: 상태 복구).
STATUSES = ["new", "changed", "planned", "applied", "carded", "noted", "missing"]


def now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def stamp() -> str:
    return _dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def load_config() -> dict:
    """config.json을 읽는다. DLP_CONFIG 환경변수로 다른 설정 파일을 지정할 수 있다(시연용)."""
    path = Path(os.environ.get("DLP_CONFIG", SKILL_DIR / "config.json"))
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg["_config_path"] = str(path)
    return cfg


def _resolve(cfg: dict, key: str) -> Path:
    p = Path(cfg[key])
    if not p.is_absolute():
        p = Path(cfg["_config_path"]).parent / p
    p.mkdir(parents=True, exist_ok=True)
    return p


def state_dir(cfg: dict) -> Path:
    return _resolve(cfg, "state_dir")


def output_dir(cfg: dict) -> Path:
    return _resolve(cfg, "output_dir")


def sha256_file(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- manifest
def manifest_path(cfg: dict) -> Path:
    return state_dir(cfg) / "manifest.jsonl"


def load_manifest(cfg: dict) -> dict[str, dict]:
    """file_id -> 최신 기록. JSONL은 추가만 하고 마지막 줄이 최신이다."""
    recs: dict[str, dict] = {}
    mp = manifest_path(cfg)
    if mp.exists():
        for line in mp.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                recs[r["file_id"]] = r
    return recs


def append_manifest(cfg: dict, rec: dict) -> None:
    rec = dict(rec, updated=now())
    with open(manifest_path(cfg), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def update_status(cfg: dict, file_id: str, status: str, **extra) -> None:
    assert status in STATUSES, status
    rec = load_manifest(cfg)[file_id]
    rec.update(extra, status=status)
    append_manifest(cfg, rec)


def next_file_id(recs: dict) -> str:
    n = max((int(k[1:]) for k in recs), default=0) + 1
    return f"F{n:04d}"


# ---------------------------------------------------------------- undo.log
def undo_log_path(cfg: dict) -> Path:
    return state_dir(cfg) / "undo.log"


def log_undo(cfg: dict, entry: dict) -> None:
    entry = dict(entry, ts=now())
    with open(undo_log_path(cfg), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_undo_log(cfg: dict) -> list[dict]:
    p = undo_log_path(cfg)
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


# ---------------------------------------------------------------- 경중표
def severity_table_path() -> Path:
    """경중표 위치. DLP_SEVERITY_TABLE로 다른 파일을 지정할 수 있다(테스트용)."""
    return Path(os.environ.get("DLP_SEVERITY_TABLE", SKILL_DIR / "references" / "severity-table.md"))


def read_severity_table() -> dict[str, dict]:
    """경중표의 표를 읽어 단계ID -> 행(dict)으로 돌려준다."""
    text = severity_table_path().read_text(encoding="utf-8")
    rows = [l for l in text.splitlines() if l.strip().startswith("|")]
    header = [c.strip() for c in rows[0].strip("|").split("|")]
    table = {}
    for line in rows[2:]:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        row = dict(zip(header, cells))
        table[row["단계ID"]] = row
    return table


# ---------------------------------------------------------------- .env
def load_env() -> dict[str, str]:
    """스킬 폴더의 .env를 읽는다(DLP_ENV_FILE로 다른 파일 지정 가능, 테스트용). 값은 절대 출력하지 않는다."""
    env = {}
    p = Path(os.environ.get("DLP_ENV_FILE", SKILL_DIR / ".env"))
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)\s*$", line)
            if m and not line.lstrip().startswith("#"):
                env[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return env


def unique_dest(dest: Path) -> Path:
    """같은 이름이 있으면 덮어쓰지 않고 ' (2)', ' (3)' ... 을 붙인다."""
    if not dest.exists():
        return dest
    n = 2
    while True:
        cand = dest.with_name(f"{dest.stem} ({n}){dest.suffix}")
        if not cand.exists():
            return cand
        n += 1
