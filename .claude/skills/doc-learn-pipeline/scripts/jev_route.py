"""jev가 단계의 경중과 모델 등급을 직접 판단한다(TypeSafe System One API, 모델 jev-latest).

요청 형식은 공식 Python SDK typesafe-sdk 0.7.2 소스에서 확인한 것을 따른다:
  POST {TYPESAFE_BASE_URL 또는 https://api.typesafe.ai}/v1/systemone
  헤더 Authorization: Bearer <키>
  본문 {"state": …, "model": "jev-latest", "questions": {이름: {"type": "choice"|"score", "instructions", "criteria"}}}
  응답 answers.<이름> = choice: {choice, confidence, probabilities} / score: {score, confidence, legend, probabilities}
SDK를 설치하지 않아도 되도록 표준 라이브러리(urllib)로 같은 요청을 보낸다.

jev에 보내는 state에는 경중표의 '단계 작업'·'작업 설명(jev 전달)'과 파일 개수·형식만 들어간다.
전송 직전에 check_prompts.check_text로 state 전체를 점검하고, 위반이 있으면 보내지 않는다(안전장치 7).

최종 등급은 decide()가 코드 규칙으로 확정한다(jev-router의 policy와 같은 방향: 불확실하면 낮추지 않음, 실패하면 기준값).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from check_prompts import check_text, severity_text  # noqa: E402
from common import load_env  # noqa: E402

TIERS = ["fast", "balanced", "strong"]
DEFAULT_BASE_URL = "https://api.typesafe.ai"
SYSTEM_ONE_PATH = "/v1/systemone"
DEFAULT_MODEL = "jev-latest"

SEVERITY_LEVELS = [
    "0 없음: 판단이 필요 없는 결정적 스크립트 작업이다.",
    "1 낮음: 이름 패턴 같은 단순 판단이고, 틀려도 뒤의 사람 승인 단계에서 쉽게 바로잡힌다.",
    "2 중간: 본문을 읽고 이해·분석해야 하며, 틀리면 산출물 품질이 떨어지지만 검증 단계에서 걸러진다.",
    "3 높음: 법적 판단, 원문 인용의 정확성, 기존 지침 변경처럼 틀리면 이후 결과 전체나 법률 산출물에 직접 영향을 준다.",
]
TIER_CRITERIA = {
    "fast": {"what": "빠른 소형 모델(Haiku). 단순·기계적 판단.",
             "signals": ["파일 이름 패턴 분류", "정해진 스크립트 실행과 결과 보고"],
             "not_for": "본문 이해, 법률 문언 인용, 여러 자료 종합."},
    "balanced": {"what": "중형 모델(Sonnet). 범위가 분명한 일상적 분석.",
                 "signals": ["본문 앞부분을 읽고 문서 종류·장르 판단", "문체·전개 분석"],
                 "not_for": "법률 인용의 정확성이 결과를 좌우하는 작업, 지침 변경 판단."},
    "strong": {"what": "가장 강한 모델(Opus). 어렵거나 틀리면 영향이 큰 작업.",
               "signals": ["계약 조항·소송서면 원문 인용과 위치 기록", "여러 카드 종합과 패턴 판단", "기존 스킬 지침 변경 제안"],
               "not_for": "단순 반복 작업."},
}


def build_request(row: dict, recs: list[dict]) -> dict:
    """jev에 보낼 요청. 문서 내용·파일명은 넣지 않는다."""
    state = {
        "pipeline": "법무 자료와 웹소설 자료를 분류하고 학습 카드·학습노트·스킬 반영 제안서를 만드는 단계형 작업. 단계마다 사람 승인에서 멈춘다.",
        "stage": {"task": row["단계 작업"], "description": row.get("작업 설명(jev 전달)", "")},
        "inputs": {
            "file_count": len(recs),
            "corpus": sorted({"법무" if r["corpus"] == "legal" else "웹소설" for r in recs}),
            "file_types": dict(Counter(r["ext"] for r in recs)),
        },
    }
    questions = {
        "severity": {"type": "score", "criteria": SEVERITY_LEVELS,
                     "instructions": "`stage`의 작업을 틀렸을 때의 영향과 필요한 판단 수준을 기준으로, 이 작업의 경중은 어느 정도인가?"},
        "tier": {"type": "choice", "criteria": TIER_CRITERIA,
                 "instructions": "`stage`의 작업을 정확하게 끝낼 수 있는 가장 저렴한 모델 등급은 무엇인가?"},
    }
    return {"state": state, "model": DEFAULT_MODEL, "questions": questions}


def _strings(obj) -> list[str]:
    """state 안의 모든 키·값 문자열(점검용). JSON 따옴표 때문에 T3가 오탐하지 않도록 풀어서 본다."""
    if isinstance(obj, dict):
        return [x for k, v in obj.items() for x in [str(k), *_strings(v)]]
    if isinstance(obj, list):
        return [x for v in obj for x in _strings(v)]
    return [str(obj)]


def api_key() -> str | None:
    env = load_env()
    return (env.get("JEV_API_KEY") or env.get("TYPESAFE_API_KEY")
            or os.environ.get("JEV_API_KEY") or os.environ.get("TYPESAFE_API_KEY"))


def ask_jev(request: dict, cfg: dict, timeout: float = 15.0) -> tuple[dict | None, str]:
    """(응답 JSON 또는 None, 상태 설명). 실패해도 예외를 내지 않는다(기준값으로 대체)."""
    violations = check_text("\n".join(_strings(request["state"])), cfg,
                            allowed_vocab=severity_text() + request["state"]["pipeline"])
    if violations:
        return None, f"전송 안 함: state 점검 위반 {violations}"
    key = api_key()
    if not key:
        return None, "JEV_API_KEY 없음"
    base = (os.environ.get("TYPESAFE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    req = urllib.request.Request(
        base + SYSTEM_ONE_PATH, data=json.dumps(request, ensure_ascii=False).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8")), "jev 응답 받음"
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:200]
        return None, f"jev HTTP {e.code}: {body}"
    except Exception as e:  # 네트워크 차단·시간 초과 등
        return None, f"jev 연결 실패: {type(e).__name__}: {e}"


def rank(t: str) -> int:
    return TIERS.index(t)


def decide(row: dict, response: dict | None, min_conf: float) -> dict:
    """jev 답을 규칙으로 확정한다. 순수 함수(테스트 대상)."""
    base = row["배정 등급"]
    if base == "none":
        return {"tier": "none", "reasons": ["모델 미사용 단계(jev 호출 안 함)"], "jev": None}
    reasons = []
    answers = (response or {}).get("answers", {})
    tier_ans, sev_ans = answers.get("tier"), answers.get("severity")
    jev = None
    if not tier_ans or tier_ans.get("choice") not in TIERS:
        tier = base
        reasons.append(f"jev 판단 없음 → 경중표 기준값 {base}")
    else:
        jev = {"tier": tier_ans["choice"], "confidence": tier_ans.get("confidence"),
               "probabilities": tier_ans.get("probabilities"),
               "severity": sev_ans.get("score") if sev_ans else None,
               "severity_confidence": sev_ans.get("confidence") if sev_ans else None}
        tier = jev["tier"]
        reasons.append(f"jev 판단 {tier} (신뢰도 {jev['confidence']})")
        conf = jev["confidence"] if isinstance(jev["confidence"], (int, float)) else 0.0
        if conf < min_conf and rank(tier) < rank(base):
            tier = base
            reasons.append(f"신뢰도 {conf:.2f} < {min_conf} → 경중표 {base}보다 낮추지 않음")
        if isinstance(jev["severity"], (int, float)):
            implied = ["fast", "fast", "balanced", "strong"][max(0, min(3, round(jev["severity"])))]
            if rank(implied) > rank(tier):
                reasons.append(f"jev 경중 점수 {jev['severity']:.2f}가 {implied}에 해당 → 높은 쪽 {implied}")
                tier = implied
    if row.get("strong 고정") == "예" and tier != "strong":
        reasons.append("strong 고정 단계 → strong")
        tier = "strong"
    return {"tier": tier, "reasons": reasons, "jev": jev}
