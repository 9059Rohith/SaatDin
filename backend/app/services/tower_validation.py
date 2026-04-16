from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping, Optional

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


def _distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dx = (lon2 - lon1) * 111_000 * 0.9
    dy = (lat2 - lat1) * 111_000
    return (dx * dx + dy * dy) ** 0.5


def _iter_cells(tower_metadata: Mapping[str, Any]) -> Iterable[Dict[str, Any]]:
    serving = tower_metadata.get("servingCell")
    if isinstance(serving, Mapping):
        yield dict(serving)
    neighbors = tower_metadata.get("neighborCells")
    if isinstance(neighbors, list):
        max_neighbors = max(0, int(settings.tower_signal_max_neighbors))
        for neighbor in neighbors[:max_neighbors]:
            if isinstance(neighbor, Mapping):
                yield dict(neighbor)


def validate_tower_metadata_for_zone(
    *,
    tower_metadata: Optional[Mapping[str, Any]],
    claimed_zone_pincode: str,
    zone_lat: float,
    zone_lon: float,
    captured_at: Optional[datetime],
    received_at: Optional[datetime],
    now_utc: Optional[datetime] = None,
) -> Dict[str, Any]:
    now = now_utc or datetime.now(timezone.utc)
    if not settings.tower_validation_enabled:
        return {
            "status": "disabled",
            "confidence": 0.5,
            "reason": "tower_validation_disabled",
            "signal_present": False,
            "signal_age_minutes": None,
        }

    if not tower_metadata:
        return {
            "status": "missing",
            "confidence": 0.5,
            "reason": "tower_metadata_missing",
            "signal_present": False,
            "signal_age_minutes": None,
        }

    signal_at = captured_at or received_at
    signal_age_minutes: Optional[float] = None
    if signal_at is not None:
        signal_age_minutes = max(0.0, (now - signal_at).total_seconds() / 60.0)
        if signal_age_minutes > float(settings.tower_signal_freshness_minutes):
            return {
                "status": "stale",
                "confidence": 0.5,
                "reason": "tower_signal_stale",
                "signal_present": True,
                "signal_age_minutes": round(signal_age_minutes, 3),
            }

    candidates: list[tuple[float, float, float]] = []
    for cell in _iter_cells(tower_metadata):
        lat = cell.get("approxLatitude")
        lon = cell.get("approxLongitude")
        if lat is None or lon is None:
            continue
        lat_value = _coerce_float(lat, 999.0)
        lon_value = _coerce_float(lon, 999.0)
        if not (-90.0 <= lat_value <= 90.0 and -180.0 <= lon_value <= 180.0):
            continue
        signal_dbm = _coerce_float(cell.get("signalDbm"), -120.0)
        candidates.append((lat_value, lon_value, signal_dbm))

    if candidates:
        # Higher dBm (closer to zero) indicates stronger serving signal.
        best_lat, best_lon, _ = max(candidates, key=lambda item: item[2])
        distance = _distance_meters(best_lat, best_lon, zone_lat, zone_lon)
        match_km = max(0.1, float(settings.tower_validation_distance_match_km))
        mismatch_km = max(match_km + 0.1, float(settings.tower_validation_distance_mismatch_km))
        distance_km = distance / 1000.0
        if distance_km <= match_km:
            confidence = 0.9
            status = "match"
            reason = "tower_distance_match"
        elif distance_km >= mismatch_km:
            confidence = 0.1
            status = "mismatch"
            reason = "tower_distance_mismatch"
        else:
            span = mismatch_km - match_km
            ratio = (distance_km - match_km) / span
            confidence = _clamp(0.9 - (0.8 * ratio), 0.1, 0.9)
            status = "match" if confidence >= 0.5 else "mismatch"
            reason = "tower_distance_partial"
        return {
            "status": status,
            "confidence": round(confidence, 3),
            "reason": reason,
            "signal_present": True,
            "signal_age_minutes": round(signal_age_minutes, 3) if signal_age_minutes is not None else None,
            "distance_km": round(distance_km, 3),
        }

    network_hint = tower_metadata.get("networkZoneHintPincode")
    if isinstance(network_hint, str) and network_hint.strip():
        normalized_hint = network_hint.strip()
        normalized_zone = claimed_zone_pincode.strip()
        if normalized_hint == normalized_zone:
            return {
                "status": "match_hint",
                "confidence": 0.72,
                "reason": "tower_zone_hint_match",
                "signal_present": True,
                "signal_age_minutes": round(signal_age_minutes, 3) if signal_age_minutes is not None else None,
            }
        return {
            "status": "mismatch_hint",
            "confidence": 0.2,
            "reason": "tower_zone_hint_mismatch",
            "signal_present": True,
            "signal_age_minutes": round(signal_age_minutes, 3) if signal_age_minutes is not None else None,
        }

    return {
        "status": "insufficient",
        "confidence": 0.5,
        "reason": "tower_metadata_insufficient",
        "signal_present": True,
        "signal_age_minutes": round(signal_age_minutes, 3) if signal_age_minutes is not None else None,
    }


async def evaluate_worker_tower_signal(
    *,
    phone: str,
    claimed_zone_pincode: str,
    zone_lat: float,
    zone_lon: float,
) -> Dict[str, Any]:
    signal = await get_worker_location_signal(phone)
    if signal is None:
        result = {
            "status": "missing",
            "confidence": 0.5,
            "reason": "tower_signal_not_found",
            "signal_present": False,
            "signal_received_at": None,
            "signal_age_minutes": None,
        }
        logger.info(
            "tower_validation_evaluated phone=%s status=%s confidence=%.3f reason=%s",
            phone,
            result["status"],
            result["confidence"],
            result["reason"],
        )
        return result

    tower_metadata = signal.get("tower_metadata_json")
    if isinstance(tower_metadata, str):
        try:
            parsed = json.loads(tower_metadata)
        except json.JSONDecodeError:
            parsed = None
        tower_metadata = parsed

    received_at = _parse_iso_datetime(signal.get("received_at"))
    captured_at = _parse_iso_datetime(signal.get("captured_at"))
    result = validate_tower_metadata_for_zone(
        tower_metadata=tower_metadata if isinstance(tower_metadata, Mapping) else None,
        claimed_zone_pincode=claimed_zone_pincode,
        zone_lat=zone_lat,
        zone_lon=zone_lon,
        captured_at=captured_at,
        received_at=received_at,
    )
    result["signal_received_at"] = received_at.isoformat() if received_at is not None else None
    logger.info(
        "tower_validation_evaluated phone=%s status=%s confidence=%.3f reason=%s zone=%s",
        phone,
        result["status"],
        float(result["confidence"]),
        result["reason"],
        claimed_zone_pincode,
    )
    return result


def tower_features_from_validation(validation: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "tower_zone_confidence": _clamp(_coerce_float(validation.get("confidence"), 0.5), 0.0, 1.0),
        "tower_validation_status": str(validation.get("status", "missing")),
        "tower_validation_reason": str(validation.get("reason", "tower_signal_not_found")),
        "tower_signal_present": 1.0 if bool(validation.get("signal_present")) else 0.0,
        "tower_signal_age_minutes": _coerce_float(validation.get("signal_age_minutes"), 0.0),
        "tower_signal_received_at": validation.get("signal_received_at"),
    }
