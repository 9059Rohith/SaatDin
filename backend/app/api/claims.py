from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Path

from ..core.db import count_claims_for_phone_since, create_claim, list_claims_for_phone, escalate_claim, get_claim_escalation
from ..core.dependencies import get_current_worker
from ..core.zone_cache import resolve_zone
from ..models.schemas import ApiResponse, ClaimOut, ClaimSubmitRequest, ClaimEscalateRequest, ClaimEscalationOut
from ..services.fraud_isolation import score_claim
from ..services.motion_validation import evaluate_worker_motion_signal, motion_features_from_validation
from ..services.tower_validation import evaluate_worker_tower_signal, tower_features_from_validation
from ..services.trigger_monitor import calculate_zone_affinity_score, get_fraud_ring_members

router = APIRouter(tags=["claims"])
logger = logging.getLogger(__name__)

_ALLOWED_CLAIM_TYPES = {
    "rainlock": "RainLock",
    "aqi_guard": "AQI Guard",
    "aqiguard": "AQI Guard",
    "trafficblock": "TrafficBlock",
    "zonelock": "ZoneLock",
    "heatblock": "HeatBlock",
}

_MANUAL_PAYOUT = {
    "RainLock": 400.0,
    "AQI Guard": 320.0,
    "TrafficBlock": 280.0,
    "ZoneLock": 400.0,
    "HeatBlock": 240.0,
}


def _normalize_claim_type(raw: str) -> str:
    key = raw.strip().lower().replace(" ", "").replace("_", "")
    if key not in _ALLOWED_CLAIM_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown claim type: {raw}")
    return _ALLOWED_CLAIM_TYPES[key]


def _to_claim_out(row: dict) -> ClaimOut:
    anomaly_features_raw = row.get("anomaly_features_json")
    if isinstance(anomaly_features_raw, str):
        try:
            anomaly_features_raw = json.loads(anomaly_features_raw)
        except json.JSONDecodeError:
            anomaly_features_raw = None
    anomaly_features = anomaly_features_raw if isinstance(anomaly_features_raw, dict) else None
    anomaly_scored_at = row.get("anomaly_scored_at")
    llm_decision_raw = row.get("llm_decision_json")
    if isinstance(llm_decision_raw, str):
        try:
            llm_decision_raw = json.loads(llm_decision_raw)
        except json.JSONDecodeError:
            llm_decision_raw = None
    llm_decision = llm_decision_raw if isinstance(llm_decision_raw, dict) else None

    llm_attempts_raw = row.get("llm_attempts_json")
    if isinstance(llm_attempts_raw, str):
        try:
            llm_attempts_raw = json.loads(llm_attempts_raw)
        except json.JSONDecodeError:
            llm_attempts_raw = None
    llm_attempts = llm_attempts_raw if isinstance(llm_attempts_raw, list) else None
    llm_scored_at = row.get("llm_scored_at")
    tower_status = anomaly_features.get("tower_validation_status") if isinstance(anomaly_features, dict) else None
    tower_confidence_raw = anomaly_features.get("tower_zone_confidence") if isinstance(anomaly_features, dict) else None
    tower_reason = anomaly_features.get("tower_validation_reason") if isinstance(anomaly_features, dict) else None
    tower_received_at = anomaly_features.get("tower_signal_received_at") if isinstance(anomaly_features, dict) else None
    motion_status = anomaly_features.get("motion_validation_status") if isinstance(anomaly_features, dict) else None
    motion_confidence_raw = anomaly_features.get("motion_confidence") if isinstance(anomaly_features, dict) else None
    motion_reason = anomaly_features.get("motion_validation_reason") if isinstance(anomaly_features, dict) else None
    motion_received_at = anomaly_features.get("motion_signal_received_at") if isinstance(anomaly_features, dict) else None

    return ClaimOut(
        id=f"#C{int(row['id']):05d}",
        claimType=str(row["claim_type"]),
        status=str(row["status"]),
        amount=float(row["amount"]),
        date=str(row["created_at"]),
        description=str(row["description"]),
        source=str(row["source"]),
        anomalyScore=float(row["anomaly_score"]) if row.get("anomaly_score") is not None else None,
        anomalyThreshold=float(row["anomaly_threshold"]) if row.get("anomaly_threshold") is not None else None,
        anomalyFlagged=bool(row["anomaly_flagged"]) if row.get("anomaly_flagged") is not None else None,
        anomalyModelVersion=str(row["anomaly_model_version"]) if row.get("anomaly_model_version") is not None else None,
        anomalyScoredAt=str(anomaly_scored_at) if anomaly_scored_at is not None else None,
        anomalyFeaturesJson=anomaly_features,
        llmReviewUsed=bool(row["llm_review_used"]) if row.get("llm_review_used") is not None else None,
        llmReviewStatus=str(row["llm_review_status"]) if row.get("llm_review_status") is not None else None,
        llmProvider=str(row["llm_provider"]) if row.get("llm_provider") is not None else None,
        llmModel=str(row["llm_model"]) if row.get("llm_model") is not None else None,
        llmFallbackUsed=bool(row["llm_fallback_used"]) if row.get("llm_fallback_used") is not None else None,
        llmDecisionConfidence=float(row["llm_decision_confidence"])
        if row.get("llm_decision_confidence") is not None
        else None,
        llmDecisionJson=llm_decision,
        llmAttemptsJson=llm_attempts,
        llmValidationError=str(row["llm_validation_error"]) if row.get("llm_validation_error") is not None else None,
        llmScoredAt=str(llm_scored_at) if llm_scored_at is not None else None,
        towerValidationStatus=str(tower_status) if tower_status is not None else None,
        towerZoneConfidence=float(tower_confidence_raw) if isinstance(tower_confidence_raw, (float, int)) else None,
        towerValidationReason=str(tower_reason) if tower_reason is not None else None,
        towerSignalReceivedAt=str(tower_received_at) if tower_received_at is not None else None,
        motionValidationStatus=str(motion_status) if motion_status is not None else None,
        motionConfidence=float(motion_confidence_raw) if isinstance(motion_confidence_raw, (float, int)) else None,
        motionValidationReason=str(motion_reason) if motion_reason is not None else None,
        motionSignalReceivedAt=str(motion_received_at) if motion_received_at is not None else None,
    )


async def _build_manual_claim_features(worker: dict, amount: float) -> dict:
    phone = str(worker["phone"])
    zone_pincode = str(worker["zone_pincode"])
    _, zone_data = resolve_zone(zone_pincode)

    coords = zone_data.get("coordinates_approx", {})
    zone_lat = float(zone_data.get("latitude", coords.get("lat", 12.97)))
    zone_lon = float(zone_data.get("longitude", coords.get("lon", 77.59)))
    zone_affinity = calculate_zone_affinity_score(phone, zone_lat, zone_lon)
    fraud_ring_size = len(get_fraud_ring_members(phone))
    recent_claims_24h = await count_claims_for_phone_since(
        phone,
        datetime.now(timezone.utc) - timedelta(hours=24),
    )
    tower_validation = await evaluate_worker_tower_signal(
        phone=phone,
        claimed_zone_pincode=zone_pincode,
        zone_lat=zone_lat,
        zone_lon=zone_lon,
    )
    motion_validation = await evaluate_worker_motion_signal(phone=phone)

    features = {
        "zone_affinity_score": zone_affinity,
        "fraud_ring_size": float(fraud_ring_size),
        "recent_claims_24h": float(recent_claims_24h),
        "claim_amount": float(amount),
        "trigger_confidence": 0.55,
        "is_manual_source": 1.0,
        "is_auto_source": 0.0,
        "flood_risk_score": float(zone_data.get("flood_risk_score", 0.5)),
        "aqi_risk_score": float(zone_data.get("aqi_risk_score", 0.5)),
        "traffic_congestion_score": float(zone_data.get("traffic_congestion_score", 0.5)),
    }
    features.update(tower_features_from_validation(tower_validation))
    features.update(motion_features_from_validation(motion_validation))
    return features


@router.get("", response_model=ApiResponse)
async def get_my_claims(worker: dict = Depends(get_current_worker)) -> ApiResponse:
    rows = await list_claims_for_phone(str(worker["phone"]))
    items = [_to_claim_out(row) for row in rows]
    logger.info("claims_list_requested phone=%s count=%s", worker["phone"], len(items))
    return ApiResponse(success=True, data=items)


@router.post("/submit", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def submit_claim(payload: ClaimSubmitRequest, worker: dict = Depends(get_current_worker)) -> ApiResponse:
    claim_type = _normalize_claim_type(payload.claimType)
    amount = _MANUAL_PAYOUT.get(claim_type, 250.0)
    phone = str(worker["phone"])
    anomaly_features = await _build_manual_claim_features(worker, amount)
    anomaly = score_claim(
        anomaly_features,
        context={
            "phone": phone,
            "claim_type": claim_type,
            "source": "manual",
        },
    )

    row = await create_claim(
        phone=phone,
        claim_type=claim_type,
        status="in_review",
        amount=amount,
        description=payload.description.strip(),
        zone_pincode=str(worker["zone_pincode"]),
        source="manual",
        anomaly_score=float(anomaly["anomaly_score"]),
        anomaly_threshold=float(anomaly["anomaly_threshold"]),
        anomaly_flagged=bool(anomaly["anomaly_flagged"]),
        anomaly_model_version=str(anomaly["anomaly_model_version"]),
        anomaly_features=dict(anomaly["anomaly_features"]),
        anomaly_scored_at=str(anomaly["anomaly_scored_at"]),
        llm_review_used=bool(anomaly["llm_review_used"]) if anomaly.get("llm_review_used") is not None else None,
        llm_review_status=str(anomaly["llm_review_status"]) if anomaly.get("llm_review_status") is not None else None,
        llm_provider=str(anomaly["llm_provider"]) if anomaly.get("llm_provider") is not None else None,
        llm_model=str(anomaly["llm_model"]) if anomaly.get("llm_model") is not None else None,
        llm_fallback_used=bool(anomaly["llm_fallback_used"]) if anomaly.get("llm_fallback_used") is not None else None,
        llm_decision_confidence=float(anomaly["llm_decision_confidence"])
        if anomaly.get("llm_decision_confidence") is not None
        else None,
        llm_decision_json=anomaly.get("llm_decision_json"),
        llm_attempts=anomaly.get("llm_attempts"),
        llm_validation_error=str(anomaly["llm_validation_error"])
        if anomaly.get("llm_validation_error") is not None
        else None,
        llm_scored_at=str(anomaly["llm_scored_at"]) if anomaly.get("llm_scored_at") is not None else None,
    )
    out = _to_claim_out(row)
    logger.info(
        "claim_submitted phone=%s claim_id=%s claim_type=%s anomaly_score=%.6f anomaly_flagged=%s",
        phone,
        out.id,
        claim_type,
        float(anomaly["anomaly_score"]),
        bool(anomaly["anomaly_flagged"]),
    )

    return ApiResponse(
        success=True,
        data=out,
        message="Claim submitted for review",
    )


@router.post("/{claim_id}/escalate", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def escalate_claim_endpoint(
    claim_id: int = Path(..., ge=1),
    payload: ClaimEscalateRequest = None,
    worker: dict = Depends(get_current_worker),
) -> ApiResponse:
    """
    Worker escalates a claim for manual review (e.g., disputes auto-settlement).
    Claim is marked and queued for human review with target SLA of 2 hours.
    """
    if payload is None:
        raise HTTPException(status_code=400, detail="Escalation reason required")

    phone = str(worker["phone"])
    
    # TODO: Verify that claim_id belongs to this phone (add check)
    # For now, we'll allow escalation

    escalation = await escalate_claim(
        claim_id=claim_id,
        phone=phone,
        reason=payload.reason.strip(),
    )

    logger.info(
        f"claim_escalated claim_id={claim_id} phone={phone} reason={payload.reason[:50]}..."
    )

    return ApiResponse(
        success=True,
        data=ClaimEscalationOut(
            id=escalation["id"],
            claimId=escalation["claim_id"],
            phone=escalation["phone"],
            reason=escalation["reason"],
            status=escalation["status"],
            reviewNotes=None,
            createdAt=escalation["created_at"],
        ),
        message="Claim escalated for manual review. Review SLA: 2 hours.",
    )
