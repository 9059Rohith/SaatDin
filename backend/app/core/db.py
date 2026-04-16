from __future__ import annotations

from datetime import datetime, timezone, timedelta
import json
from typing import Any, Dict, List, Optional
from urllib.parse import unquote, urlparse
import ssl

import logging

import asyncpg

from .config import settings


_pool: Optional[asyncpg.Pool] = None
logger = logging.getLogger(__name__)


def _utc_now_iso() -> datetime:
    return datetime.now(timezone.utc)


def _row_to_dict(row: Optional[asyncpg.Record]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    return dict(row)


def _rows_to_dicts(rows: list[asyncpg.Record]) -> list[Dict[str, Any]]:
    return [dict(row) for row in rows]


def _to_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


async def _get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        dsn = settings.database_url

        # Supabase pooler connections need SSL context that accepts self-signed certs
        if "pooler.supabase.com" in dsn.lower():
            parsed = urlparse(dsn)
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            logger.info("db_connect_attempt", extra={"using_pooler": True, "ssl_context_set": True})

            # Use explicit connection kwargs so asyncpg cannot override SSL behavior from DSN options.
            _pool = await asyncpg.create_pool(
                user=unquote(parsed.username or ""),
                password=unquote(parsed.password or ""),
                database=(parsed.path or "/postgres").lstrip("/"),
                host=parsed.hostname,
                port=parsed.port or 5432,
                min_size=settings.db_pool_min_size,
                max_size=settings.db_pool_max_size,
                command_timeout=30,
                ssl=ctx,
            )
        else:
            logger.info("db_connect_attempt", extra={"using_pooler": False})
            _pool = await asyncpg.create_pool(
                dsn=dsn,
                min_size=settings.db_pool_min_size,
                max_size=settings.db_pool_max_size,
                command_timeout=30,
            )
    return _pool


async def init_db() -> None:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS otp_codes (
                phone TEXT PRIMARY KEY,
                otp_hash TEXT NOT NULL,
                expires_at TIMESTAMPTZ NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_sent_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workers (
                phone TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                platform_name TEXT NOT NULL,
                zone_pincode TEXT NOT NULL,
                zone_name TEXT NOT NULL,
                plan_name TEXT NOT NULL,
                pending_plan_name TEXT,
                pending_plan_effective_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        await conn.execute("ALTER TABLE workers ADD COLUMN IF NOT EXISTS pending_plan_name TEXT")
        await conn.execute("ALTER TABLE workers ADD COLUMN IF NOT EXISTS pending_plan_effective_at TIMESTAMPTZ")
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS claims (
                id BIGSERIAL PRIMARY KEY,
                phone TEXT NOT NULL,
                claim_type TEXT NOT NULL,
                status TEXT NOT NULL,
                amount REAL NOT NULL,
                description TEXT NOT NULL,
                zone_pincode TEXT NOT NULL,
                source TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        await conn.execute("ALTER TABLE claims ADD COLUMN IF NOT EXISTS source TEXT")
        await conn.execute("UPDATE claims SET source = 'manual' WHERE source IS NULL")
        await conn.execute("ALTER TABLE claims ALTER COLUMN source SET DEFAULT 'manual'")
        await conn.execute("ALTER TABLE claims ALTER COLUMN source SET NOT NULL")
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS worker_location_signals (
                phone TEXT PRIMARY KEY,
                latitude DOUBLE PRECISION,
                longitude DOUBLE PRECISION,
                accuracy_meters DOUBLE PRECISION,
                captured_at TIMESTAMPTZ,
                tower_metadata_json JSONB,
                motion_metadata_json JSONB,
                received_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        await conn.execute("ALTER TABLE worker_location_signals ADD COLUMN IF NOT EXISTS motion_metadata_json JSONB")
        await conn.execute("ALTER TABLE claims ADD COLUMN IF NOT EXISTS anomaly_score DOUBLE PRECISION")
        await conn.execute("ALTER TABLE claims ADD COLUMN IF NOT EXISTS anomaly_threshold DOUBLE PRECISION")
        await conn.execute("ALTER TABLE claims ADD COLUMN IF NOT EXISTS anomaly_flagged BOOLEAN")
        await conn.execute("ALTER TABLE claims ADD COLUMN IF NOT EXISTS anomaly_model_version TEXT")
        await conn.execute("ALTER TABLE claims ADD COLUMN IF NOT EXISTS anomaly_features_json JSONB")
        await conn.execute("ALTER TABLE claims ADD COLUMN IF NOT EXISTS anomaly_scored_at TIMESTAMPTZ")
        await conn.execute("ALTER TABLE claims ADD COLUMN IF NOT EXISTS llm_review_used BOOLEAN")
        await conn.execute("ALTER TABLE claims ADD COLUMN IF NOT EXISTS llm_review_status TEXT")
        await conn.execute("ALTER TABLE claims ADD COLUMN IF NOT EXISTS llm_provider TEXT")
        await conn.execute("ALTER TABLE claims ADD COLUMN IF NOT EXISTS llm_model TEXT")
        await conn.execute("ALTER TABLE claims ADD COLUMN IF NOT EXISTS llm_fallback_used BOOLEAN")
        await conn.execute("ALTER TABLE claims ADD COLUMN IF NOT EXISTS llm_decision_confidence DOUBLE PRECISION")
        await conn.execute("ALTER TABLE claims ADD COLUMN IF NOT EXISTS llm_decision_json JSONB")
        await conn.execute("ALTER TABLE claims ADD COLUMN IF NOT EXISTS llm_attempts_json JSONB")
        await conn.execute("ALTER TABLE claims ADD COLUMN IF NOT EXISTS llm_validation_error TEXT")
        await conn.execute("ALTER TABLE claims ADD COLUMN IF NOT EXISTS llm_scored_at TIMESTAMPTZ")
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS zonelock_reports (
                id BIGSERIAL PRIMARY KEY,
                phone TEXT NOT NULL,
                zone_pincode TEXT NOT NULL,
                zone_name TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL,
                confidence REAL NOT NULL,
                verified_count INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS claim_escalations (
                id BIGSERIAL PRIMARY KEY,
                claim_id INTEGER NOT NULL,
                phone TEXT NOT NULL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL,
                review_notes TEXT,
                created_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fraud_cluster_runs (
                id BIGSERIAL PRIMARY KEY,
                started_at TIMESTAMPTZ NOT NULL,
                finished_at TIMESTAMPTZ,
                status TEXT NOT NULL,
                error_message TEXT,
                lookback_days INTEGER NOT NULL,
                time_bucket_minutes INTEGER NOT NULL,
                min_edge_support INTEGER NOT NULL,
                medium_risk_threshold DOUBLE PRECISION NOT NULL,
                high_risk_threshold DOUBLE PRECISION NOT NULL,
                claims_scanned INTEGER NOT NULL DEFAULT 0,
                edge_count INTEGER NOT NULL DEFAULT 0,
                cluster_count INTEGER NOT NULL DEFAULT 0,
                flagged_cluster_count INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fraud_co_claim_clusters (
                id BIGSERIAL PRIMARY KEY,
                run_id BIGINT NOT NULL,
                cluster_key TEXT NOT NULL,
                risk_score DOUBLE PRECISION NOT NULL,
                risk_level TEXT NOT NULL,
                member_count INTEGER NOT NULL,
                edge_count INTEGER NOT NULL,
                event_count INTEGER NOT NULL,
                frequency_score DOUBLE PRECISION NOT NULL,
                recency_score DOUBLE PRECISION NOT NULL,
                supporting_metadata_json JSONB,
                created_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fraud_co_claim_cluster_members (
                id BIGSERIAL PRIMARY KEY,
                cluster_id BIGINT NOT NULL,
                phone TEXT NOT NULL,
                claim_count INTEGER NOT NULL,
                first_claim_at TIMESTAMPTZ,
                last_claim_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fraud_co_claim_cluster_edges (
                id BIGSERIAL PRIMARY KEY,
                cluster_id BIGINT NOT NULL,
                phone_a TEXT NOT NULL,
                phone_b TEXT NOT NULL,
                co_claim_count INTEGER NOT NULL,
                recency_weight DOUBLE PRECISION NOT NULL,
                edge_weight DOUBLE PRECISION NOT NULL,
                last_co_claim_at TIMESTAMPTZ,
                supporting_metadata_json JSONB,
                created_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_fraud_cluster_runs_created_at ON fraud_cluster_runs(created_at DESC)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_fraud_co_claim_clusters_run_id ON fraud_co_claim_clusters(run_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_fraud_co_claim_clusters_risk_level ON fraud_co_claim_clusters(risk_level)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_fraud_co_claim_cluster_members_cluster_id ON fraud_co_claim_cluster_members(cluster_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_fraud_co_claim_cluster_members_phone ON fraud_co_claim_cluster_members(phone)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_fraud_co_claim_cluster_edges_cluster_id ON fraud_co_claim_cluster_edges(cluster_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_worker_location_signals_received_at ON worker_location_signals(received_at DESC)")


async def close_db() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def healthcheck_db() -> bool:
    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            await conn.execute("SELECT 1")
        return True
    except Exception:
        return False


async def save_otp(phone: str, otp_hash: str, expires_at: str | datetime) -> None:
    now = _utc_now_iso()
    expires_value: datetime
    if isinstance(expires_at, str):
        expires_value = datetime.fromisoformat(expires_at)
    else:
        expires_value = expires_at
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO otp_codes (phone, otp_hash, expires_at, attempts, last_sent_at)
            VALUES ($1, $2, $3, 0, $4)
            ON CONFLICT(phone) DO UPDATE SET
                otp_hash=excluded.otp_hash,
                expires_at=excluded.expires_at,
                attempts=0,
                last_sent_at=excluded.last_sent_at
            """,
            phone,
            otp_hash,
            expires_value,
            now,
        )


async def get_otp(phone: str) -> Optional[Dict[str, Any]]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM otp_codes WHERE phone = $1", phone)
    out = _row_to_dict(row)
    if out is None:
        return None
    out["expires_at"] = _to_iso(out["expires_at"])
    out["last_sent_at"] = _to_iso(out["last_sent_at"])
    return out


async def increment_otp_attempts(phone: str) -> None:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE otp_codes SET attempts = attempts + 1 WHERE phone = $1", phone)


async def delete_otp(phone: str) -> None:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM otp_codes WHERE phone = $1", phone)


async def upsert_worker(
    *,
    phone: str,
    name: str,
    platform_name: str,
    zone_pincode: str,
    zone_name: str,
    plan_name: str,
) -> None:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO workers (phone, name, platform_name, zone_pincode, zone_name, plan_name, pending_plan_name, pending_plan_effective_at, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, NULL, NULL, $7)
            ON CONFLICT(phone) DO UPDATE SET
                name=excluded.name,
                platform_name=excluded.platform_name,
                zone_pincode=excluded.zone_pincode,
                zone_name=excluded.zone_name,
                plan_name=excluded.plan_name,
                pending_plan_name=NULL,
                pending_plan_effective_at=NULL
            """,
            phone,
            name,
            platform_name,
            zone_pincode,
            zone_name,
            plan_name,
            _utc_now_iso(),
        )


async def get_worker(phone: str) -> Optional[Dict[str, Any]]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM workers WHERE phone = $1", phone)
    out = _row_to_dict(row)
    if out is None:
        return None
    out["created_at"] = _to_iso(out["created_at"])
    if out.get("pending_plan_effective_at") is not None:
        out["pending_plan_effective_at"] = _to_iso(out["pending_plan_effective_at"])
    return out


async def update_worker_plan(phone: str, plan_name: str) -> None:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE workers SET plan_name = $1, pending_plan_name = NULL, pending_plan_effective_at = NULL WHERE phone = $2",
            plan_name,
            phone,
        )


async def set_pending_worker_plan(phone: str, plan_name: str, effective_at: datetime) -> None:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE workers SET pending_plan_name = $1, pending_plan_effective_at = $2 WHERE phone = $3",
            plan_name,
            effective_at,
            phone,
        )


async def apply_due_pending_worker_plan(phone: str, now: Optional[datetime] = None) -> bool:
    now_utc = now or _utc_now_iso()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT pending_plan_name, pending_plan_effective_at FROM workers WHERE phone = $1",
            phone,
        )
        if not row:
            return False

        pending_name = row["pending_plan_name"]
        pending_effective_at = row["pending_plan_effective_at"]
        if not pending_name or pending_effective_at is None:
            return False

        if pending_effective_at <= now_utc:
            await conn.execute(
                """
                UPDATE workers
                SET plan_name = pending_plan_name,
                    pending_plan_name = NULL,
                    pending_plan_effective_at = NULL
                WHERE phone = $1
                """,
                phone,
            )
            return True

    return False


async def list_workers_by_zone(zone_pincode: str) -> list[Dict[str, Any]]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM workers WHERE zone_pincode = $1", zone_pincode)
    out = _rows_to_dicts(rows)
    for item in out:
        item["created_at"] = _to_iso(item["created_at"])
    return out


async def upsert_worker_location_signal(
    *,
    phone: str,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    accuracy_meters: Optional[float] = None,
    captured_at: Optional[str | datetime] = None,
    tower_metadata: Optional[Dict[str, Any]] = None,
    motion_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    now = _utc_now_iso()
    captured_at_value: Optional[datetime]
    if captured_at is None:
        captured_at_value = None
    elif isinstance(captured_at, str):
        captured_at_value = datetime.fromisoformat(captured_at)
    else:
        captured_at_value = captured_at
    tower_payload = json.dumps(tower_metadata) if tower_metadata is not None else None
    motion_payload = json.dumps(motion_metadata) if motion_metadata is not None else None
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO worker_location_signals (
                phone,
                latitude,
                longitude,
                accuracy_meters,
                captured_at,
                tower_metadata_json,
                motion_metadata_json,
                received_at
            )
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8)
            ON CONFLICT(phone) DO UPDATE SET
                latitude = excluded.latitude,
                longitude = excluded.longitude,
                accuracy_meters = excluded.accuracy_meters,
                captured_at = excluded.captured_at,
                tower_metadata_json = excluded.tower_metadata_json,
                motion_metadata_json = excluded.motion_metadata_json,
                received_at = excluded.received_at
            """,
            phone,
            latitude,
            longitude,
            accuracy_meters,
            captured_at_value,
            tower_payload,
            motion_payload,
            now,
        )
    return {
        "phone": phone,
        "latitude": latitude,
        "longitude": longitude,
        "accuracy_meters": accuracy_meters,
        "captured_at": _to_iso(captured_at_value) if captured_at_value is not None else None,
        "tower_metadata_json": tower_metadata,
        "motion_metadata_json": motion_metadata,
        "received_at": _to_iso(now),
    }


async def get_worker_location_signal(phone: str) -> Optional[Dict[str, Any]]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM worker_location_signals WHERE phone = $1", phone)
    out = _row_to_dict(row)
    if out is None:
        return None
    if out.get("captured_at") is not None:
        out["captured_at"] = _to_iso(out["captured_at"])
    out["received_at"] = _to_iso(out["received_at"])
    return out


async def purge_stale_worker_location_signals(*, retention_days: int) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, int(retention_days)))
    pool = await _get_pool()
    async with pool.acquire() as conn:
        deleted = await conn.execute("DELETE FROM worker_location_signals WHERE received_at < $1", cutoff)
    # asyncpg returns "DELETE <count>"
    parts = deleted.split()
    if len(parts) == 2 and parts[1].isdigit():
        return int(parts[1])
    return 0


async def create_claim(
    *,
    phone: str,
    claim_type: str,
    status: str,
    amount: float,
    description: str,
    zone_pincode: str,
    source: str,
    anomaly_score: Optional[float] = None,
    anomaly_threshold: Optional[float] = None,
    anomaly_flagged: Optional[bool] = None,
    anomaly_model_version: Optional[str] = None,
    anomaly_features: Optional[Dict[str, Any]] = None,
    anomaly_scored_at: Optional[str | datetime] = None,
    llm_review_used: Optional[bool] = None,
    llm_review_status: Optional[str] = None,
    llm_provider: Optional[str] = None,
    llm_model: Optional[str] = None,
    llm_fallback_used: Optional[bool] = None,
    llm_decision_confidence: Optional[float] = None,
    llm_decision_json: Optional[Dict[str, Any]] = None,
    llm_attempts: Optional[List[Dict[str, Any]]] = None,
    llm_validation_error: Optional[str] = None,
    llm_scored_at: Optional[str | datetime] = None,
) -> Dict[str, Any]:
    now = _utc_now_iso()
    anomaly_scored_at_value: Optional[datetime]
    if anomaly_scored_at is None:
        anomaly_scored_at_value = now if anomaly_score is not None else None
    elif isinstance(anomaly_scored_at, str):
        anomaly_scored_at_value = datetime.fromisoformat(anomaly_scored_at)
    else:
        anomaly_scored_at_value = anomaly_scored_at
    llm_scored_at_value: Optional[datetime]
    if llm_scored_at is None:
        llm_scored_at_value = now if llm_review_used else None
    elif isinstance(llm_scored_at, str):
        llm_scored_at_value = datetime.fromisoformat(llm_scored_at)
    else:
        llm_scored_at_value = llm_scored_at
    anomaly_features_payload = json.dumps(anomaly_features) if anomaly_features is not None else None
    llm_decision_payload = json.dumps(llm_decision_json) if llm_decision_json is not None else None
    llm_attempts_payload = json.dumps(llm_attempts) if llm_attempts is not None else None

    pool = await _get_pool()
    async with pool.acquire() as conn:
        claim_id = await conn.fetchval(
            """
            INSERT INTO claims (
                phone,
                claim_type,
                status,
                amount,
                description,
                zone_pincode,
                source,
                created_at,
                anomaly_score,
                anomaly_threshold,
                anomaly_flagged,
                anomaly_model_version,
                anomaly_features_json,
                anomaly_scored_at,
                llm_review_used,
                llm_review_status,
                llm_provider,
                llm_model,
                llm_fallback_used,
                llm_decision_confidence,
                llm_decision_json,
                llm_attempts_json,
                llm_validation_error,
                llm_scored_at
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8,
                $9, $10, $11, $12, $13::jsonb, $14,
                $15, $16, $17, $18, $19, $20, $21::jsonb, $22::jsonb, $23, $24
            )
            RETURNING id
            """,
            phone,
            claim_type,
            status,
            amount,
            description,
            zone_pincode,
            source,
            now,
            anomaly_score,
            anomaly_threshold,
            anomaly_flagged,
            anomaly_model_version,
            anomaly_features_payload,
            anomaly_scored_at_value,
            llm_review_used,
            llm_review_status,
            llm_provider,
            llm_model,
            llm_fallback_used,
            llm_decision_confidence,
            llm_decision_payload,
            llm_attempts_payload,
            llm_validation_error,
            llm_scored_at_value,
        )

    return {
        "id": int(claim_id),
        "phone": phone,
        "claim_type": claim_type,
        "status": status,
        "amount": float(amount),
        "description": description,
        "zone_pincode": zone_pincode,
        "source": source,
        "created_at": _to_iso(now),
        "anomaly_score": anomaly_score,
        "anomaly_threshold": anomaly_threshold,
        "anomaly_flagged": anomaly_flagged,
        "anomaly_model_version": anomaly_model_version,
        "anomaly_features_json": anomaly_features,
        "anomaly_scored_at": _to_iso(anomaly_scored_at_value) if anomaly_scored_at_value is not None else None,
        "llm_review_used": llm_review_used,
        "llm_review_status": llm_review_status,
        "llm_provider": llm_provider,
        "llm_model": llm_model,
        "llm_fallback_used": llm_fallback_used,
        "llm_decision_confidence": llm_decision_confidence,
        "llm_decision_json": llm_decision_json,
        "llm_attempts_json": llm_attempts,
        "llm_validation_error": llm_validation_error,
        "llm_scored_at": _to_iso(llm_scored_at_value) if llm_scored_at_value is not None else None,
    }


async def list_claims_for_phone(phone: str) -> list[Dict[str, Any]]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM claims WHERE phone = $1 ORDER BY created_at DESC",
            phone,
        )
    out = _rows_to_dicts(rows)
    for item in out:
        item["created_at"] = _to_iso(item["created_at"])
    return out


async def total_settled_amount_for_phone(phone: str) -> float:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        value = await conn.fetchval(
            "SELECT COALESCE(SUM(amount), 0) FROM claims WHERE phone = $1 AND status = 'settled'",
            phone,
        )
    return float(value or 0)


async def count_claims_for_phone_since(phone: str, since: datetime) -> int:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        value = await conn.fetchval(
            "SELECT COUNT(*) FROM claims WHERE phone = $1 AND created_at >= $2",
            phone,
            since,
        )
    return int(value or 0)


async def has_recent_auto_claim(phone: str, claim_type: str, within_minutes: int = 360) -> bool:
    cutoff = datetime.now(timezone.utc).timestamp() - (within_minutes * 60)
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT created_at
            FROM claims
            WHERE phone = $1 AND claim_type = $2 AND source = 'auto'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            phone,
            claim_type,
        )

    if not row:
        return False
    created_at = row["created_at"]
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at)
    return created_at.timestamp() >= cutoff


async def create_zonelock_report(
    *,
    phone: str,
    zone_pincode: str,
    zone_name: str,
    description: str,
) -> Dict[str, Any]:
    """Create a ZoneLock manual report from worker."""
    now = _utc_now_iso()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        report_id = await conn.fetchval(
            """
            INSERT INTO zonelock_reports (phone, zone_pincode, zone_name, description, status, confidence, verified_count, created_at)
            VALUES ($1, $2, $3, $4, 'pending', 0.4, 1, $5)
            RETURNING id
            """,
            phone,
            zone_pincode,
            zone_name,
            description,
            now,
        )

    return {
        "id": int(report_id),
        "phone": phone,
        "zone_pincode": zone_pincode,
        "zone_name": zone_name,
        "description": description,
        "status": "pending",
        "confidence": 0.4,
        "verified_count": 1,
        "created_at": _to_iso(now),
    }


async def get_zonelock_report(report_id: int) -> Optional[Dict[str, Any]]:
    """Get a ZoneLock report by ID."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM zonelock_reports WHERE id = $1", report_id)
    out = _row_to_dict(row)
    if out is None:
        return None
    out["created_at"] = _to_iso(out["created_at"])
    return out


async def list_zonelock_reports_for_zone(zone_pincode: str, status: Optional[str] = None) -> list[Dict[str, Any]]:
    """List ZoneLock reports for a zone."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        if status:
            rows = await conn.fetch(
                """
                SELECT * FROM zonelock_reports
                WHERE zone_pincode = $1 AND status = $2
                ORDER BY created_at DESC
                """,
                zone_pincode,
                status,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT * FROM zonelock_reports
                WHERE zone_pincode = $1
                ORDER BY created_at DESC
                """,
                zone_pincode,
            )
    out = _rows_to_dicts(rows)
    for item in out:
        item["created_at"] = _to_iso(item["created_at"])
    return out


async def increment_zonelock_report_verification(report_id: int) -> None:
    """Increment verification count for a ZoneLock report."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE zonelock_reports
            SET verified_count = verified_count + 1,
                confidence = MIN(0.95, 0.4 + (verified_count + 1) * 0.2),
                status = CASE WHEN (verified_count + 1) >= 2 THEN 'auto_confirmed' ELSE status END
            WHERE id = $1
            """,
            report_id,
        )


async def update_zonelock_report_status(report_id: int, status: str, review_notes: Optional[str] = None) -> None:
    """Update ZoneLock report status after manual review."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE zonelock_reports SET status = $1 WHERE id = $2", status, report_id)


async def escalate_claim(
    *,
    claim_id: int,
    phone: str,
    reason: str,
) -> Dict[str, Any]:
    """Create a claim escalation record."""
    now = _utc_now_iso()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            escalation_id = await conn.fetchval(
                """
                INSERT INTO claim_escalations (claim_id, phone, reason, status, created_at)
                VALUES ($1, $2, $3, 'pending_review', $4)
                RETURNING id
                """,
                claim_id,
                phone,
                reason,
                now,
            )
            # Update claim status to reflect escalation
            await conn.execute(
                "UPDATE claims SET status = 'escalated' WHERE id = $1",
                claim_id,
            )

    return {
        "id": int(escalation_id),
        "claim_id": claim_id,
        "phone": phone,
        "reason": reason,
        "status": "pending_review",
        "created_at": _to_iso(now),
    }


async def get_claim_escalation(escalation_id: int) -> Optional[Dict[str, Any]]:
    """Get a claim escalation by ID."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM claim_escalations WHERE id = $1", escalation_id)
    out = _row_to_dict(row)
    if out is None:
        return None
    out["created_at"] = _to_iso(out["created_at"])
    return out


async def list_claim_escalations_for_phone(phone: str) -> list[Dict[str, Any]]:
    """List claim escalations for a phone."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM claim_escalations
            WHERE phone = $1
            ORDER BY created_at DESC
            """,
            phone,
        )
    out = _rows_to_dicts(rows)
    for item in out:
        item["created_at"] = _to_iso(item["created_at"])
    return out


async def update_escalation_status(escalation_id: int, status: str, review_notes: Optional[str] = None) -> None:
    """Update claim escalation status after human review."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE claim_escalations
            SET status = $1, review_notes = $2
            WHERE id = $3
            """,
            status,
            review_notes,
            escalation_id,
        )


async def list_claim_events_since(since: datetime) -> list[Dict[str, Any]]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, phone, claim_type, status, amount, zone_pincode, source, created_at
            FROM claims
            WHERE created_at >= $1
            ORDER BY created_at ASC
            """,
            since,
        )
    out = _rows_to_dicts(rows)
    for item in out:
        item["created_at"] = _to_iso(item["created_at"])
    return out


async def create_fraud_cluster_run(
    *,
    lookback_days: int,
    time_bucket_minutes: int,
    min_edge_support: int,
    medium_risk_threshold: float,
    high_risk_threshold: float,
) -> Dict[str, Any]:
    now = _utc_now_iso()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        run_id = await conn.fetchval(
            """
            INSERT INTO fraud_cluster_runs (
                started_at,
                status,
                lookback_days,
                time_bucket_minutes,
                min_edge_support,
                medium_risk_threshold,
                high_risk_threshold,
                claims_scanned,
                edge_count,
                cluster_count,
                flagged_cluster_count,
                created_at
            )
            VALUES ($1, 'running', $2, $3, $4, $5, $6, 0, 0, 0, 0, $1)
            RETURNING id
            """,
            now,
            int(lookback_days),
            int(time_bucket_minutes),
            int(min_edge_support),
            float(medium_risk_threshold),
            float(high_risk_threshold),
        )
    return {
        "id": int(run_id),
        "started_at": _to_iso(now),
        "status": "running",
    }


async def finalize_fraud_cluster_run(
    run_id: int,
    *,
    status: str,
    claims_scanned: int,
    edge_count: int,
    cluster_count: int,
    flagged_cluster_count: int,
    error_message: Optional[str] = None,
) -> None:
    now = _utc_now_iso()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE fraud_cluster_runs
            SET finished_at = $1,
                status = $2,
                claims_scanned = $3,
                edge_count = $4,
                cluster_count = $5,
                flagged_cluster_count = $6,
                error_message = $7
            WHERE id = $8
            """,
            now,
            status,
            int(claims_scanned),
            int(edge_count),
            int(cluster_count),
            int(flagged_cluster_count),
            error_message,
            int(run_id),
        )


async def save_fraud_co_claim_clusters(run_id: int, clusters: List[Dict[str, Any]]) -> int:
    now = _utc_now_iso()
    pool = await _get_pool()
    persisted = 0
    async with pool.acquire() as conn:
        async with conn.transaction():
            for cluster in clusters:
                cluster_id = await conn.fetchval(
                    """
                    INSERT INTO fraud_co_claim_clusters (
                        run_id,
                        cluster_key,
                        risk_score,
                        risk_level,
                        member_count,
                        edge_count,
                        event_count,
                        frequency_score,
                        recency_score,
                        supporting_metadata_json,
                        created_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11)
                    RETURNING id
                    """,
                    int(run_id),
                    str(cluster.get("cluster_key", "")),
                    float(cluster.get("risk_score", 0.0)),
                    str(cluster.get("risk_level", "low")),
                    int(cluster.get("member_count", 0)),
                    int(cluster.get("edge_count", 0)),
                    int(cluster.get("event_count", 0)),
                    float(cluster.get("frequency_score", 0.0)),
                    float(cluster.get("recency_score", 0.0)),
                    json.dumps(cluster.get("supporting_metadata", {})),
                    now,
                )

                members = cluster.get("members", [])
                if isinstance(members, list):
                    for member in members:
                        first_claim_at = member.get("first_claim_at")
                        last_claim_at = member.get("last_claim_at")
                        first_claim_at_value = (
                            datetime.fromisoformat(first_claim_at)
                            if isinstance(first_claim_at, str) and first_claim_at
                            else None
                        )
                        last_claim_at_value = (
                            datetime.fromisoformat(last_claim_at)
                            if isinstance(last_claim_at, str) and last_claim_at
                            else None
                        )
                        await conn.execute(
                            """
                            INSERT INTO fraud_co_claim_cluster_members (
                                cluster_id,
                                phone,
                                claim_count,
                                first_claim_at,
                                last_claim_at,
                                created_at
                            )
                            VALUES ($1, $2, $3, $4, $5, $6)
                            """,
                            int(cluster_id),
                            str(member.get("phone", "")),
                            int(member.get("claim_count", 0)),
                            first_claim_at_value,
                            last_claim_at_value,
                            now,
                        )

                edges = cluster.get("edges", [])
                if isinstance(edges, list):
                    for edge in edges:
                        last_co_claim_at = edge.get("last_co_claim_at")
                        last_co_claim_at_value = (
                            datetime.fromisoformat(last_co_claim_at)
                            if isinstance(last_co_claim_at, str) and last_co_claim_at
                            else None
                        )
                        await conn.execute(
                            """
                            INSERT INTO fraud_co_claim_cluster_edges (
                                cluster_id,
                                phone_a,
                                phone_b,
                                co_claim_count,
                                recency_weight,
                                edge_weight,
                                last_co_claim_at,
                                supporting_metadata_json,
                                created_at
                            )
                            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9)
                            """,
                            int(cluster_id),
                            str(edge.get("phone_a", "")),
                            str(edge.get("phone_b", "")),
                            int(edge.get("co_claim_count", 0)),
                            float(edge.get("recency_weight", 0.0)),
                            float(edge.get("edge_weight", 0.0)),
                            last_co_claim_at_value,
                            json.dumps(edge.get("supporting_metadata", {})),
                            now,
                        )
                persisted += 1
    return persisted


async def list_fraud_cluster_runs(limit: int = 20) -> list[Dict[str, Any]]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT *
            FROM fraud_cluster_runs
            ORDER BY created_at DESC
            LIMIT $1
            """,
            max(1, int(limit)),
        )
    out = _rows_to_dicts(rows)
    for item in out:
        item["created_at"] = _to_iso(item["created_at"])
        item["started_at"] = _to_iso(item["started_at"])
        if item.get("finished_at") is not None:
            item["finished_at"] = _to_iso(item["finished_at"])
    return out


async def get_latest_fraud_cluster_run() -> Optional[Dict[str, Any]]:
    rows = await list_fraud_cluster_runs(limit=1)
    if not rows:
        return None
    return rows[0]


async def list_fraud_clusters(
    *,
    run_id: Optional[int] = None,
    risk_level: Optional[str] = None,
    flagged_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[Dict[str, Any]]:
    query = """
        SELECT *
        FROM fraud_co_claim_clusters
        WHERE 1 = 1
    """
    params: list[Any] = []
    if run_id is not None:
        params.append(int(run_id))
        query += f" AND run_id = ${len(params)}"
    if risk_level:
        params.append(risk_level.strip().lower())
        query += f" AND LOWER(risk_level) = ${len(params)}"
    if flagged_only:
        query += " AND LOWER(risk_level) IN ('medium', 'high')"

    params.append(max(1, int(limit)))
    query += f" ORDER BY risk_score DESC, id DESC LIMIT ${len(params)}"
    params.append(max(0, int(offset)))
    query += f" OFFSET ${len(params)}"

    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)

    out = _rows_to_dicts(rows)
    for item in out:
        item["created_at"] = _to_iso(item["created_at"])
    return out


async def get_fraud_cluster(cluster_id: int) -> Optional[Dict[str, Any]]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM fraud_co_claim_clusters WHERE id = $1", int(cluster_id))
    out = _row_to_dict(row)
    if out is None:
        return None
    out["created_at"] = _to_iso(out["created_at"])
    return out


async def list_fraud_cluster_members(cluster_id: int) -> list[Dict[str, Any]]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT *
            FROM fraud_co_claim_cluster_members
            WHERE cluster_id = $1
            ORDER BY claim_count DESC, phone ASC
            """,
            int(cluster_id),
        )
    out = _rows_to_dicts(rows)
    for item in out:
        item["created_at"] = _to_iso(item["created_at"])
        if item.get("first_claim_at") is not None:
            item["first_claim_at"] = _to_iso(item["first_claim_at"])
        if item.get("last_claim_at") is not None:
            item["last_claim_at"] = _to_iso(item["last_claim_at"])
    return out


async def list_fraud_cluster_edges(cluster_id: int, limit: int = 200) -> list[Dict[str, Any]]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT *
            FROM fraud_co_claim_cluster_edges
            WHERE cluster_id = $1
            ORDER BY edge_weight DESC, co_claim_count DESC
            LIMIT $2
            """,
            int(cluster_id),
            max(1, int(limit)),
        )
    out = _rows_to_dicts(rows)
    for item in out:
        item["created_at"] = _to_iso(item["created_at"])
        if item.get("last_co_claim_at") is not None:
            item["last_co_claim_at"] = _to_iso(item["last_co_claim_at"])
    return out
