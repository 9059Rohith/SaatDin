from __future__ import annotations

import json
import logging
import math
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from ..core.config import settings
from .fraud_llm_graph import run_fraud_llm_fallback

try:
    from joblib import load
except ImportError:
    load = None  # type: ignore

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore

logger = logging.getLogger(__name__)

FEATURE_NAMES: tuple[str, ...] = (
    "zone_affinity_score",
    "fraud_ring_size",
    "recent_claims_24h",
    "claim_amount",
    "trigger_confidence",
    "is_manual_source",
    "is_auto_source",
    "flood_risk_score",
    "aqi_risk_score",
    "traffic_congestion_score",
)

DEFAULT_FEATURES: Dict[str, float] = {
    "zone_affinity_score": 0.5,
    "fraud_ring_size": 0.0,
    "recent_claims_24h": 0.0,
    "claim_amount": 250.0,
    "trigger_confidence": 0.55,
    "is_manual_source": 0.0,
    "is_auto_source": 1.0,
    "flood_risk_score": 0.5,
    "aqi_risk_score": 0.5,
    "traffic_congestion_score": 0.5,
}

_model: Any = None
_model_version = "uninitialized"
_metrics_total = 0
_metrics_flagged = 0
_metrics_errors = 0
_metrics_scores: deque[float] = deque(maxlen=512)


def _metadata_path(model_path: Path) -> Path:
    return model_path.with_suffix(".json")


def _load_metadata(model_path: Path) -> Dict[str, Any]:
    metadata_path = _metadata_path(model_path)
    if not metadata_path.exists():
        return {}
    try:
        return json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("fraud_model_metadata_read_failed path=%s error=%s", metadata_path, exc)
        return {}


def _coerce_feature_value(value: Any, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(parsed) or math.isinf(parsed):
        return default
    return parsed


def normalize_features(features: Mapping[str, Any]) -> Dict[str, float]:
    normalized: Dict[str, float] = {}
    for name in FEATURE_NAMES:
        normalized[name] = _coerce_feature_value(features.get(name), DEFAULT_FEATURES[name])
    return normalized


def initialize_fraud_model() -> None:
    global _model
    global _model_version

    if not settings.fraud_scoring_enabled:
        _model = None
        _model_version = "disabled"
        logger.info("fraud_scoring_disabled")
        return

    if load is None:
        _model = None
        _model_version = "missing-joblib"
        logger.warning("fraud_model_unavailable reason=joblib_not_installed")
        return

    model_path = settings.fraud_model_file_path
    if not model_path.exists():
        _model = None
        _model_version = "missing-artifact"
        logger.warning("fraud_model_unavailable reason=artifact_missing path=%s", model_path)
        return

    try:
        loaded_model = load(model_path)
        if not hasattr(loaded_model, "decision_function"):
            raise TypeError("Loaded artifact does not expose decision_function")
        _model = loaded_model
        metadata = _load_metadata(model_path)
        _model_version = str(metadata.get("version") or model_path.stem)
        logger.info(
            "fraud_model_loaded path=%s version=%s feature_count=%s",
            model_path,
            _model_version,
            len(FEATURE_NAMES),
        )
    except Exception as exc:
        _model = None
        _model_version = "load-failed"
        logger.exception("fraud_model_load_failed path=%s error=%s", model_path, exc)


def _record_metrics(score: float, flagged: bool, errored: bool) -> None:
    global _metrics_total
    global _metrics_flagged
    global _metrics_errors

    _metrics_total += 1
    if flagged:
        _metrics_flagged += 1
    if errored:
        _metrics_errors += 1
    _metrics_scores.append(score)

    if _metrics_total <= 0:
        return

    log_every = max(1, int(settings.fraud_metrics_log_every_n))
    if _metrics_total % log_every != 0:
        return

    sorted_scores = sorted(_metrics_scores)
    p95_index = int((len(sorted_scores) - 1) * 0.95) if sorted_scores else 0
    p95_score = sorted_scores[p95_index] if sorted_scores else 0.0
    flagged_rate = _metrics_flagged / _metrics_total
    logger.info(
        "fraud_metrics window=%s total=%s flagged=%s flagged_rate=%.4f p95_score=%.6f errors=%s model_version=%s",
        len(_metrics_scores),
        _metrics_total,
        _metrics_flagged,
        flagged_rate,
        p95_score,
        _metrics_errors,
        _model_version,
    )


def _log_score_event(result: Dict[str, Any], context: Mapping[str, Any], mode: str) -> None:
    logger.info(
        "fraud_score_evaluated mode=%s model_version=%s score=%.6f threshold=%.6f flagged=%s claim_type=%s source=%s phone=%s",
        mode,
        result["anomaly_model_version"],
        float(result["anomaly_score"]),
        float(result["anomaly_threshold"]),
        bool(result["anomaly_flagged"]),
        str(context.get("claim_type", "unknown")),
        str(context.get("source", "unknown")),
        str(context.get("phone", "unknown")),
    )


def _default_llm_metadata(*, scored_at: str) -> Dict[str, Any]:
    return {
        "llm_review_used": False,
        "llm_review_status": None,
        "llm_provider": None,
        "llm_model": None,
        "llm_fallback_used": False,
        "llm_decision_confidence": None,
        "llm_decision_json": None,
        "llm_attempts": None,
        "llm_validation_error": None,
        "llm_scored_at": scored_at,
    }


def _should_use_llm_fallback(*, score: float, threshold: float, features: Mapping[str, float]) -> bool:
    if not settings.fraud_llm_fallback_enabled:
        return False

    margin = max(0.0, float(settings.fraud_llm_ambiguity_margin))
    score_gap = abs(score - threshold)
    if score_gap > margin:
        return False

    trigger_confidence = float(features.get("trigger_confidence", DEFAULT_FEATURES["trigger_confidence"]))
    min_conf = min(
        float(settings.fraud_llm_trigger_confidence_min),
        float(settings.fraud_llm_trigger_confidence_max),
    )
    max_conf = max(
        float(settings.fraud_llm_trigger_confidence_min),
        float(settings.fraud_llm_trigger_confidence_max),
    )
    return min_conf <= trigger_confidence <= max_conf


def _tower_adjustment_from_features(features: Mapping[str, Any]) -> Dict[str, Any]:
    if not settings.tower_validation_enabled:
        return {
            "applied": False,
            "adjustment": 0.0,
            "status": "disabled",
            "confidence": 0.5,
            "reason": "tower_validation_disabled",
            "present": False,
        }

    status = str(features.get("tower_validation_status", "missing")).strip().lower()
    confidence = max(0.0, min(1.0, _coerce_feature_value(features.get("tower_zone_confidence"), 0.5)))
    present = _coerce_feature_value(features.get("tower_signal_present"), 0.0) >= 0.5
    reason = str(features.get("tower_validation_reason", "tower_signal_not_found"))
    if not present or status in {"missing", "stale", "insufficient", "invalid"}:
        return {
            "applied": False,
            "adjustment": 0.0,
            "status": status or "missing",
            "confidence": confidence,
            "reason": reason,
            "present": present,
        }

    raw_adjustment = (confidence - 0.5) * 2.0 * float(settings.tower_validation_score_weight)
    cap = abs(float(settings.tower_validation_adjustment_cap))
    adjustment = max(-cap, min(cap, raw_adjustment))
    return {
        "applied": abs(adjustment) > 0.0,
        "adjustment": adjustment,
        "status": status or "insufficient",
        "confidence": confidence,
        "reason": reason,
        "present": present,
    }


def _motion_adjustment_from_features(features: Mapping[str, Any]) -> Dict[str, Any]:
    if not settings.motion_validation_enabled:
        return {
            "applied": False,
            "adjustment": 0.0,
            "status": "disabled",
            "confidence": 0.5,
            "reason": "motion_validation_disabled",
            "present": False,
            "eligible": False,
        }

    status = str(features.get("motion_validation_status", "missing")).strip().lower()
    confidence = max(0.0, min(1.0, _coerce_feature_value(features.get("motion_confidence"), 0.5)))
    present = _coerce_feature_value(features.get("motion_signal_present"), 0.0) >= 0.5
    eligible = _coerce_feature_value(features.get("motion_signal_eligible"), 0.0) >= 0.5
    reason = str(features.get("motion_validation_reason", "motion_signal_not_found"))
    if not present or not eligible or status in {"missing", "stale", "insufficient", "invalid"}:
        return {
            "applied": False,
            "adjustment": 0.0,
            "status": status or "missing",
            "confidence": confidence,
            "reason": reason,
            "present": present,
            "eligible": eligible,
        }

    raw_adjustment = (confidence - 0.5) * 2.0 * float(settings.motion_validation_score_weight)
    cap = abs(float(settings.motion_validation_adjustment_cap))

    # False-positive guardrail: apply full negative adjustment only when corroborating risk exists.
    corroborating_risk = (
        _coerce_feature_value(features.get("zone_affinity_score"), 0.5) < 0.35
        or str(features.get("tower_validation_status", "")).strip().lower() in {"mismatch", "mismatch_hint"}
    )
    if raw_adjustment < 0 and not corroborating_risk:
        raw_adjustment *= 0.5

    adjustment = max(-cap, min(cap, raw_adjustment))
    return {
        "applied": abs(adjustment) > 0.0,
        "adjustment": adjustment,
        "status": status or "insufficient",
        "confidence": confidence,
        "reason": reason,
        "present": present,
        "eligible": eligible,
    }


def score_claim(
    features: Mapping[str, Any],
    *,
    context: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    threshold = float(settings.fraud_anomaly_threshold)
    normalized = normalize_features(features)
    scored_at = datetime.now(timezone.utc).isoformat()
    event_context = context or {}

    if not settings.fraud_scoring_enabled:
        result = {
            "anomaly_score": 0.0,
            "anomaly_threshold": threshold,
            "anomaly_flagged": False,
            "anomaly_model_version": "disabled",
            "anomaly_features": normalized,
            "anomaly_scored_at": scored_at,
        }
        result.update(_default_llm_metadata(scored_at=scored_at))
        _record_metrics(0.0, False, False)
        _log_score_event(result, event_context, mode="disabled")
        return result

    if _model is None:
        initialize_fraud_model()

    if _model is None:
        if settings.fraud_fail_open:
            result = {
                "anomaly_score": 0.0,
                "anomaly_threshold": threshold,
                "anomaly_flagged": False,
                "anomaly_model_version": f"{_model_version}:fail-open",
                "anomaly_features": normalized,
                "anomaly_scored_at": scored_at,
            }
            result.update(_default_llm_metadata(scored_at=scored_at))
            _record_metrics(0.0, False, True)
            _log_score_event(result, event_context, mode="fail-open")
            return result
        raise RuntimeError("Fraud model unavailable and FRAUD_FAIL_OPEN is false")

    if np is None:
        if settings.fraud_fail_open:
            result = {
                "anomaly_score": 0.0,
                "anomaly_threshold": threshold,
                "anomaly_flagged": False,
                "anomaly_model_version": f"{_model_version}:missing-numpy",
                "anomaly_features": normalized,
                "anomaly_scored_at": scored_at,
            }
            result.update(_default_llm_metadata(scored_at=scored_at))
            _record_metrics(0.0, False, True)
            _log_score_event(result, event_context, mode="fail-open")
            return result
        raise RuntimeError("NumPy unavailable and FRAUD_FAIL_OPEN is false")

    try:
        feature_vector = np.array([[normalized[name] for name in FEATURE_NAMES]], dtype=float)
        raw_score = float(_model.decision_function(feature_vector)[0])
        tower_adjustment = _tower_adjustment_from_features(features)
        motion_adjustment = _motion_adjustment_from_features(features)
        adjusted_score = raw_score + float(tower_adjustment["adjustment"]) + float(motion_adjustment["adjustment"])
        flagged = adjusted_score < threshold
        scoring_features: Dict[str, Any] = dict(normalized)
        scoring_features.update(
            {
                "tower_zone_confidence": round(float(tower_adjustment["confidence"]), 3),
                "tower_validation_status": str(tower_adjustment["status"]),
                "tower_validation_reason": str(tower_adjustment["reason"]),
                "tower_signal_present": 1.0 if bool(tower_adjustment["present"]) else 0.0,
                "tower_signal_age_minutes": _coerce_feature_value(features.get("tower_signal_age_minutes"), 0.0),
                "tower_signal_received_at": features.get("tower_signal_received_at"),
                "tower_score_adjustment": round(float(tower_adjustment["adjustment"]), 6),
                "motion_confidence": round(float(motion_adjustment["confidence"]), 3),
                "motion_validation_status": str(motion_adjustment["status"]),
                "motion_validation_reason": str(motion_adjustment["reason"]),
                "motion_signal_present": 1.0 if bool(motion_adjustment["present"]) else 0.0,
                "motion_signal_eligible": 1.0 if bool(motion_adjustment["eligible"]) else 0.0,
                "motion_signal_age_minutes": _coerce_feature_value(features.get("motion_signal_age_minutes"), 0.0),
                "motion_signal_received_at": features.get("motion_signal_received_at"),
                "motion_score_adjustment": round(float(motion_adjustment["adjustment"]), 6),
                "model_raw_score": round(raw_score, 6),
            }
        )
        llm_features: Dict[str, float] = dict(normalized)
        llm_features.update(
            {
                "tower_zone_confidence": float(scoring_features["tower_zone_confidence"]),
                "tower_signal_present": float(scoring_features["tower_signal_present"]),
                "tower_signal_age_minutes": float(scoring_features["tower_signal_age_minutes"]),
                "tower_score_adjustment": float(scoring_features["tower_score_adjustment"]),
                "motion_confidence": float(scoring_features["motion_confidence"]),
                "motion_signal_present": float(scoring_features["motion_signal_present"]),
                "motion_signal_eligible": float(scoring_features["motion_signal_eligible"]),
                "motion_signal_age_minutes": float(scoring_features["motion_signal_age_minutes"]),
                "motion_score_adjustment": float(scoring_features["motion_score_adjustment"]),
                "model_raw_score": float(scoring_features["model_raw_score"]),
            }
        )
        result = {
            "anomaly_score": round(adjusted_score, 6),
            "anomaly_threshold": threshold,
            "anomaly_flagged": flagged,
            "anomaly_model_version": _model_version,
            "anomaly_features": scoring_features,
            "anomaly_scored_at": scored_at,
        }
        result.update(_default_llm_metadata(scored_at=scored_at))

        if _should_use_llm_fallback(score=adjusted_score, threshold=threshold, features=normalized):
            llm_result = run_fraud_llm_fallback(
                features=llm_features,
                context=dict(event_context),
                model_score=adjusted_score,
                threshold=threshold,
            )
            llm_status = str(llm_result.get("status", "provider_failed"))
            llm_decision = llm_result.get("decision")
            llm_confidence = None
            if isinstance(llm_decision, dict):
                decision_conf = llm_decision.get("confidence")
                if isinstance(decision_conf, (float, int)):
                    llm_confidence = float(decision_conf)

            result.update(
                {
                    "llm_review_used": True,
                    "llm_review_status": llm_status,
                    "llm_provider": llm_result.get("provider"),
                    "llm_model": llm_result.get("model"),
                    "llm_fallback_used": bool(llm_result.get("fallback_used", False)),
                    "llm_decision_confidence": llm_confidence,
                    "llm_decision_json": llm_decision if isinstance(llm_decision, dict) else None,
                    "llm_attempts": llm_result.get("attempts"),
                    "llm_validation_error": llm_result.get("validation_error"),
                    "llm_scored_at": str(llm_result.get("scored_at", scored_at)),
                }
            )

            if llm_status == "accepted" and isinstance(llm_decision, dict):
                result["anomaly_flagged"] = bool(llm_decision.get("anomaly_flagged", flagged))
                llm_provider = str(llm_result.get("provider") or "unknown")
                result["anomaly_model_version"] = f"{_model_version}:llm-{llm_provider}"
            elif llm_status == "invalid_output":
                # Reject malformed LLM output safely: keep claim in manual review.
                result["anomaly_flagged"] = True
                result["anomaly_model_version"] = f"{_model_version}:llm-invalid"

        _record_metrics(adjusted_score, bool(result["anomaly_flagged"]), False)
        _log_score_event(result, event_context, mode="model")
        return result
    except Exception as exc:
        if settings.fraud_fail_open:
            logger.exception("fraud_scoring_failed mode=fail-open error=%s", exc)
            result = {
                "anomaly_score": 0.0,
                "anomaly_threshold": threshold,
                "anomaly_flagged": False,
                "anomaly_model_version": f"{_model_version}:score-failed",
                "anomaly_features": normalized,
                "anomaly_scored_at": scored_at,
            }
            result.update(_default_llm_metadata(scored_at=scored_at))
            _record_metrics(0.0, False, True)
            _log_score_event(result, event_context, mode="fail-open")
            return result
        raise
