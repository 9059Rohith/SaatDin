from __future__ import annotations

import hashlib
import logging
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from itertools import combinations
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..core.config import settings
from ..core.db import (
    create_fraud_cluster_run,
    finalize_fraud_cluster_run,
    list_claim_events_since,
    save_fraud_co_claim_clusters,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClaimEvent:
    phone: str
    claim_type: str
    zone_pincode: str
    created_at: datetime


def _parse_claim_events(rows: List[Dict[str, Any]]) -> List[ClaimEvent]:
    events: List[ClaimEvent] = []
    for row in rows:
        phone = str(row.get("phone", "")).strip()
        claim_type = str(row.get("claim_type", "")).strip()
        zone_pincode = str(row.get("zone_pincode", "")).strip()
        created_raw = row.get("created_at")
        if not phone or not claim_type or not zone_pincode or not isinstance(created_raw, str):
            continue
        try:
            created_at = datetime.fromisoformat(created_raw)
        except ValueError:
            continue
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        events.append(
            ClaimEvent(
                phone=phone,
                claim_type=claim_type,
                zone_pincode=zone_pincode,
                created_at=created_at.astimezone(timezone.utc),
            )
        )
    return events


def _bucket_start(value: datetime, bucket_minutes: int) -> datetime:
    utc = value.astimezone(timezone.utc)
    minute = (utc.minute // bucket_minutes) * bucket_minutes
    return utc.replace(minute=minute, second=0, microsecond=0)


def _edge_key(phone_a: str, phone_b: str) -> Tuple[str, str]:
    return (phone_a, phone_b) if phone_a < phone_b else (phone_b, phone_a)


def _recency_weight(last_seen: datetime, now_utc: datetime, half_life_days: float) -> float:
    age_days = max(0.0, (now_utc - last_seen).total_seconds() / 86400.0)
    if half_life_days <= 0:
        return 0.0
    return float(0.5 ** (age_days / half_life_days))


def _frequency_score(co_claim_count: int, min_edge_support: int) -> float:
    support = max(1, min_edge_support)
    return min(1.0, float(co_claim_count) / float(support * 2))


def _cluster_key(members: Iterable[str]) -> str:
    material = "|".join(sorted(members))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _build_edges(
    events: List[ClaimEvent],
    *,
    bucket_minutes: int,
    now_utc: datetime,
    min_edge_support: int,
    recency_half_life_days: float,
) -> Dict[Tuple[str, str], Dict[str, Any]]:
    grouped: Dict[Tuple[str, str, datetime], set[str]] = defaultdict(set)
    for event in events:
        bucket = _bucket_start(event.created_at, bucket_minutes)
        grouped[(event.zone_pincode, event.claim_type, bucket)].add(event.phone)

    edges: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for (zone_pincode, claim_type, bucket), phones in grouped.items():
        if len(phones) < 2:
            continue
        for left, right in combinations(sorted(phones), 2):
            key = _edge_key(left, right)
            existing = edges.get(key)
            if existing is None:
                edges[key] = {
                    "phone_a": key[0],
                    "phone_b": key[1],
                    "co_claim_count": 1,
                    "last_co_claim_at": bucket,
                    "zones": {zone_pincode},
                    "claim_types": {claim_type},
                }
            else:
                existing["co_claim_count"] = int(existing["co_claim_count"]) + 1
                if bucket > existing["last_co_claim_at"]:
                    existing["last_co_claim_at"] = bucket
                existing["zones"].add(zone_pincode)
                existing["claim_types"].add(claim_type)

    supported_edges: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for key, edge in edges.items():
        co_count = int(edge["co_claim_count"])
        if co_count < max(1, min_edge_support):
            continue
        recency = _recency_weight(
            edge["last_co_claim_at"],
            now_utc,
            recency_half_life_days,
        )
        frequency = _frequency_score(co_count, min_edge_support)
        edge_weight = (0.65 * frequency) + (0.35 * recency)
        supported_edges[key] = {
            "phone_a": edge["phone_a"],
            "phone_b": edge["phone_b"],
            "co_claim_count": co_count,
            "last_co_claim_at": edge["last_co_claim_at"].isoformat(),
            "frequency_score": round(frequency, 6),
            "recency_weight": round(recency, 6),
            "edge_weight": round(edge_weight, 6),
            "supporting_metadata": {
                "zones": sorted(edge["zones"]),
                "claim_types": sorted(edge["claim_types"]),
            },
        }
    return supported_edges


def _connected_components(edges: Dict[Tuple[str, str], Dict[str, Any]]) -> List[set[str]]:
    adjacency: Dict[str, set[str]] = defaultdict(set)
    for (phone_a, phone_b), _edge in edges.items():
        adjacency[phone_a].add(phone_b)
        adjacency[phone_b].add(phone_a)

    visited: set[str] = set()
    components: List[set[str]] = []
    for phone in adjacency:
        if phone in visited:
            continue
        queue: deque[str] = deque([phone])
        component: set[str] = set()
        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            component.add(current)
            for neighbor in adjacency.get(current, set()):
                if neighbor not in visited:
                    queue.append(neighbor)
        if component:
            components.append(component)
    return components


def _risk_level(score: float) -> str:
    if score >= settings.co_claim_high_threshold:
        return "high"
    if score >= settings.co_claim_medium_threshold:
        return "medium"
    return "low"


def _cluster_risk_score(
    *,
    member_count: int,
    edge_count: int,
    event_count: int,
    frequency_score: float,
    recency_score: float,
) -> Tuple[float, float, float]:
    possible_edges = max(1, (member_count * (member_count - 1)) // 2)
    density = float(edge_count) / float(possible_edges)
    activity_score = min(1.0, float(event_count) / float(max(1, member_count * 2)))
    score = (0.45 * frequency_score) + (0.25 * recency_score) + (0.20 * density) + (0.10 * activity_score)
    return (min(1.0, round(score, 6)), round(density, 6), round(activity_score, 6))


def _member_claim_stats(events: List[ClaimEvent], members: set[str]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for phone in members:
        related = [event.created_at for event in events if event.phone == phone]
        if not related:
            out[phone] = {
                "phone": phone,
                "claim_count": 0,
                "first_claim_at": None,
                "last_claim_at": None,
            }
            continue
        related.sort()
        out[phone] = {
            "phone": phone,
            "claim_count": len(related),
            "first_claim_at": related[0].isoformat(),
            "last_claim_at": related[-1].isoformat(),
        }
    return out


def compute_co_claim_clusters(
    *,
    claims: List[Dict[str, Any]],
    now_utc: Optional[datetime] = None,
) -> Dict[str, Any]:
    reference_now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    events = _parse_claim_events(claims)
    edges = _build_edges(
        events,
        bucket_minutes=max(1, int(settings.co_claim_graph_time_bucket_minutes)),
        now_utc=reference_now,
        min_edge_support=max(1, int(settings.co_claim_graph_min_edge_support)),
        recency_half_life_days=max(0.1, float(settings.co_claim_graph_recency_half_life_days)),
    )
    components = _connected_components(edges)
    member_stats_lookup = _member_claim_stats(events, {event.phone for event in events})

    clusters: List[Dict[str, Any]] = []
    min_members = max(2, int(settings.co_claim_graph_min_cluster_members))
    for component in components:
        if len(component) < min_members:
            continue
        component_edges = [
            edge
            for edge in edges.values()
            if edge["phone_a"] in component and edge["phone_b"] in component
        ]
        if not component_edges:
            continue

        edge_count = len(component_edges)
        event_count = sum(int(edge["co_claim_count"]) for edge in component_edges)
        frequency_score = sum(float(edge["frequency_score"]) for edge in component_edges) / float(edge_count)
        recency_score = sum(float(edge["recency_weight"]) for edge in component_edges) / float(edge_count)
        risk_score, density, activity_score = _cluster_risk_score(
            member_count=len(component),
            edge_count=edge_count,
            event_count=event_count,
            frequency_score=frequency_score,
            recency_score=recency_score,
        )
        members = [member_stats_lookup.get(phone, {"phone": phone, "claim_count": 0, "first_claim_at": None, "last_claim_at": None}) for phone in sorted(component)]
        top_edges = sorted(component_edges, key=lambda item: float(item["edge_weight"]), reverse=True)[:5]
        clusters.append(
            {
                "cluster_key": _cluster_key(component),
                "risk_score": risk_score,
                "risk_level": _risk_level(risk_score),
                "member_count": len(component),
                "edge_count": edge_count,
                "event_count": event_count,
                "frequency_score": round(frequency_score, 6),
                "recency_score": round(recency_score, 6),
                "supporting_metadata": {
                    "density": density,
                    "activity_score": activity_score,
                    "formula": "0.45*frequency + 0.25*recency + 0.20*density + 0.10*activity",
                    "time_bucket_minutes": int(settings.co_claim_graph_time_bucket_minutes),
                    "lookback_days": int(settings.co_claim_graph_lookback_days),
                    "min_edge_support": int(settings.co_claim_graph_min_edge_support),
                    "top_edges": top_edges,
                },
                "members": members,
                "edges": component_edges,
            }
        )

    clusters.sort(key=lambda cluster: float(cluster["risk_score"]), reverse=True)
    limited_clusters = clusters[: max(1, int(settings.co_claim_graph_max_clusters_per_run))]
    flagged = [cluster for cluster in limited_clusters if cluster["risk_level"] in {"medium", "high"}]
    return {
        "claims_scanned": len(events),
        "edge_count": len(edges),
        "cluster_count": len(limited_clusters),
        "flagged_cluster_count": len(flagged),
        "clusters": limited_clusters,
    }


async def generate_co_claim_clusters_snapshot() -> Dict[str, Any]:
    if not settings.co_claim_graph_enabled:
        return {"status": "disabled", "message": "Co-claim graph pipeline is disabled."}

    run = await create_fraud_cluster_run(
        lookback_days=int(settings.co_claim_graph_lookback_days),
        time_bucket_minutes=int(settings.co_claim_graph_time_bucket_minutes),
        min_edge_support=int(settings.co_claim_graph_min_edge_support),
        medium_risk_threshold=float(settings.co_claim_medium_threshold),
        high_risk_threshold=float(settings.co_claim_high_threshold),
    )
    run_id = int(run["id"])
    logger.info("co_claim_cluster_run_started run_id=%s", run_id)
    try:
        since = datetime.now(timezone.utc) - timedelta(days=int(settings.co_claim_graph_lookback_days))
        rows = await list_claim_events_since(since)
        result = compute_co_claim_clusters(claims=rows)
        persisted = await save_fraud_co_claim_clusters(run_id, result["clusters"])
        await finalize_fraud_cluster_run(
            run_id,
            status="completed",
            claims_scanned=int(result["claims_scanned"]),
            edge_count=int(result["edge_count"]),
            cluster_count=int(result["cluster_count"]),
            flagged_cluster_count=int(result["flagged_cluster_count"]),
        )
        logger.info(
            "co_claim_cluster_run_completed run_id=%s claims_scanned=%s edges=%s clusters=%s flagged=%s",
            run_id,
            result["claims_scanned"],
            result["edge_count"],
            persisted,
            result["flagged_cluster_count"],
        )
        return {
            "status": "completed",
            "run_id": run_id,
            "claims_scanned": int(result["claims_scanned"]),
            "edge_count": int(result["edge_count"]),
            "cluster_count": int(result["cluster_count"]),
            "flagged_cluster_count": int(result["flagged_cluster_count"]),
        }
    except Exception as exc:
        logger.exception("co_claim_cluster_run_failed run_id=%s error=%s", run_id, exc)
        await finalize_fraud_cluster_run(
            run_id,
            status="failed",
            claims_scanned=0,
            edge_count=0,
            cluster_count=0,
            flagged_cluster_count=0,
            error_message=str(exc),
        )
        raise
