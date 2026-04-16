from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional
import hashlib
from collections import defaultdict

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ..core.db import create_claim, has_recent_auto_claim, list_workers_by_zone
from ..core.zone_cache import load_zone_map, resolve_zone
from .premium import build_plans
from .external_apis import get_api_client, TRIGGER_THRESHOLDS
from ..models.platform import Platform

logger = logging.getLogger(__name__)

_live_trigger_state: Dict[str, Dict[str, Any]] = {}

# Fraud detection: track device fingerprints and suspicious patterns
_device_fingerprints: Dict[str, str] = {}  # phone -> device_fingerprint
_fraud_ring_clusters: Dict[str, set] = defaultdict(set)  # device_fingerprint -> set of phones
_worker_gps_cache: Dict[str, Dict[str, Any]] = {}  # phone -> {latitude, longitude, timestamp}

_TRIGGER_PAYOUT_FACTORS = {
    "rain": 1.00,
    "aqi": 0.80,
    "traffic": 0.70,
    "zonelock": 1.00,
    "heat": 0.60,
}


async def force_trigger_for_zone(
    zone_key: str,
    claim_type: str,
    alert_title: str,
    alert_description: str,
    confidence: float = 0.9,
    source: str = "manual",
) -> Dict[str, Any]:
    pincode, zone = resolve_zone(zone_key)
    state = {
        "hasActiveAlert": True,
        "alertType": claim_type.lower().replace(" ", ""),
        "claimType": claim_type,
        "alertTitle": alert_title,
        "alertDescription": alert_description,
        "confidence": confidence,
        "dataSource": source,
        "source": source,
    }
    _live_trigger_state[pincode] = state

    workers = await list_workers_by_zone(pincode)
    created = 0
    for worker in workers:
        phone = str(worker["phone"])

        if await has_recent_auto_claim(phone, claim_type, within_minutes=360):
            continue

        platform = _platform_from_display(str(worker["platform_name"]))
        zone_multiplier = float(zone.get("zone_risk_multiplier", 1.0))
        plans = build_plans(zone_multiplier, platform, zone_data=zone)
        selected = next(
            (plan for plan in plans if plan.name.lower() == str(worker["plan_name"]).lower()),
            plans[1],
        )

        payout = float(selected.perTriggerPayout) * _TRIGGER_PAYOUT_FACTORS.get(state["alertType"], 0.7)
        await create_claim(
            phone=phone,
            claim_type=claim_type,
            status="settled",
            amount=round(payout, 2),
            description=f"Auto-settled: {alert_title}. Data source: {source}.",
            zone_pincode=pincode,
            source=source,
        )
        created += 1

    logger.info(
        "trigger_forced pincode=%s claim_type=%s created=%s source=%s",
        pincode,
        claim_type,
        created,
        source,
    )
    return {
        "zone": zone.get("name", zone_key),
        "pincode": pincode,
        "claimType": claim_type,
        "alertTitle": alert_title,
        "hasActiveAlert": True,
        "autoClaimsCreated": created,
        "source": source,
    }


def get_live_trigger_state() -> Dict[str, Dict[str, Any]]:
    return _live_trigger_state


def register_device_fingerprint(phone: str, device_id: str, app_version: str, os_type: str) -> str:
    """
    Register device fingerprint for fraud ring detection.
    Returns the hash of the fingerprint.
    """
    fingerprint = f"{device_id}|{app_version}|{os_type}"
    fingerprint_hash = hashlib.sha256(fingerprint.encode()).hexdigest()[:12]
    _device_fingerprints[phone] = fingerprint_hash
    _fraud_ring_clusters[fingerprint_hash].add(phone)
    logger.info(f"device_fingerprint_registered phone={phone} hash={fingerprint_hash}")
    return fingerprint_hash


def update_worker_gps(phone: str, latitude: float, longitude: float):
    """Update worker's last known GPS location for zone affinity scoring."""
    _worker_gps_cache[phone] = {
        "latitude": latitude,
        "longitude": longitude,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def calculate_zone_affinity_score(phone: str, zone_center_lat: float, zone_center_lon: float) -> float:
    """
    Calculate zone affinity score (0-1) based on GPS distance from zone center.
    Score of 1.0 means worker is at zone center.
    Score < 0.3 is suspicious (worker far from registered zone).
    """
    if phone not in _worker_gps_cache:
        return 0.5  # Unknown location, neutral score

    gps = _worker_gps_cache[phone]
    lat1, lon1 = gps["latitude"], gps["longitude"]
    lat2, lon2 = zone_center_lat, zone_center_lon

    # Haversine distance (approximate for small distances)
    # For Bangalore zones, rough approximation: 1 degree ≈ 111 km, 1 km ≈ 0.009 degrees
    dx = (lon2 - lon1) * 111 * 1000 * 0.9  # meters (latitude adjustment)
    dy = (lat2 - lat1) * 111 * 1000
    distance_meters = (dx**2 + dy**2) ** 0.5

    # Scoring: within 2 km = high (0.9), within 5 km = medium (0.6), beyond 10 km = low (0.3)
    if distance_meters < 2000:
        return 0.95
    elif distance_meters < 5000:
        return 0.7
    elif distance_meters < 10000:
        return 0.4
    else:
        return 0.2


def get_fraud_ring_members(phone: str) -> set:
    """Get all phones (potential fraud ring) that share device fingerprint with given phone."""
    if phone not in _device_fingerprints:
        return set()
    fingerprint_hash = _device_fingerprints[phone]
    return _fraud_ring_clusters.get(fingerprint_hash, set())


async def _determine_trigger(zone: Dict[str, Any]) -> Dict[str, Any]:
    """
    Determine active trigger for a zone using real API data.
    Falls back to zone risk scores if APIs unavailable.
    """
    api_client = get_api_client()
    zone_lat = float(zone.get("latitude", 12.97))
    zone_lon = float(zone.get("longitude", 77.59))

    # Try real APIs first, fall back to zone risk scores
    flood = float(zone.get("flood_risk_score", 0.0))
    aqi = float(zone.get("aqi_risk_score", 0.0))
    traffic = float(zone.get("traffic_congestion_score", 0.0))

    # Attempt to fetch real rainfall data
    rainfall_real = await api_client.get_rainfall_data(zone_lat, zone_lon)
    if rainfall_real is not None and rainfall_real > TRIGGER_THRESHOLDS["rainfall_mm"]:
        return {
            "hasActiveAlert": True,
            "alertType": "rain",
            "claimType": "RainLock",
            "alertTitle": "RainLock: Heavy rainfall detected",
            "alertDescription": f"Rainfall {rainfall_real:.1f}mm exceeds threshold ({TRIGGER_THRESHOLDS['rainfall_mm']}mm).",
            "confidence": min(0.99, 0.85 + (rainfall_real / 100) * 0.14),
            "dataSource": "open-meteo",
        }

    # Attempt to fetch real AQI data
    aqi_real = await api_client.get_aqi_data(zone_lat, zone_lon)
    if aqi_real is not None and aqi_real > TRIGGER_THRESHOLDS["aqi_dangerous"]:
        now = datetime.now(timezone.utc)
        if 12 <= now.hour <= 22:  # Daytime outdoor work window
            return {
                "hasActiveAlert": True,
                "alertType": "aqi",
                "claimType": "AQI Guard",
                "alertTitle": "AQI Guard: Hazardous air quality",
                "alertDescription": f"AQI {int(aqi_real)} exceeds danger threshold ({TRIGGER_THRESHOLDS['aqi_dangerous']}).",
                "confidence": min(0.98, 0.80 + (aqi_real / 300) * 0.18),
                "dataSource": "waqi",
            }

    # Attempt to fetch real traffic speed
    traffic_real = await api_client.get_traffic_speed(zone_lat, zone_lon)
    if traffic_real is not None and traffic_real < TRIGGER_THRESHOLDS["traffic_speed_kmph"]:
        return {
            "hasActiveAlert": True,
            "alertType": "traffic",
            "claimType": "TrafficBlock",
            "alertTitle": "TrafficBlock: Severe congestion",
            "alertDescription": f"Average speed {traffic_real:.1f} kmph below limit ({TRIGGER_THRESHOLDS['traffic_speed_kmph']} kmph).",
            "confidence": min(0.98, 0.75 + (1 - traffic_real / 10) * 0.23),
            "dataSource": "tomtom",
        }

    # Attempt to fetch heat + humidity
    heat_data = await api_client.get_heat_humidity_data(zone_lat, zone_lon)
    if (
        heat_data
        and heat_data.get("temperature", 0) > TRIGGER_THRESHOLDS["heat_temp_celsius"]
        and heat_data.get("humidity", 0) > TRIGGER_THRESHOLDS["heat_humidity_percent"]
    ):
        now = datetime.now(timezone.utc)
        if 13 <= now.hour <= 17:  # Peak afternoon heat
            return {
                "hasActiveAlert": True,
                "alertType": "heat",
                "claimType": "HeatBlock",
                "alertTitle": "HeatBlock: Extreme heat + humidity",
                "alertDescription": f"Temperature {heat_data['temperature']:.0f}°C, Humidity {heat_data['humidity']:.0f}%.",
                "confidence": 0.85,
                "dataSource": "open-meteo",
            }

    # Attempt to fetch zone disruption news
    zone_name = str(zone.get("zone_name", ""))
    pincode = str(zone.get("pincode", ""))
    disruption = await api_client.get_zone_disruption_news(zone_name, pincode)
    if disruption:
        return {
            "hasActiveAlert": True,
            "alertType": "zonelock",
            "claimType": "ZoneLock",
            "alertTitle": f"ZoneLock: {disruption.title()} detected",
            "alertDescription": f"Civic disruption ({disruption}) detected in {zone_name}.",
            "confidence": 0.80,
            "dataSource": "newsapi",
        }

    # Fallback: use zone risk scores if APIs unavailable
    if flood >= 0.75:
        return {
            "hasActiveAlert": True,
            "alertType": "rain",
            "claimType": "RainLock",
            "alertTitle": "RainLock: High flood risk zone",
            "alertDescription": "Zone has elevated historical flood risk.",
            "confidence": 0.72,
            "dataSource": "zone-risk-score",
        }

    if aqi >= 0.70:
        return {
            "hasActiveAlert": True,
            "alertType": "aqi",
            "claimType": "AQI Guard",
            "alertTitle": "AQI Guard: High AQI history",
            "alertDescription": "Zone has elevated AQI risk history.",
            "confidence": 0.68,
            "dataSource": "zone-risk-score",
        }

    if traffic >= 0.80:
        return {
            "hasActiveAlert": True,
            "alertType": "traffic",
            "claimType": "TrafficBlock",
            "alertTitle": "TrafficBlock: High congestion risk",
            "alertDescription": "Zone has elevated traffic congestion history.",
            "confidence": 0.70,
            "dataSource": "zone-risk-score",
        }

    return {
        "hasActiveAlert": False,
        "alertType": "none",
        "claimType": "none",
        "alertTitle": "No active trigger",
        "alertDescription": "No active disruption trigger detected.",
        "confidence": 0.55,
        "dataSource": "none",
    }


def _platform_from_display(name: str) -> Platform:
    lowered = name.strip().lower()
    if lowered == "blinkit":
        return Platform.blinkit
    if lowered == "zepto":
        return Platform.zepto
    return Platform.swiggy_instamart


async def refresh_live_trigger_state() -> None:
    zones = load_zone_map()

    for pincode, zone in zones.items():
        state = await _determine_trigger(zone)
        state["source"] = "live"
        _live_trigger_state[pincode] = state

        if not state.get("hasActiveAlert"):
            continue

        claim_type = str(state.get("claimType", "none"))
        alert_type = str(state.get("alertType", "none"))
        if claim_type == "none" or alert_type == "none":
            continue

        workers = await list_workers_by_zone(pincode)
        for worker in workers:
            phone = str(worker["phone"])
            
            # Fraud scoring: multiple checks before auto-claim
            zone_affinity = calculate_zone_affinity_score(
                phone,
                float(zone.get("latitude", 12.97)),
                float(zone.get("longitude", 77.59)),
            )
            fraud_ring = get_fraud_ring_members(phone)
            
            # Only auto-claim if zone affinity is reasonable (not obviously spoofed location)
            if zone_affinity < 0.25:
                logger.info(
                    f"auto_claim_rejected phone={phone} claim_type={claim_type} reason=low_zone_affinity score={zone_affinity:.2f}"
                )
                continue
            
            # Check for fraud ring activity on same event
            same_event_ring_claims = sum(
                1 for member in fraud_ring
                if member != phone and member in [w["phone"] for w in workers]
            )
            if same_event_ring_claims > 2:
                logger.warning(
                    f"auto_claim_rejected phone={phone} claim_type={claim_type} reason=fraud_ring_detected count={same_event_ring_claims + 1}"
                )
                continue

            # Standard duplicate suppression
            if await has_recent_auto_claim(phone, claim_type, within_minutes=360):
                continue

            platform = _platform_from_display(str(worker["platform_name"]))
            zone_multiplier = float(zone.get("zone_risk_multiplier", 1.0))
            plans = build_plans(zone_multiplier, platform, zone_data=zone)
            selected = next(
                (plan for plan in plans if plan.name.lower() == str(worker["plan_name"]).lower()),
                plans[1],
            )

            payout = float(selected.perTriggerPayout) * _TRIGGER_PAYOUT_FACTORS.get(alert_type, 0.7)
            await create_claim(
                phone=phone,
                claim_type=claim_type,
                status="settled",
                amount=round(payout, 2),
                description=f"Auto-settled: {state['alertTitle']}. Data source: {state.get('dataSource', 'unknown')}.",
                zone_pincode=pincode,
                source="auto",
            )
            logger.info(
                f"auto_claim_created phone={phone} claim_type={claim_type} payout={payout} zone_affinity={zone_affinity:.2f} data_source={state.get('dataSource')}"
            )


class TriggerMonitor:
    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler(timezone="UTC")
        self._started = False

    async def _safe_refresh(self) -> None:
        try:
            await refresh_live_trigger_state()
        except Exception:
            logger.exception("trigger_refresh_failed")

    async def start(self) -> None:
        if self._started:
            return
        self._scheduler.add_job(self._safe_refresh, "interval", minutes=5, id="trigger_refresh", replace_existing=True)
        # Do not block API boot on external API fetches; run initial refresh in background.
        asyncio.create_task(self._safe_refresh())
        self._scheduler.start()
        self._started = True
        logger.info("trigger_monitor_started")

    async def stop(self) -> None:
        if not self._started:
            return
        self._scheduler.shutdown(wait=False)
        self._started = False
        logger.info("trigger_monitor_stopped")


trigger_monitor = TriggerMonitor()
