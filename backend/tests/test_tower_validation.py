from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.workers import router as workers_router
from backend.app.core.config import settings
from backend.app.core.dependencies import get_current_worker
from backend.app.services import fraud_isolation
from backend.app.services.tower_validation import validate_tower_metadata_for_zone


class _StubIsolationModel:
    def __init__(self, score: float) -> None:
        self._score = score

    def decision_function(self, _feature_vector):
        return [self._score]


class TowerValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original = {
            "tower_validation_enabled": settings.tower_validation_enabled,
            "tower_signal_freshness_minutes": settings.tower_signal_freshness_minutes,
            "tower_validation_score_weight": settings.tower_validation_score_weight,
            "tower_validation_adjustment_cap": settings.tower_validation_adjustment_cap,
            "fraud_llm_fallback_enabled": settings.fraud_llm_fallback_enabled,
        }
        settings.tower_validation_enabled = True
        settings.tower_signal_freshness_minutes = 30
        settings.tower_validation_score_weight = 0.12
        settings.tower_validation_adjustment_cap = 0.12
        settings.fraud_llm_fallback_enabled = False

    def tearDown(self) -> None:
        for key, value in self._original.items():
            setattr(settings, key, value)

    def test_missing_tower_payload_returns_neutral_fallback(self) -> None:
        result = validate_tower_metadata_for_zone(
            tower_metadata=None,
            claimed_zone_pincode="560001",
            zone_lat=12.9716,
            zone_lon=77.5946,
            captured_at=None,
            received_at=None,
        )
        self.assertEqual(result["status"], "missing")
        self.assertEqual(result["confidence"], 0.5)
        self.assertFalse(result["signal_present"])

    def test_stale_tower_payload_returns_neutral_fallback(self) -> None:
        now = datetime(2026, 4, 12, 12, 0, tzinfo=timezone.utc)
        stale = now - timedelta(minutes=90)
        result = validate_tower_metadata_for_zone(
            tower_metadata={
                "servingCell": {
                    "cellId": "abc",
                    "signalDbm": -85,
                    "approxLatitude": 12.9718,
                    "approxLongitude": 77.5948,
                }
            },
            claimed_zone_pincode="560001",
            zone_lat=12.9716,
            zone_lon=77.5946,
            captured_at=stale,
            received_at=stale,
            now_utc=now,
        )
        self.assertEqual(result["status"], "stale")
        self.assertEqual(result["confidence"], 0.5)

    def test_distance_based_validation_produces_match_and_mismatch(self) -> None:
        now = datetime(2026, 4, 12, 12, 0, tzinfo=timezone.utc)
        matched = validate_tower_metadata_for_zone(
            tower_metadata={
                "servingCell": {
                    "cellId": "near",
                    "signalDbm": -70,
                    "approxLatitude": 12.9717,
                    "approxLongitude": 77.5947,
                }
            },
            claimed_zone_pincode="560001",
            zone_lat=12.9716,
            zone_lon=77.5946,
            captured_at=now,
            received_at=now,
            now_utc=now,
        )
        mismatched = validate_tower_metadata_for_zone(
            tower_metadata={
                "servingCell": {
                    "cellId": "far",
                    "signalDbm": -75,
                    "approxLatitude": 13.2000,
                    "approxLongitude": 77.1000,
                }
            },
            claimed_zone_pincode="560001",
            zone_lat=12.9716,
            zone_lon=77.5946,
            captured_at=now,
            received_at=now,
            now_utc=now,
        )
        self.assertEqual(matched["status"], "match")
        self.assertGreater(matched["confidence"], 0.5)
        self.assertEqual(mismatched["status"], "mismatch")
        self.assertLess(mismatched["confidence"], 0.5)

    def test_score_claim_applies_tower_adjustment(self) -> None:
        features = {
            "zone_affinity_score": 0.7,
            "fraud_ring_size": 0.0,
            "recent_claims_24h": 0.0,
            "claim_amount": 320.0,
            "trigger_confidence": 0.6,
            "is_manual_source": 1.0,
            "is_auto_source": 0.0,
            "flood_risk_score": 0.5,
            "aqi_risk_score": 0.5,
            "traffic_congestion_score": 0.4,
            "tower_validation_status": "mismatch",
            "tower_zone_confidence": 0.1,
            "tower_validation_reason": "tower_distance_mismatch",
            "tower_signal_present": 1.0,
            "tower_signal_age_minutes": 2.0,
        }
        with (
            patch.object(fraud_isolation, "_model", _StubIsolationModel(-0.04)),
            patch.object(fraud_isolation, "_model_version", "iforest-v1"),
        ):
            result = fraud_isolation.score_claim(features, context={"phone": "9999999999", "claim_type": "RainLock"})

        self.assertTrue(result["anomaly_flagged"])
        self.assertLess(float(result["anomaly_score"]), float(result["anomaly_threshold"]))
        self.assertIn("tower_score_adjustment", result["anomaly_features"])

    def test_location_signal_ingestion_endpoint(self) -> None:
        app = FastAPI()
        app.include_router(workers_router, prefix="/api/v1")
        app.dependency_overrides[get_current_worker] = lambda: {
            "phone": "9999999999",
            "zone_pincode": "560001",
            "name": "Worker",
            "platform_name": "Blinkit",
            "zone_name": "Indiranagar",
            "plan_name": "Weekly Saver",
        }
        client = TestClient(app)

        with (
            patch("backend.app.api.workers.upsert_worker_location_signal", new=AsyncMock(return_value={})),
            patch(
                "backend.app.api.workers.evaluate_worker_tower_signal",
                new=AsyncMock(
                    return_value={
                        "status": "match",
                        "confidence": 0.91,
                        "reason": "tower_distance_match",
                        "signal_present": True,
                        "signal_received_at": "2026-04-12T12:00:00+00:00",
                        "signal_age_minutes": 1.5,
                    }
                ),
            ),
            patch(
                "backend.app.api.workers.evaluate_worker_motion_signal",
                new=AsyncMock(
                    return_value={
                        "status": "match",
                        "confidence": 0.78,
                        "reason": "motion_genuine_pattern",
                        "eligible": True,
                        "signal_present": True,
                        "signal_received_at": "2026-04-12T12:00:00+00:00",
                        "signal_age_minutes": 1.2,
                    }
                ),
            ),
            patch("backend.app.api.workers.resolve_zone", return_value=("560001", {"latitude": 12.97, "longitude": 77.59})),
            patch("backend.app.api.workers.update_worker_gps", new=Mock()),
            patch("backend.app.api.workers.purge_stale_worker_location_signals", new=AsyncMock(return_value=0)),
        ):
            response = client.post(
                "/api/v1/workers/location-signal",
                json={
                    "latitude": 12.9716,
                    "longitude": 77.5946,
                    "accuracyMeters": 25,
                    "capturedAt": "2026-04-12T12:00:00+00:00",
                    "towerMetadata": {
                        "servingCell": {"cellId": "serving-1", "signalDbm": -82},
                        "neighborCells": [{"cellId": "n1", "signalDbm": -90}],
                    },
                    "motionMetadata": {
                        "windowSeconds": 120,
                        "sampleCount": 24,
                        "movingSeconds": 70,
                        "stationarySeconds": 50,
                        "distanceMeters": 160,
                        "avgSpeedMps": 1.8,
                        "maxSpeedMps": 5.2,
                    },
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["data"]["tower"]["status"], "match")
        self.assertEqual(payload["data"]["tower"]["reason"], "tower_distance_match")
        self.assertEqual(payload["data"]["motion"]["status"], "match")
        self.assertEqual(payload["data"]["motion"]["reason"], "motion_genuine_pattern")


if __name__ == "__main__":
    unittest.main()
