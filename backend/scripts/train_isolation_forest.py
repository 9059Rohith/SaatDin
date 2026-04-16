from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import asyncpg
import numpy as np
from joblib import dump
from sklearn.ensemble import IsolationForest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.fraud_isolation import FEATURE_NAMES, normalize_features


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train and version Isolation Forest artifact for fraud scoring")
    parser.add_argument("--supabase-db-url", default="", help="Optional Postgres URL to bootstrap from real claim metadata")
    parser.add_argument("--output-dir", default="backend/models/fraud", help="Directory for model artifacts")
    parser.add_argument("--version", default="", help="Artifact version suffix; default is UTC timestamp")
    parser.add_argument("--contamination", type=float, default=0.08, help="IsolationForest contamination rate")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic random seed")
    parser.add_argument("--min-training-samples", type=int, default=400, help="Minimum rows needed for training")
    parser.add_argument("--max-real-samples", type=int, default=50000, help="Maximum real rows to read")
    parser.add_argument("--synthetic-samples", type=int, default=1200, help="Synthetic fallback rows when real data is sparse")
    return parser.parse_args()


def _build_feature_vector(rows: List[Dict[str, float]]) -> np.ndarray:
    return np.array([[row[name] for name in FEATURE_NAMES] for row in rows], dtype=float)


def _generate_synthetic_rows(count: int, seed: int) -> List[Dict[str, float]]:
    rng = np.random.default_rng(seed)
    rows: List[Dict[str, float]] = []
    normal_count = max(1, int(count * 0.9))
    anomaly_count = max(0, count - normal_count)

    for _ in range(normal_count):
        is_manual = float(rng.choice([0, 1], p=[0.65, 0.35]))
        rows.append(
            normalize_features(
                {
                    "zone_affinity_score": float(rng.uniform(0.55, 1.0)),
                    "fraud_ring_size": float(np.clip(rng.poisson(0.4), 0, 4)),
                    "recent_claims_24h": float(np.clip(rng.poisson(0.8), 0, 6)),
                    "claim_amount": float(np.clip(rng.normal(360.0, 90.0), 60.0, 900.0)),
                    "trigger_confidence": float(rng.uniform(0.65, 0.99)),
                    "is_manual_source": is_manual,
                    "is_auto_source": 1.0 - is_manual,
                    "flood_risk_score": float(rng.uniform(0.2, 0.9)),
                    "aqi_risk_score": float(rng.uniform(0.2, 0.9)),
                    "traffic_congestion_score": float(rng.uniform(0.25, 0.95)),
                }
            )
        )

    for _ in range(anomaly_count):
        is_manual = float(rng.choice([0, 1], p=[0.30, 0.70]))
        rows.append(
            normalize_features(
                {
                    "zone_affinity_score": float(rng.uniform(0.05, 0.35)),
                    "fraud_ring_size": float(rng.integers(3, 10)),
                    "recent_claims_24h": float(rng.integers(5, 22)),
                    "claim_amount": float(rng.uniform(700.0, 2400.0)),
                    "trigger_confidence": float(rng.uniform(0.20, 0.65)),
                    "is_manual_source": is_manual,
                    "is_auto_source": 1.0 - is_manual,
                    "flood_risk_score": float(rng.uniform(0.4, 1.0)),
                    "aqi_risk_score": float(rng.uniform(0.4, 1.0)),
                    "traffic_congestion_score": float(rng.uniform(0.4, 1.0)),
                }
            )
        )

    return rows


async def _fetch_real_rows(supabase_db_url: str, max_rows: int) -> List[Dict[str, float]]:
    if not supabase_db_url.strip():
        return []

    pool = await asyncpg.create_pool(dsn=supabase_db_url, min_size=1, max_size=3)
    try:
        async with pool.acquire() as conn:
            try:
                rows = await conn.fetch(
                    """
                    SELECT anomaly_features_json
                    FROM claims
                    WHERE anomaly_features_json IS NOT NULL
                    ORDER BY created_at DESC
                    LIMIT $1
                    """,
                    max_rows,
                )
            except Exception as exc:
                print(f"real_data_unavailable reason={exc}")
                return []
    finally:
        await pool.close()

    parsed_rows: List[Dict[str, float]] = []
    for row in rows:
        payload = row["anomaly_features_json"]
        if payload is None:
            continue
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                continue
        if isinstance(payload, dict):
            parsed_rows.append(normalize_features(payload))
    return parsed_rows


def _write_artifacts(
    model: IsolationForest,
    output_dir: Path,
    version: str,
    contamination: float,
    seed: int,
    real_samples: int,
    synthetic_samples: int,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    version_model = output_dir / f"fraud_iforest_{version}.joblib"
    version_metadata = output_dir / f"fraud_iforest_{version}.json"
    latest_model = output_dir / "fraud_iforest_latest.joblib"
    latest_metadata = output_dir / "fraud_iforest_latest.json"

    dump(model, version_model)

    metadata: Dict[str, Any] = {
        "version": version,
        "trained_at_utc": datetime.now(timezone.utc).isoformat(),
        "model_type": "IsolationForest",
        "feature_names": list(FEATURE_NAMES),
        "contamination": contamination,
        "random_seed": seed,
        "real_samples": real_samples,
        "synthetic_samples": synthetic_samples,
        "total_samples": real_samples + synthetic_samples,
    }
    version_metadata.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    shutil.copy2(version_model, latest_model)
    shutil.copy2(version_metadata, latest_metadata)

    print(f"saved_model={version_model}")
    print(f"saved_metadata={version_metadata}")
    print(f"latest_model={latest_model}")
    print(f"latest_metadata={latest_metadata}")


async def _run() -> None:
    args = _parse_args()
    if not 0.0 < args.contamination < 0.5:
        raise ValueError("--contamination must be between 0 and 0.5")

    version = args.version.strip() or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    output_dir = Path(args.output_dir).resolve()

    real_rows = await _fetch_real_rows(args.supabase_db_url, args.max_real_samples)
    synthetic_rows: List[Dict[str, float]] = []

    if len(real_rows) < args.min_training_samples:
        required = max(args.synthetic_samples, args.min_training_samples - len(real_rows))
        synthetic_rows = _generate_synthetic_rows(required, args.seed)

    training_rows = real_rows + synthetic_rows
    if not training_rows:
        raise RuntimeError("No training rows available")

    X = _build_feature_vector(training_rows)
    model = IsolationForest(
        n_estimators=200,
        contamination=args.contamination,
        random_state=args.seed,
        n_jobs=-1,
    )
    model.fit(X)

    _write_artifacts(
        model=model,
        output_dir=output_dir,
        version=version,
        contamination=float(args.contamination),
        seed=int(args.seed),
        real_samples=len(real_rows),
        synthetic_samples=len(synthetic_rows),
    )
    print(
        "training_complete "
        f"version={version} total_rows={len(training_rows)} real_rows={len(real_rows)} synthetic_rows={len(synthetic_rows)}"
    )


if __name__ == "__main__":
    asyncio.run(_run())
