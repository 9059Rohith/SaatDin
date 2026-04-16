from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from jwt import InvalidTokenError
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field

from ..core.config import settings
from ..core.db import (
    _get_pool,
    update_escalation_status,
    update_zonelock_report_status,
)
from ..core.zone_cache import load_zone_map
from ..models.schemas import ApiResponse

router = APIRouter(tags=["admin"])

ADMIN_SESSION_COOKIE = "saatdin_admin_session"
ALLOWED_CLAIM_STATUSES = {"pending", "in_review", "settled", "rejected", "escalated"}
ALLOWED_ESCALATION_STATUSES = {"pending_review", "approved", "rejected"}
ALLOWED_REPORT_STATUSES = {"pending", "auto_confirmed", "approved", "rejected"}


class AdminLoginRequest(BaseModel):
    password: str = Field(min_length=1)


class AdminStatusUpdateRequest(BaseModel):
    status: str = Field(min_length=3, max_length=50)


class AdminEscalationReviewRequest(BaseModel):
    status: str = Field(min_length=3, max_length=50)
    reviewNotes: str | None = Field(default=None, max_length=1000)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _token_expiry() -> datetime:
    return _utc_now() + timedelta(minutes=settings.admin_session_minutes)


def _create_admin_token() -> str:
    payload = {
        "sub": settings.admin_username,
        "role": "admin",
        "iat": int(_utc_now().timestamp()),
        "exp": int(_token_expiry().timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _decode_admin_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin session") from exc

    if payload.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin session")
    return payload


def _get_session_token(request: Request) -> str | None:
    cookie_token = request.cookies.get(ADMIN_SESSION_COOKIE)
    if cookie_token:
        return cookie_token

    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return None


def _require_admin(request: Request) -> dict[str, Any]:
    token = _get_session_token(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin session required")
    return _decode_admin_token(token)


def _build_filter_clause(filters: list[tuple[str, Any]]) -> tuple[str, list[Any]]:
    if not filters:
        return "", []

    clauses: list[str] = []
    params: list[Any] = []
    for template, value in filters:
        params.append(value)
        clauses.append(template.format(param=f"${len(params)}"))
    return " WHERE " + " AND ".join(clauses), params


def _safe_limit(value: int | None, default: int = 50, maximum: int = 200) -> int:
    if value is None:
        return default
    return max(1, min(int(value), maximum))


def _safe_offset(value: int | None) -> int:
    if value is None:
        return 0
    return max(0, int(value))


def _to_iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _claim_ref(claim_id: int) -> str:
    return f"#C{claim_id:05d}"


def _escalation_ref(escalation_id: int) -> str:
    return f"#E{escalation_id:05d}"


def _report_ref(report_id: int) -> str:
    return f"#Z{report_id:05d}"


async def _fetch_rows(sql: str, params: list[Any]) -> list[dict[str, Any]]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return [dict(row) for row in rows]


async def _fetch_row(sql: str, params: list[Any]) -> dict[str, Any] | None:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, *params)
    return dict(row) if row else None


async def _fetch_value(sql: str, params: list[Any]) -> Any:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(sql, *params)


def _format_worker(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "phone": str(row["phone"]),
        "name": str(row["name"]),
        "platform": str(row["platform_name"]),
        "zonePincode": str(row["zone_pincode"]),
        "zone": str(row["zone_name"]),
        "plan": str(row["plan_name"]),
        "pendingPlan": row.get("pending_plan_name"),
        "pendingEffectiveAt": _to_iso(row.get("pending_plan_effective_at")),
        "createdAt": _to_iso(row.get("created_at")),
    }


def _format_claim(row: dict[str, Any]) -> dict[str, Any]:
    claim_id = int(row["id"])
    return {
        "id": claim_id,
        "claimRef": _claim_ref(claim_id),
        "phone": str(row["phone"]),
        "workerName": row.get("worker_name"),
        "workerZone": row.get("worker_zone_name"),
        "workerPlatform": row.get("worker_platform_name"),
        "claimType": str(row["claim_type"]),
        "status": str(row["status"]),
        "amount": float(row["amount"]),
        "description": str(row["description"]),
        "zonePincode": str(row["zone_pincode"]),
        "source": str(row["source"]),
        "createdAt": _to_iso(row.get("created_at")),
    }


def _format_escalation(row: dict[str, Any]) -> dict[str, Any]:
    escalation_id = int(row["id"])
    return {
        "id": escalation_id,
        "escalationRef": _escalation_ref(escalation_id),
        "claimId": int(row["claim_id"]),
        "claimRef": _claim_ref(int(row["claim_id"])),
        "phone": str(row["phone"]),
        "workerName": row.get("worker_name"),
        "workerZone": row.get("worker_zone_name"),
        "workerPlatform": row.get("worker_platform_name"),
        "claimType": row.get("claim_type"),
        "claimStatus": row.get("claim_status"),
        "amount": float(row["amount"]),
        "reason": str(row["reason"]),
        "status": str(row["status"]),
        "reviewNotes": row.get("review_notes"),
        "zonePincode": row.get("zone_pincode"),
        "source": row.get("source"),
        "createdAt": _to_iso(row.get("created_at")),
    }


def _format_report(row: dict[str, Any]) -> dict[str, Any]:
    report_id = int(row["id"])
    confidence_raw = row.get("confidence")
    verified_count_raw = row.get("verified_count")

    try:
        confidence_value = float(confidence_raw) if confidence_raw is not None else 0.0
    except (TypeError, ValueError):
        confidence_value = 0.0

    try:
        verified_count_value = int(verified_count_raw) if verified_count_raw is not None else 0
    except (TypeError, ValueError):
        verified_count_value = 0

    return {
        "id": report_id,
        "reportRef": _report_ref(report_id),
        "phone": str(row["phone"]),
        "workerName": row.get("worker_name"),
        "workerPlatform": row.get("worker_platform_name"),
        "zonePincode": str(row["zone_pincode"]),
        "zoneName": str(row["zone_name"]),
        "description": str(row["description"]),
        "status": str(row["status"]),
        "confidence": confidence_value,
        "verifiedCount": verified_count_value,
        "createdAt": _to_iso(row.get("created_at")),
    }


@router.post("/auth/login", response_model=ApiResponse)
async def login(payload: AdminLoginRequest, response: Response) -> ApiResponse:
    if payload.password != settings.admin_password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin password")

    token = _create_admin_token()
    response.set_cookie(
        key=ADMIN_SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=settings.admin_session_minutes * 60,
        path="/",
    )
    return ApiResponse(success=True, data={"authenticated": True, "username": settings.admin_username}, message="Admin signed in")


@router.post("/auth/logout", response_model=ApiResponse)
async def logout(response: Response) -> ApiResponse:
    response.delete_cookie(ADMIN_SESSION_COOKIE, path="/")
    return ApiResponse(success=True, data={"authenticated": False}, message="Admin signed out")


@router.get("/session", response_model=ApiResponse)
async def session(request: Request) -> ApiResponse:
    token = _get_session_token(request)
    if not token:
        return ApiResponse(success=True, data={"authenticated": False})

    payload = _decode_admin_token(token)
    return ApiResponse(
        success=True,
        data={"authenticated": True, "username": payload.get("sub", settings.admin_username)},
    )


@router.get("/overview", response_model=ApiResponse)
async def overview(_admin: dict[str, Any] = Depends(_require_admin)) -> ApiResponse:
    zones = load_zone_map()
    totals = {
        "zones": len(zones),
        "workers": int(await _fetch_value("SELECT COUNT(*) FROM workers", [] ) or 0),
        "claims": int(await _fetch_value("SELECT COUNT(*) FROM claims", []) or 0),
        "settledClaims": int(
            await _fetch_value("SELECT COUNT(*) FROM claims WHERE status = 'settled'", []) or 0
        ),
        "pendingEscalations": int(
            await _fetch_value("SELECT COUNT(*) FROM claim_escalations WHERE status = 'pending_review'", []) or 0
        ),
        "pendingZoneLockReports": int(
            await _fetch_value("SELECT COUNT(*) FROM zonelock_reports WHERE status = 'pending'", []) or 0
        ),
        "totalSettledAmount": float(
            await _fetch_value("SELECT COALESCE(SUM(amount), 0) FROM claims WHERE status = 'settled'", []) or 0
        ),
        "pendingPlanChanges": int(
            await _fetch_value("SELECT COUNT(*) FROM workers WHERE pending_plan_name IS NOT NULL", []) or 0
        ),
    }

    claim_status_rows = await _fetch_rows(
        "SELECT status, COUNT(*) AS total FROM claims GROUP BY status ORDER BY status",
        [],
    )
    escalation_status_rows = await _fetch_rows(
        "SELECT status, COUNT(*) AS total FROM claim_escalations GROUP BY status ORDER BY status",
        [],
    )
    report_status_rows = await _fetch_rows(
        "SELECT status, COUNT(*) AS total FROM zonelock_reports GROUP BY status ORDER BY status",
        [],
    )

    return ApiResponse(
        success=True,
        data={
            "totals": totals,
            "claimStatusCounts": {str(row["status"]): int(row["total"]) for row in claim_status_rows},
            "escalationStatusCounts": {str(row["status"]): int(row["total"]) for row in escalation_status_rows},
            "reportStatusCounts": {str(row["status"]): int(row["total"]) for row in report_status_rows},
        },
    )


@router.get("/workers", response_model=ApiResponse)
async def workers(
    search: str | None = Query(default=None),
    zone: str | None = Query(default=None),
    platform: str | None = Query(default=None),
    limit: int | None = Query(default=50, ge=1, le=200),
    offset: int | None = Query(default=0, ge=0),
    _admin: dict[str, Any] = Depends(_require_admin),
) -> ApiResponse:
    filters: list[tuple[str, Any]] = []
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        filters.append(("(phone ILIKE {param} OR name ILIKE {param} OR zone_name ILIKE {param} OR platform_name ILIKE {param} OR plan_name ILIKE {param})", pattern))
    if zone and zone.strip():
        filters.append(("(zone_name ILIKE {param} OR zone_pincode ILIKE {param})", f"%{zone.strip()}%"))
    if platform and platform.strip():
        filters.append(("platform_name ILIKE {param}", f"%{platform.strip()}%"))

    where_sql, params = _build_filter_clause(filters)
    limit_value = _safe_limit(limit)
    offset_value = _safe_offset(offset)
    params.extend([limit_value, offset_value])
    sql = (
        "SELECT phone, name, platform_name, zone_pincode, zone_name, plan_name, pending_plan_name, "
        "pending_plan_effective_at, created_at FROM workers"
        f"{where_sql} ORDER BY created_at DESC LIMIT ${len(params) - 1} OFFSET ${len(params)}"
    )

    rows = await _fetch_rows(sql, params)
    return ApiResponse(success=True, data={"items": [_format_worker(row) for row in rows]})


@router.get("/claims", response_model=ApiResponse)
async def claims(
    search: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    claim_type: str | None = Query(default=None, alias="claimType"),
    source: str | None = Query(default=None),
    zone: str | None = Query(default=None),
    limit: int | None = Query(default=50, ge=1, le=200),
    offset: int | None = Query(default=0, ge=0),
    _admin: dict[str, Any] = Depends(_require_admin),
) -> ApiResponse:
    filters: list[tuple[str, Any]] = []
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        filters.append(("(c.phone ILIKE {param} OR c.claim_type ILIKE {param} OR c.status ILIKE {param} OR c.description ILIKE {param} OR c.zone_pincode ILIKE {param} OR w.name ILIKE {param})", pattern))
    if status_filter and status_filter.strip():
        filters.append(("c.status ILIKE {param}", f"%{status_filter.strip()}%"))
    if claim_type and claim_type.strip():
        filters.append(("c.claim_type ILIKE {param}", f"%{claim_type.strip()}%"))
    if source and source.strip():
        filters.append(("c.source ILIKE {param}", f"%{source.strip()}%"))
    if zone and zone.strip():
        filters.append(("(c.zone_pincode ILIKE {param} OR w.zone_name ILIKE {param})", f"%{zone.strip()}%"))

    where_sql, params = _build_filter_clause(filters)
    limit_value = _safe_limit(limit)
    offset_value = _safe_offset(offset)
    params.extend([limit_value, offset_value])
    sql = (
        "SELECT c.*, w.name AS worker_name, w.zone_name AS worker_zone_name, w.platform_name AS worker_platform_name "
        "FROM claims c LEFT JOIN workers w ON w.phone = c.phone"
        f"{where_sql} ORDER BY c.created_at DESC LIMIT ${len(params) - 1} OFFSET ${len(params)}"
    )

    rows = await _fetch_rows(sql, params)
    return ApiResponse(success=True, data={"items": [_format_claim(row) for row in rows]})


@router.get("/escalations", response_model=ApiResponse)
async def escalations(
    search: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int | None = Query(default=50, ge=1, le=200),
    offset: int | None = Query(default=0, ge=0),
    _admin: dict[str, Any] = Depends(_require_admin),
) -> ApiResponse:
    filters: list[tuple[str, Any]] = []
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        filters.append(("(e.phone ILIKE {param} OR e.reason ILIKE {param} OR c.claim_type ILIKE {param} OR w.name ILIKE {param})", pattern))
    if status_filter and status_filter.strip():
        filters.append(("e.status ILIKE {param}", f"%{status_filter.strip()}%"))

    where_sql, params = _build_filter_clause(filters)
    limit_value = _safe_limit(limit)
    offset_value = _safe_offset(offset)
    params.extend([limit_value, offset_value])
    sql = (
        "SELECT e.*, c.claim_type, c.status AS claim_status, c.amount, c.zone_pincode, c.source, "
        "w.name AS worker_name, w.zone_name AS worker_zone_name, w.platform_name AS worker_platform_name "
        "FROM claim_escalations e "
        "LEFT JOIN claims c ON c.id = e.claim_id "
        "LEFT JOIN workers w ON w.phone = e.phone"
        f"{where_sql} ORDER BY e.created_at DESC LIMIT ${len(params) - 1} OFFSET ${len(params)}"
    )

    rows = await _fetch_rows(sql, params)
    return ApiResponse(success=True, data={"items": [_format_escalation(row) for row in rows]})


@router.get("/zonelock-reports", response_model=ApiResponse)
async def zonelock_reports(
    search: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    zone: str | None = Query(default=None),
    limit: int | None = Query(default=50, ge=1, le=200),
    offset: int | None = Query(default=0, ge=0),
    _admin: dict[str, Any] = Depends(_require_admin),
) -> ApiResponse:
    filters: list[tuple[str, Any]] = []
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        filters.append(("(r.phone ILIKE {param} OR r.description ILIKE {param} OR r.zone_name ILIKE {param} OR w.name ILIKE {param})", pattern))
    if status_filter and status_filter.strip():
        filters.append(("r.status ILIKE {param}", f"%{status_filter.strip()}%"))
    if zone and zone.strip():
        filters.append(("(r.zone_pincode ILIKE {param} OR r.zone_name ILIKE {param})", f"%{zone.strip()}%"))

    where_sql, params = _build_filter_clause(filters)
    limit_value = _safe_limit(limit)
    offset_value = _safe_offset(offset)
    params.extend([limit_value, offset_value])
    sql = (
        "SELECT r.*, w.name AS worker_name, w.platform_name AS worker_platform_name "
        "FROM zonelock_reports r LEFT JOIN workers w ON w.phone = r.phone"
        f"{where_sql} ORDER BY r.created_at DESC LIMIT ${len(params) - 1} OFFSET ${len(params)}"
    )

    rows = await _fetch_rows(sql, params)
    return ApiResponse(success=True, data={"items": [_format_report(row) for row in rows]})


@router.post("/claims/{claim_id}/status", response_model=ApiResponse)
async def update_claim_status(
    claim_id: int,
    payload: AdminStatusUpdateRequest,
    _admin: dict[str, Any] = Depends(_require_admin),
) -> ApiResponse:
    status_value = payload.status.strip().lower()
    if status_value not in ALLOWED_CLAIM_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported claim status")

    row = await _fetch_row("SELECT * FROM claims WHERE id = $1", [claim_id])
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")

    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE claims SET status = $1 WHERE id = $2", status_value, claim_id)

    row["status"] = status_value
    return ApiResponse(success=True, data=_format_claim(row), message="Claim status updated")


@router.post("/escalations/{escalation_id}/review", response_model=ApiResponse)
async def review_escalation(
    escalation_id: int,
    payload: AdminEscalationReviewRequest,
    _admin: dict[str, Any] = Depends(_require_admin),
) -> ApiResponse:
    status_value = payload.status.strip().lower()
    if status_value not in ALLOWED_ESCALATION_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported escalation status")

    row = await _fetch_row("SELECT * FROM claim_escalations WHERE id = $1", [escalation_id])
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Escalation not found")

    await update_escalation_status(escalation_id, status_value, payload.reviewNotes.strip() if payload.reviewNotes else None)
    row["status"] = status_value
    row["review_notes"] = payload.reviewNotes.strip() if payload.reviewNotes else row.get("review_notes")

    claim_row = await _fetch_row("SELECT * FROM claims WHERE id = $1", [int(row["claim_id"])])
    if claim_row:
        row["claim_type"] = claim_row.get("claim_type")
        row["claim_status"] = claim_row.get("status")
        row["amount"] = claim_row.get("amount")
        row["zone_pincode"] = claim_row.get("zone_pincode")
        row["source"] = claim_row.get("source")

    worker_row = await _fetch_row("SELECT name, zone_name, platform_name FROM workers WHERE phone = $1", [str(row["phone"])])
    if worker_row:
        row["worker_name"] = worker_row.get("name")
        row["worker_zone_name"] = worker_row.get("zone_name")
        row["worker_platform_name"] = worker_row.get("platform_name")

    return ApiResponse(success=True, data=_format_escalation(row), message="Escalation reviewed")


@router.post("/zonelock-reports/{report_id}/review", response_model=ApiResponse)
async def review_report(
    report_id: int,
    payload: AdminStatusUpdateRequest,
    _admin: dict[str, Any] = Depends(_require_admin),
) -> ApiResponse:
    status_value = payload.status.strip().lower()
    if status_value not in ALLOWED_REPORT_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported report status")

    row = await _fetch_row("SELECT * FROM zonelock_reports WHERE id = $1", [report_id])
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")

    await update_zonelock_report_status(report_id, status_value)
    row["status"] = status_value

    worker_row = await _fetch_row("SELECT name, platform_name FROM workers WHERE phone = $1", [str(row["phone"])])
    if worker_row:
        row["worker_name"] = worker_row.get("name")
        row["worker_platform_name"] = worker_row.get("platform_name")

    return ApiResponse(success=True, data=_format_report(row), message="ZoneLock report updated")