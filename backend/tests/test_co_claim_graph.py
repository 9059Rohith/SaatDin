from __future__ import annotations

import unittest
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.fraud_clusters import router as fraud_clusters_router
from backend.app.core.config import settings
from backend.app.core.dependencies import get_current_phone
from backend.app.services.co_claim_graph import compute_co_claim_clusters
from backend.app.services.co_claim_monitor import CoClaimClusterMonitor


def _claim(phone: str, created_at: datetime, claim_type: str = "RainLock", zone: str = "560103") -> dict:
    return {
        "phone": phone,
        "claim_type": claim_type,
        "zone_pincode": zone,
        "created_at": created_at.astimezone(timezone.utc).isoformat(),
    }


class CoClaimGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original = {
            "co_claim_graph_time_bucket_minutes": settings.co_claim_graph_time_bucket_minutes,
            "co_claim_graph_min_edge_support": settings.co_claim_graph_min_edge_support,
            "co_claim_graph_min_cluster_members": settings.co_claim_graph_min_cluster_members,
            "co_claim_graph_lookback_days": settings.co_claim_graph_lookback_days,
            "co_claim_graph_recency_half_life_days": settings.co_claim_graph_recency_half_life_days,
            "co_claim_graph_max_clusters_per_run": settings.co_claim_graph_max_clusters_per_run,
            "co_claim_graph_medium_risk_threshold": settings.co_claim_graph_medium_risk_threshold,
            "co_claim_graph_high_risk_threshold": settings.co_claim_graph_high_risk_threshold,
        }
        settings.co_claim_graph_time_bucket_minutes = 10
        settings.co_claim_graph_min_edge_support = 2
        settings.co_claim_graph_min_cluster_members = 3
        settings.co_claim_graph_lookback_days = 30
        settings.co_claim_graph_recency_half_life_days = 7.0
        settings.co_claim_graph_max_clusters_per_run = 50
        settings.co_claim_graph_medium_risk_threshold = 0.50
        settings.co_claim_graph_high_risk_threshold = 0.75

    def tearDown(self) -> None:
        for key, value in self.original.items():
            setattr(settings, key, value)

    def test_detects_cluster_with_supporting_metadata(self) -> None:
        now = datetime(2026, 4, 12, 12, 30, tzinfo=timezone.utc)
        claims = [
            _claim("9000000001", now.replace(hour=10, minute=1)),
            _claim("9000000002", now.replace(hour=10, minute=1)),
            _claim("9000000003", now.replace(hour=10, minute=1)),
            _claim("9000000001", now.replace(hour=11, minute=2)),
            _claim("9000000002", now.replace(hour=11, minute=2)),
            _claim("9000000003", now.replace(hour=11, minute=2)),
            _claim("9000000001", now.replace(hour=12, minute=3)),
            _claim("9000000002", now.replace(hour=12, minute=3)),
            _claim("9000000003", now.replace(hour=12, minute=3)),
        ]
        result = compute_co_claim_clusters(claims=claims, now_utc=now)
        self.assertEqual(result["cluster_count"], 1)
        self.assertEqual(result["flagged_cluster_count"], 1)

        cluster = result["clusters"][0]
        self.assertIn(cluster["risk_level"], {"medium", "high"})
        self.assertIn("supporting_metadata", cluster)
        self.assertIn("formula", cluster["supporting_metadata"])
        self.assertTrue(cluster["supporting_metadata"]["top_edges"])

    def test_recency_decay_reduces_risk_score(self) -> None:
        now = datetime(2026, 4, 12, 12, 30, tzinfo=timezone.utc)
        recent_claims = [
            _claim("9000000011", now.replace(hour=10, minute=5)),
            _claim("9000000012", now.replace(hour=10, minute=5)),
            _claim("9000000013", now.replace(hour=10, minute=5)),
            _claim("9000000011", now.replace(hour=11, minute=5)),
            _claim("9000000012", now.replace(hour=11, minute=5)),
            _claim("9000000013", now.replace(hour=11, minute=5)),
            _claim("9000000011", now.replace(hour=12, minute=5)),
            _claim("9000000012", now.replace(hour=12, minute=5)),
            _claim("9000000013", now.replace(hour=12, minute=5)),
        ]
        older_base = now - timedelta(days=25)
        older_claims = [
            _claim("9000000011", older_base.replace(hour=10, minute=5)),
            _claim("9000000012", older_base.replace(hour=10, minute=5)),
            _claim("9000000013", older_base.replace(hour=10, minute=5)),
            _claim("9000000011", older_base.replace(hour=11, minute=5)),
            _claim("9000000012", older_base.replace(hour=11, minute=5)),
            _claim("9000000013", older_base.replace(hour=11, minute=5)),
            _claim("9000000011", older_base.replace(hour=12, minute=5)),
            _claim("9000000012", older_base.replace(hour=12, minute=5)),
            _claim("9000000013", older_base.replace(hour=12, minute=5)),
        ]

        recent_score = compute_co_claim_clusters(claims=recent_claims, now_utc=now)["clusters"][0]["risk_score"]
        older_score = compute_co_claim_clusters(claims=older_claims, now_utc=now)["clusters"][0]["risk_score"]
        self.assertGreater(recent_score, older_score)

    def test_clusters_endpoint_returns_flagged_with_metadata(self) -> None:
        app = FastAPI()
        app.include_router(fraud_clusters_router, prefix="/api/v1/fraud")
        app.dependency_overrides[get_current_phone] = lambda: "9999999999"
        client = TestClient(app)
        now_iso = datetime.now(timezone.utc).isoformat()

        with (
            patch("backend.app.api.fraud_clusters.get_latest_fraud_cluster_run", new=AsyncMock(return_value={"id": 7})),
            patch(
                "backend.app.api.fraud_clusters.list_fraud_clusters",
                new=AsyncMock(
                    return_value=[
                        {
                            "id": 42,
                            "run_id": 7,
                            "cluster_key": "abc123",
                            "risk_score": 0.82,
                            "risk_level": "high",
                            "member_count": 4,
                            "edge_count": 5,
                            "event_count": 9,
                            "frequency_score": 0.88,
                            "recency_score": 0.77,
                            "supporting_metadata_json": {"top_edges": [{"phone_a": "a", "phone_b": "b"}]},
                            "created_at": now_iso,
                        }
                    ]
                ),
            ) as mock_list_clusters,
        ):
            response = client.get("/api/v1/fraud/clusters")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["data"][0]["riskLevel"], "high")
        self.assertIn("supportingMetadataJson", payload["data"][0])
        self.assertEqual(payload["data"][0]["createdAt"], now_iso)
        mock_list_clusters.assert_awaited_once()

    def test_monitor_stop_safe_when_pipeline_disabled(self) -> None:
        settings.co_claim_graph_enabled = False
        monitor = CoClaimClusterMonitor()
        asyncio.run(monitor.start())
        asyncio.run(monitor.stop())


if __name__ == "__main__":
    unittest.main()
