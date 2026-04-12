from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.app.core.config import settings
from backend.app.services import fraud_isolation, fraud_llm_graph


class _StubIsolationModel:
    def __init__(self, score: float) -> None:
        self._score = score

    def decision_function(self, _feature_vector):
        return [self._score]


class FraudLLMFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original = {
            "fraud_llm_fallback_enabled": settings.fraud_llm_fallback_enabled,
            "fraud_llm_ambiguity_margin": settings.fraud_llm_ambiguity_margin,
            "fraud_llm_trigger_confidence_min": settings.fraud_llm_trigger_confidence_min,
            "fraud_llm_trigger_confidence_max": settings.fraud_llm_trigger_confidence_max,
            "fraud_llm_provider_order": settings.fraud_llm_provider_order,
        }
        settings.fraud_llm_fallback_enabled = True
        settings.fraud_llm_ambiguity_margin = 0.02
        settings.fraud_llm_trigger_confidence_min = 0.35
        settings.fraud_llm_trigger_confidence_max = 0.75
        settings.fraud_llm_provider_order = "groq,gemini"

    def tearDown(self) -> None:
        for key, value in self._original.items():
            setattr(settings, key, value)

    def test_ambiguity_gate_honors_configured_confidence_conditions(self) -> None:
        features = fraud_isolation.normalize_features(
            {
                "zone_affinity_score": 0.6,
                "fraud_ring_size": 0.0,
                "recent_claims_24h": 1.0,
                "claim_amount": 350.0,
                "trigger_confidence": 0.6,
            }
        )
        self.assertTrue(
            fraud_isolation._should_use_llm_fallback(
                score=-0.049,
                threshold=-0.05,
                features=features,
            )
        )
        self.assertFalse(
            fraud_isolation._should_use_llm_fallback(
                score=-0.010,
                threshold=-0.05,
                features=features,
            )
        )
        low_conf_features = dict(features)
        low_conf_features["trigger_confidence"] = 0.2
        self.assertFalse(
            fraud_isolation._should_use_llm_fallback(
                score=-0.049,
                threshold=-0.05,
                features=low_conf_features,
            )
        )

    def test_invalid_llm_output_is_rejected_safely(self) -> None:
        features = fraud_isolation.normalize_features(
            {
                "zone_affinity_score": 0.61,
                "fraud_ring_size": 0.0,
                "recent_claims_24h": 0.0,
                "claim_amount": 300.0,
                "trigger_confidence": 0.55,
            }
        )
        with (
            patch.object(fraud_isolation, "_model", _StubIsolationModel(-0.049)),
            patch.object(fraud_isolation, "_model_version", "iforest-v1"),
            patch.object(
                fraud_isolation,
                "run_fraud_llm_fallback",
                return_value={
                    "status": "invalid_output",
                    "decision": None,
                    "provider": "groq",
                    "model": "llama-3.3-70b-versatile",
                    "fallback_used": False,
                    "attempts": [{"provider": "groq", "success": True}],
                    "validation_error": "missing field",
                    "scored_at": "2026-01-01T00:00:00+00:00",
                },
            ),
        ):
            result = fraud_isolation.score_claim(
                features,
                context={"phone": "9999999999", "claim_type": "RainLock", "source": "auto"},
            )

        self.assertTrue(result["llm_review_used"])
        self.assertEqual(result["llm_review_status"], "invalid_output")
        self.assertTrue(result["anomaly_flagged"])

    def test_provider_failover_uses_configured_order(self) -> None:
        valid_payload = {
            "anomaly_flagged": False,
            "confidence": 0.84,
            "rationale": "Signals are stable and do not indicate coordinated abuse.",
            "risk_signals": ["zone_affinity_ok", "low_ring_size"],
            "recommended_status": "settled",
        }
        with patch.object(
            fraud_llm_graph,
            "_invoke_provider",
            side_effect=[
                {
                    "provider": "groq",
                    "model": "llama-3.3-70b-versatile",
                    "success": False,
                    "latency_ms": 50,
                    "payload": None,
                    "error": "timeout",
                },
                {
                    "provider": "gemini",
                    "model": "gemini-2.5-flash",
                    "success": True,
                    "latency_ms": 70,
                    "payload": valid_payload,
                    "error": None,
                },
            ],
        ):
            invoked = fraud_llm_graph._invoke_providers_node(
                {"providers": ["groq", "gemini"], "attempts": [], "prompt": "{}"}
            )
            self.assertEqual(invoked["provider"], "gemini")
            self.assertTrue(invoked["fallback_used"])
            self.assertEqual(len(invoked["attempts"]), 2)

            validated = fraud_llm_graph._validate_output_node(invoked)
            self.assertEqual(validated["status"], "accepted")
            self.assertIsInstance(validated["decision"], dict)


if __name__ == "__main__":
    unittest.main()
