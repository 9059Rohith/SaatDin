from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional

from ..core.config import settings
from ..core.db import get_worker_location_signal

logger = logging.getLogger(__name__)


def _coerce_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed != parsed:
        return default
    return parsed


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _parse_iso_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def validate_motion_metadata(
    *,
    motion_metadata: Optional[Mapping[str, Any]],
    captured_at: Optional[datetime],
    received_at: Optional[datetime],
    now_utc: Optional[datetime] = None,
) -> Dict[str, Any]:
    now = now_utc or datetime.now(timezone.utc)
    if not settings.motion_validation_enabled:
        return {
            "status": "disabled",
            "confidence": 0.5,
            "reason": "motion_validation_disabled",
            "eligible": False,
            "signal_present": False,
            "signal_age_minutes": None,
        }

    if not motion_metadata:
        return {
            "status": "missing",
            "confidence": 0.5,
            "reason": "motion_metadata_missing",
            "eligible": False,
            "signal_present": False,
            "signal_age_minutes": None,
        }

    signal_at = captured_at or received_at
    signal_age_minutes: Optional[float] = None
    if signal_at is not None:
        signal_age_minutes = max(0.0, (now - signal_at).total_seconds() / 60.0)
        if signal_age_minutes > float(settings.motion_signal_freshness_minutes):
            return {
                "status": "stale",
                "confidence": 0.5,
                "reason": "motion_signal_stale",
                "eligible": False,
                "signal_present": True,
                "signal_age_minutes": round(signal_age_minutes, 3),
            }

    window_seconds = max(0.0, _coerce_float(motion_metadata.get("windowSeconds"), 0.0))
    sample_count = int(max(0.0, _coerce_float(motion_metadata.get("sampleCount"), 0.0)))
    if window_seconds < float(settings.motion_min_window_seconds) or sample_count < int(settings.motion_min_sample_count):
        return {
            "status": "insufficient",
            "confidence": 0.5,
            "reason": "motion_window_or_samples_insufficient",
            "eligible": False,
            "signal_present": True,
            "signal_age_minutes": round(signal_age_minutes, 3) if signal_age_minutes is not None else None,
        }

    moving_seconds = _coerce_float(motion_metadata.get("movingSeconds"), 0.0)
    stationary_seconds = _coerce_float(motion_metadata.get("stationarySeconds"), 0.0)
    distance_meters = _coerce_float(motion_metadata.get("distanceMeters"), 0.0)
    avg_speed = _coerce_float(motion_metadata.get("avgSpeedMps"), 0.0)
    max_speed = _coerce_float(motion_metadata.get("maxSpeedMps"), avg_speed)

    moving_ratio = moving_seconds / max(1.0, moving_seconds + stationary_seconds, window_seconds)
    plausible_speed_limit = float(settings.motion_max_speed_mps)
    if max_speed > plausible_speed_limit:
        return {
            "status": "mismatch",
            "confidence": 0.18,
            "reason": "motion_speed_implausible",
            "eligible": True,
            "signal_present": True,
            "signal_age_minutes": round(signal_age_minutes, 3) if signal_age_minutes is not None else None,
            "moving_ratio": round(moving_ratio, 3),
            "distance_meters": round(distance_meters, 3),
        }

    min_distance = float(settings.motion_min_distance_meters)
    if distance_meters < min_distance and moving_ratio < 0.05:
        return {
            "status": "static",
            "confidence": 0.35,
            "reason": "motion_static_pattern",
            "eligible": True,
            "signal_present": True,
            "signal_age_minutes": round(signal_age_minutes, 3) if signal_age_minutes is not None else None,
            "moving_ratio": round(moving_ratio, 3),
            "distance_meters": round(distance_meters, 3),
        }

    ratio_score = _clamp((moving_ratio - 0.05) / 0.55, 0.0, 1.0)
    distance_score = _clamp((distance_meters - min_distance) / max(1.0, min_distance * 6.0), 0.0, 1.0)
    speed_score = _clamp(avg_speed / max(1.0, plausible_speed_limit / 2.5), 0.0, 1.0)
    confidence = 0.45 + (0.30 * ratio_score) + (0.15 * distance_score) + (0.10 * speed_score)
    confidence = _clamp(confidence, 0.0, 1.0)
    status = "match" if confidence >= 0.55 else "mismatch"
    reason = "motion_genuine_pattern" if status == "match" else "motion_low_quality_pattern"
    return {
        "status": status,
        "confidence": round(confidence, 3),
        "reason": reason,
        "eligible": True,
        "signal_present": True,
        "signal_age_minutes": round(signal_age_minutes, 3) if signal_age_minutes is not None else None,
        "moving_ratio": round(moving_ratio, 3),
        "distance_meters": round(distance_meters, 3),
        "avg_speed_mps": round(avg_speed, 3),
        "max_speed_mps": round(max_speed, 3),
    }


async def evaluate_worker_motion_signal(*, phone: str) -> Dict[str, Any]:
    signal = await get_worker_location_signal(phone)
    if signal is None:
        result = {
            "status": "missing",
            "confidence": 0.5,
            "reason": "motion_signal_not_found",
            "eligible": False,
            "signal_present": False,
            "signal_received_at": None,
            "signal_age_minutes": None,
        }
        logger.info(
            "motion_validation_evaluated phone=%s status=%s confidence=%.3f reason=%s",
            phone,
            result["status"],
            result["confidence"],
            result["reason"],
        )
        return result

    motion_metadata = signal.get("motion_metadata_json")
    if isinstance(motion_metadata, str):
        try:
            motion_metadata = json.loads(motion_metadata)
        except json.JSONDecodeError:
            motion_metadata = None

    result = validate_motion_metadata(
        motion_metadata=motion_metadata if isinstance(motion_metadata, Mapping) else None,
        captured_at=_parse_iso_datetime(signal.get("captured_at")),
        received_at=_parse_iso_datetime(signal.get("received_at")),
    )
    result["signal_received_at"] = signal.get("received_at")
    logger.info(
        "motion_validation_evaluated phone=%s status=%s confidence=%.3f reason=%s eligible=%s",
        phone,
        result["status"],
        float(result["confidence"]),
        result["reason"],
        bool(result.get("eligible")),
    )
    return result


def motion_features_from_validation(validation: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "motion_confidence": _clamp(_coerce_float(validation.get("confidence"), 0.5), 0.0, 1.0),
        "motion_validation_status": str(validation.get("status", "missing")),
        "motion_validation_reason": str(validation.get("reason", "motion_signal_not_found")),
        "motion_signal_present": 1.0 if bool(validation.get("signal_present")) else 0.0,
        "motion_signal_eligible": 1.0 if bool(validation.get("eligible")) else 0.0,
        "motion_signal_age_minutes": _coerce_float(validation.get("signal_age_minutes"), 0.0),
        "motion_signal_received_at": validation.get("signal_received_at"),
        "motion_moving_ratio": _coerce_float(validation.get("moving_ratio"), 0.0),
        "motion_distance_meters": _coerce_float(validation.get("distance_meters"), 0.0),
    }
