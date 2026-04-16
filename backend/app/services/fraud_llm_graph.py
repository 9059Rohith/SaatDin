from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, TypedDict
from urllib import error, request

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ..core.config import settings

try:
    from langgraph.graph import START, END, StateGraph
except ImportError:
    START = "START"  # type: ignore[assignment]
    END = "END"  # type: ignore[assignment]
    StateGraph = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)


class FraudLLMDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    anomaly_flagged: bool
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=10, max_length=1500)
    risk_signals: List[str] = Field(default_factory=list, max_length=10)
    recommended_status: Literal["settled", "in_review"]

    @model_validator(mode="after")
    def _validate_consistency(self) -> "FraudLLMDecision":
        if self.anomaly_flagged and self.recommended_status != "in_review":
            raise ValueError("recommended_status must be in_review when anomaly_flagged is true")
        if not self.anomaly_flagged and self.recommended_status != "settled":
            raise ValueError("recommended_status must be settled when anomaly_flagged is false")
        return self


class _FraudLLMState(TypedDict, total=False):
    prompt: str
    providers: List[str]
    attempts: List[Dict[str, Any]]
    raw_payload: Dict[str, Any] | None
    provider: str | None
    model: str | None
    fallback_used: bool
    status: str
    validation_error: str | None
    decision: Dict[str, Any] | None
    scored_at: str


def _build_prompt(features: Dict[str, float], context: Dict[str, Any], model_score: float, threshold: float) -> str:
    guidance = {
        "task": "Assess whether this claim should be treated as anomaly-flagged for manual review.",
        "output_rules": [
            "Return strict JSON only with keys: anomaly_flagged, confidence, rationale, risk_signals, recommended_status.",
            "Do not include markdown, prose outside JSON, or extra keys.",
            "recommended_status must be 'in_review' when anomaly_flagged is true; otherwise 'settled'.",
        ],
        "base_model": {
            "anomaly_score": round(model_score, 6),
            "anomaly_threshold": round(threshold, 6),
        },
        "claim_context": {
            "phone": str(context.get("phone", "unknown")),
            "claim_type": str(context.get("claim_type", "unknown")),
            "source": str(context.get("source", "unknown")),
        },
        "features": features,
    }
    return json.dumps(guidance, ensure_ascii=True)


def _provider_model(provider: str) -> str:
    if provider == "groq":
        return settings.groq_model.strip() or "llama-3.3-70b-versatile"
    if provider == "gemini":
        return settings.gemini_model.strip() or "gemini-2.5-flash"
    return "unknown"


def _post_json(url: str, *, headers: Dict[str, str], payload: Dict[str, Any], timeout_seconds: int) -> Dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    req = request.Request(url=url, data=body, headers=headers, method="POST")
    with request.urlopen(req, timeout=timeout_seconds) as resp:  # nosec B310
        raw = resp.read().decode("utf-8")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise RuntimeError("Provider returned non-object JSON")
    return parsed


def _parse_json_text_payload(raw_text: str) -> Dict[str, Any]:
    parsed = json.loads(raw_text.strip())
    if not isinstance(parsed, dict):
        raise ValueError("Model output must be a JSON object")
    return parsed


def _invoke_groq(prompt: str) -> Dict[str, Any]:
    if not settings.groq_api_key.strip():
        raise RuntimeError("GROQ_API_KEY is not configured")
    model_name = _provider_model("groq")
    payload = {
        "model": model_name,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a fraud adjudication engine. Return strict JSON only "
                    "with no additional text."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
        "max_tokens": int(settings.fraud_llm_max_output_tokens),
        "response_format": {"type": "json_object"},
    }
    response = _post_json(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {settings.groq_api_key.strip()}",
            "Content-Type": "application/json",
        },
        payload=payload,
        timeout_seconds=max(1, int(settings.fraud_llm_request_timeout_seconds)),
    )
    content = (
        response.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Groq returned empty content")
    parsed = _parse_json_text_payload(content)
    return {"provider": "groq", "model": model_name, "payload": parsed}


def _invoke_gemini(prompt: str) -> Dict[str, Any]:
    if not settings.gemini_api_key.strip():
        raise RuntimeError("GEMINI_API_KEY is not configured")
    model_name = _provider_model("gemini")
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": (
                            "You are a fraud adjudication engine. Return strict JSON only "
                            "with no additional text.\n\n"
                            f"{prompt}"
                        )
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": int(settings.fraud_llm_max_output_tokens),
            "responseMimeType": "application/json",
        },
    }
    response = _post_json(
        (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model_name}:generateContent?key={settings.gemini_api_key.strip()}"
        ),
        headers={"Content-Type": "application/json"},
        payload=payload,
        timeout_seconds=max(1, int(settings.fraud_llm_request_timeout_seconds)),
    )
    candidates = response.get("candidates", [])
    if not isinstance(candidates, list) or not candidates:
        raise RuntimeError("Gemini returned no candidates")
    parts = candidates[0].get("content", {}).get("parts", [])
    if not isinstance(parts, list) or not parts:
        raise RuntimeError("Gemini returned no content parts")
    text = parts[0].get("text", "")
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("Gemini returned empty text")
    parsed = _parse_json_text_payload(text)
    return {"provider": "gemini", "model": model_name, "payload": parsed}


def _invoke_provider(provider: str, prompt: str) -> Dict[str, Any]:
    started = time.perf_counter()
    try:
        if provider == "groq":
            response = _invoke_groq(prompt)
        elif provider == "gemini":
            response = _invoke_gemini(prompt)
        else:
            raise RuntimeError(f"Unsupported provider: {provider}")
        latency_ms = int((time.perf_counter() - started) * 1000)
        return {
            "provider": provider,
            "model": str(response.get("model", _provider_model(provider))),
            "success": True,
            "latency_ms": latency_ms,
            "payload": response.get("payload"),
            "error": None,
        }
    except (ValidationError, json.JSONDecodeError) as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return {
            "provider": provider,
            "model": _provider_model(provider),
            "success": False,
            "latency_ms": latency_ms,
            "payload": None,
            "error": f"invalid_output:{exc}",
        }
    except error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")
        except Exception:
            detail = ""
        latency_ms = int((time.perf_counter() - started) * 1000)
        return {
            "provider": provider,
            "model": _provider_model(provider),
            "success": False,
            "latency_ms": latency_ms,
            "payload": None,
            "error": f"http_error:{exc.code}:{detail[:300]}",
        }
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return {
            "provider": provider,
            "model": _provider_model(provider),
            "success": False,
            "latency_ms": latency_ms,
            "payload": None,
            "error": str(exc),
        }


def _invoke_providers_node(state: _FraudLLMState) -> _FraudLLMState:
    providers = list(state.get("providers") or [])
    attempts: List[Dict[str, Any]] = list(state.get("attempts") or [])
    prompt = str(state.get("prompt", ""))
    max_retries = max(1, int(settings.fraud_llm_max_retries_per_provider))

    for index, provider in enumerate(providers):
        for _ in range(max_retries):
            attempt = _invoke_provider(provider, prompt)
            attempts.append(
                {
                    "provider": attempt.get("provider"),
                    "model": attempt.get("model"),
                    "success": bool(attempt.get("success")),
                    "error": attempt.get("error"),
                    "latency_ms": int(attempt.get("latency_ms", 0)),
                }
            )
            if bool(attempt.get("success")) and isinstance(attempt.get("payload"), dict):
                return {
                    **state,
                    "attempts": attempts,
                    "raw_payload": attempt["payload"],
                    "provider": str(attempt.get("provider")),
                    "model": str(attempt.get("model")),
                    "fallback_used": index > 0,
                    "status": "raw_received",
                }

    return {
        **state,
        "attempts": attempts,
        "raw_payload": None,
        "provider": None,
        "model": None,
        "fallback_used": False,
        "status": "provider_failed",
    }


def _validate_output_node(state: _FraudLLMState) -> _FraudLLMState:
    if state.get("status") != "raw_received":
        return state

    payload = state.get("raw_payload")
    if not isinstance(payload, dict):
        return {**state, "status": "invalid_output", "validation_error": "Provider payload was not a JSON object"}

    try:
        decision = FraudLLMDecision.model_validate(payload)
        return {
            **state,
            "status": "accepted",
            "decision": decision.model_dump(),
            "validation_error": None,
        }
    except ValidationError as exc:
        return {
            **state,
            "status": "invalid_output",
            "decision": None,
            "validation_error": str(exc),
        }


def _compile_graph() -> Any:
    if StateGraph is None:
        logger.warning("fraud_llm_graph_unavailable reason=langgraph_not_installed")
        return None
    graph = StateGraph(_FraudLLMState)
    graph.add_node("invoke_providers", _invoke_providers_node)
    graph.add_node("validate_output", _validate_output_node)
    graph.add_edge(START, "invoke_providers")
    graph.add_edge("invoke_providers", "validate_output")
    graph.add_edge("validate_output", END)
    return graph.compile()


_graph = _compile_graph()


def run_fraud_llm_fallback(
    *,
    features: Dict[str, float],
    context: Dict[str, Any],
    model_score: float,
    threshold: float,
) -> Dict[str, Any]:
    scored_at = datetime.now(timezone.utc).isoformat()
    if not settings.fraud_llm_fallback_enabled:
        return {
            "status": "disabled",
            "decision": None,
            "provider": None,
            "model": None,
            "fallback_used": False,
            "attempts": [],
            "validation_error": None,
            "scored_at": scored_at,
        }
    if _graph is None:
        return {
            "status": "unavailable",
            "decision": None,
            "provider": None,
            "model": None,
            "fallback_used": False,
            "attempts": [],
            "validation_error": "LangGraph dependency unavailable",
            "scored_at": scored_at,
        }

    initial_state: _FraudLLMState = {
        "prompt": _build_prompt(features, context, model_score, threshold),
        "providers": list(settings.fraud_llm_provider_sequence),
        "attempts": [],
        "raw_payload": None,
        "provider": None,
        "model": None,
        "fallback_used": False,
        "status": "initialized",
        "validation_error": None,
        "decision": None,
        "scored_at": scored_at,
    }
    final_state = _graph.invoke(initial_state)
    if not isinstance(final_state, dict):
        logger.warning("fraud_llm_graph_invalid_state_type")
        return {
            "status": "provider_failed",
            "decision": None,
            "provider": None,
            "model": None,
            "fallback_used": False,
            "attempts": [],
            "validation_error": "Graph returned non-dict state",
            "scored_at": scored_at,
        }
    return {
        "status": str(final_state.get("status", "provider_failed")),
        "decision": final_state.get("decision"),
        "provider": final_state.get("provider"),
        "model": final_state.get("model"),
        "fallback_used": bool(final_state.get("fallback_used", False)),
        "attempts": final_state.get("attempts", []),
        "validation_error": final_state.get("validation_error"),
        "scored_at": str(final_state.get("scored_at", scored_at)),
    }
