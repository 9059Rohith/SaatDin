from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..core.db import (
    get_fraud_cluster,
    get_latest_fraud_cluster_run,
    list_fraud_cluster_edges,
    list_fraud_cluster_members,
    list_fraud_cluster_runs,
    list_fraud_clusters,
)
from ..core.dependencies import get_current_phone
from ..models.schemas import (
    ApiResponse,
    FraudClusterDetailOut,
    FraudClusterEdgeOut,
    FraudClusterMemberOut,
    FraudClusterRunOut,
    FraudClusterSummaryOut,
)
from ..services.co_claim_graph import generate_co_claim_clusters_snapshot

router = APIRouter(tags=["fraud-clusters"])
logger = logging.getLogger(__name__)


def _parse_json_dict(value: Any) -> Optional[Dict[str, Any]]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            return parsed
    return None


def _to_run_out(row: Dict[str, Any]) -> FraudClusterRunOut:
    return FraudClusterRunOut(
        id=int(row["id"]),
        startedAt=str(row["started_at"]),
        finishedAt=str(row["finished_at"]) if row.get("finished_at") is not None else None,
        status=str(row["status"]),
        errorMessage=str(row["error_message"]) if row.get("error_message") is not None else None,
        lookbackDays=int(row["lookback_days"]),
        timeBucketMinutes=int(row["time_bucket_minutes"]),
        minEdgeSupport=int(row["min_edge_support"]),
        mediumRiskThreshold=float(row["medium_risk_threshold"]),
        highRiskThreshold=float(row["high_risk_threshold"]),
        claimsScanned=int(row["claims_scanned"]),
        edgeCount=int(row["edge_count"]),
        clusterCount=int(row["cluster_count"]),
        flaggedClusterCount=int(row["flagged_cluster_count"]),
        createdAt=str(row["created_at"]),
    )


def _to_cluster_summary_out(row: Dict[str, Any]) -> FraudClusterSummaryOut:
    return FraudClusterSummaryOut(
        id=int(row["id"]),
        runId=int(row["run_id"]),
        clusterKey=str(row["cluster_key"]),
        riskScore=float(row["risk_score"]),
        riskLevel=str(row["risk_level"]),
        memberCount=int(row["member_count"]),
        edgeCount=int(row["edge_count"]),
        eventCount=int(row["event_count"]),
        frequencyScore=float(row["frequency_score"]),
        recencyScore=float(row["recency_score"]),
        supportingMetadataJson=_parse_json_dict(row.get("supporting_metadata_json")),
        createdAt=str(row["created_at"]),
    )


def _to_member_out(row: Dict[str, Any]) -> FraudClusterMemberOut:
    return FraudClusterMemberOut(
        id=int(row["id"]),
        clusterId=int(row["cluster_id"]),
        phone=str(row["phone"]),
        claimCount=int(row["claim_count"]),
        firstClaimAt=str(row["first_claim_at"]) if row.get("first_claim_at") is not None else None,
        lastClaimAt=str(row["last_claim_at"]) if row.get("last_claim_at") is not None else None,
        createdAt=str(row["created_at"]),
    )


def _to_edge_out(row: Dict[str, Any]) -> FraudClusterEdgeOut:
    return FraudClusterEdgeOut(
        id=int(row["id"]),
        clusterId=int(row["cluster_id"]),
        phoneA=str(row["phone_a"]),
        phoneB=str(row["phone_b"]),
        coClaimCount=int(row["co_claim_count"]),
        recencyWeight=float(row["recency_weight"]),
        edgeWeight=float(row["edge_weight"]),
        lastCoClaimAt=str(row["last_co_claim_at"]) if row.get("last_co_claim_at") is not None else None,
        supportingMetadataJson=_parse_json_dict(row.get("supporting_metadata_json")),
        createdAt=str(row["created_at"]),
    )


@router.get("/runs", response_model=ApiResponse)
async def get_cluster_runs(
    limit: int = Query(default=20, ge=1, le=100),
    _phone: str = Depends(get_current_phone),
) -> ApiResponse:
    runs = await list_fraud_cluster_runs(limit=limit)
    return ApiResponse(success=True, data=[_to_run_out(item) for item in runs])


@router.get("/clusters", response_model=ApiResponse)
async def get_clusters(
    runId: Optional[int] = Query(default=None, ge=1),
    riskLevel: Optional[str] = Query(default=None),
    flaggedOnly: bool = Query(default=True),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _phone: str = Depends(get_current_phone),
) -> ApiResponse:
    run_id = runId
    if run_id is None:
        latest = await get_latest_fraud_cluster_run()
        if latest:
            run_id = int(latest["id"])
    clusters = await list_fraud_clusters(
        run_id=run_id,
        risk_level=riskLevel,
        flagged_only=flaggedOnly,
        limit=limit,
        offset=offset,
    )
    return ApiResponse(success=True, data=[_to_cluster_summary_out(item) for item in clusters])


@router.get("/clusters/{cluster_id}", response_model=ApiResponse)
async def get_cluster_detail(
    cluster_id: int,
    edgeLimit: int = Query(default=200, ge=1, le=500),
    _phone: str = Depends(get_current_phone),
) -> ApiResponse:
    cluster = await get_fraud_cluster(cluster_id)
    if not cluster:
        raise HTTPException(status_code=404, detail=f"Cluster {cluster_id} not found")

    members = await list_fraud_cluster_members(cluster_id)
    edges = await list_fraud_cluster_edges(cluster_id, limit=edgeLimit)
    detail = FraudClusterDetailOut(
        cluster=_to_cluster_summary_out(cluster),
        members=[_to_member_out(item) for item in members],
        edges=[_to_edge_out(item) for item in edges],
    )
    return ApiResponse(success=True, data=detail)


@router.post("/clusters/run", response_model=ApiResponse)
async def run_cluster_generation(
    _phone: str = Depends(get_current_phone),
) -> ApiResponse:
    result = await generate_co_claim_clusters_snapshot()
    logger.info("co_claim_cluster_manual_run_invoked status=%s", result.get("status"))
    return ApiResponse(success=True, data=result, message="Co-claim cluster generation completed")
