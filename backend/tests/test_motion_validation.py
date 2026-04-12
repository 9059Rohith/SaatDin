from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from backend.app.core.config import settings
from backend.app.services import fraud_isolation
from backend.app.services.motion_validation import validate_motion_metadata


class _StubIsolationModel:
    def __init__(self, score: float) -> None:
        self._score = score

    def decision_function(self, _feature_vector):
        return [self._score]


class MotionValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original = {
            "motion_validation_enabled": settings.motion_validation_enabled,
            "motion_signal_freshness_minutes": settings.motion_signal_freshness_minutes,
            "motion_min_window_seconds": settings.motion_min_window_seconds,
            "motion_min_sample_count": settings.motion_min_sample_count,
            "motion_validation_score_weight": settings.motion_validation_score_weight,
            "motion_validation_adjustment_cap": settings.motion_validation_adjustment_cap,
            "motion_max_speed_mps": settings.motion_max_speed_mps,
            "fraud_llm_fallback_enabled": settings.fraud_llm_fallback_enabled,
        }
        settings.motion_validation_enabled = True
        settings.motion_signal_freshness_minutes = 30
        settings.motion_min_window_seconds = 60
        settings.motion_min_sample_count = 12
        settings.motion_validation_score_weight = 0.10
        settings.motion_validation_adjustment_cap = 0.10
        settings.motion_max_speed_mps = 33.0
        settings.fraud_llm_fallback_enabled = False

    def tearDown(self) -> None:
        for key, value in self._original.items():
            setattr(settings, key, value)

    def test_motion_missing_is_neutral(self) -> None:
        result = validate_motion_metadata(
            motion_metadata=None,
            captured_at=None,
            received_at=None,
        )
        self.assertEqual(result["status"], "missing")
        self.assertEqual(result["confidence"], 0.5)
        self.assertFalse(result["eligible"])

    def test_motion_stale_is_neutral(self) -> None:
        now = datetime(2026, 4, 12, 12, 0, tzinfo=timezone.utc)
        stale = now - timedelta(minutes=90)
        result = validate_motion_metadata(
            motion_metadata={"windowSeconds": 120, "sampleCount": 24, "distanceMeters": 120.0},
            captured_at=stale,
            received_at=stale,
            now_utc=now,
        )
        self.assertEqual(result["status"], "stale")
        self.assertEqual(result["confidence"], 0.5)
        self.assertFalse(result["eligible"])

    def test_motion_genuine_pattern_scores_positive(self) -> None:
        now = datetime(2026, 4, 12, 12, 0, tzinfo=timezone.utc)
        result = validate_motion_metadata(
            motion_metadata={
                "windowSeconds": 180,
                "sampleCount": 30,
                "movingSeconds": 110,
                "stationarySeconds": 70,
                "distanceMeters": 220,
                "avgSpeedMps": 2.2,
                "maxSpeedMps": 6.0,
            },
            captured_at=now,
            received_at=now,
            now_utc=now,
        )
        self.assertEqual(result["status"], "match")
        self.assertTrue(result["eligible"])
        self.assertGreater(result["confidence"], 0.55)

    def test_motion_guardrail_reduces_penalty_without_corroboration(self) -> None:
        features = {
            "zone_affinity_score": 0.85,
            "fraud_ring_size": 0.0,
            "recent_claims_24h": 0.0,
            "claim_amount": 320.0,
            "trigger_confidence": 0.55,
            "is_manual_source": 1.0,
            "is_auto_source": 0.0,
            "flood_risk_score": 0.5,
            "aqi_risk_score": 0.5,
            "traffic_congestion_score": 0.5,
            "tower_validation_status": "missing",
            "tower_zone_confidence": 0.5,
            "tower_signal_present": 0.0,
            "motion_validation_status": "mismatch",
            "motion_confidence": 0.2,
            "motion_validation_reason": "motion_low_quality_pattern",
            "motion_signal_present": 1.0,
            "motion_signal_eligible": 1.0,
            "motion_signal_age_minutes": 3.0,
        }
        with (
            patch.object(fraud_isolation, "_model", _StubIsolationModel(-0.04)),
            patch.object(fraud_isolation, "_model_version", "iforest-v1"),
        ):
            result = fraud_isolation.score_claim(features, context={"phone": "9999999999", "claim_type": "RainLock"})
        adjustment = float(result["anomaly_features"]["motion_score_adjustment"])
        self.assertLess(adjustment, 0.0)
        self.assertGreaterEqual(adjustment, -0.06)


if __name__ == "__main__":
    unittest.main()
