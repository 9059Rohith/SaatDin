"""External API clients for real trigger data fetching."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

from ..core.config import settings

try:
    import aiohttp
except ImportError:
    aiohttp = None  # type: ignore

logger = logging.getLogger(__name__)

# API endpoints and configurations
OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"
WAQI_BASE = "https://api.waqi.info"
TOMTOM_BASE = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"
NEWS_API_BASE = "https://newsapi.org/v2/everything"

# Configuration for trigger thresholds
TRIGGER_THRESHOLDS = {
    "rainfall_mm": 35.0,  # > 35mm in 3 hours
    "rainfall_window_hours": 3,
    "aqi_dangerous": 250,
    "aqi_window_hours": 4,
    "traffic_speed_kmph": 5,
    "traffic_duration_hours": 2,
    "heat_temp_celsius": 39,
    "heat_humidity_percent": 70,
    "heat_window_hours": 4,
}


class ExternalAPIClient:
    """Client for fetching real-time disruption data from public APIs."""

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self._aiohttp_available = aiohttp is not None

    async def initialize(self):
        """Initialize aiohttp session if available."""
        if self._aiohttp_available:
            self._session = aiohttp.ClientSession()

    async def close(self):
        """Close aiohttp session."""
        if self._session:
            await self._session.close()

    async def _fetch_json(self, url: str, params: Optional[Dict[str, Any]] = None, timeout: int = 5) -> Optional[Dict[str, Any]]:
        """Fetch JSON from URL with timeout handling."""
        if not self._aiohttp_available or not self._session:
            return None

        try:
            async with self._session.get(url, params=params, timeout=timeout) as resp:
                if resp.status == 200:
                    return await resp.json()
                logger.warning(f"API response status {resp.status} for {url}")
                return None
        except asyncio.TimeoutError:
            logger.warning(f"API timeout for {url}")
            return None
        except Exception as e:
            logger.warning(f"API fetch error for {url}: {e}")
            return None

    async def get_rainfall_data(self, latitude: float, longitude: float) -> Optional[float]:
        """
        Fetch rainfall data from Open-Meteo.
        Returns: mm of rainfall in the past 3 hours, or None if API fails.
        """
        try:
            params = {
                "latitude": latitude,
                "longitude": longitude,
                "precipitation_unit": "mm",
                "timezone": "Asia/Kolkata",
                "past_days": 1,
                "forecast_hours": 0,
            }
            data = await self._fetch_json(OPEN_METEO_BASE, params)
            if not data or "hourly" not in data:
                return None

            hourly = data["hourly"]
            if "precipitation" not in hourly or "time" not in hourly:
                return None

            times = hourly["time"]
            precip = hourly["precipitation"]

            # Find current time and sum last 3 hours
            now = datetime.now(timezone.utc)
            three_hours_ago = now - timedelta(hours=3)

            total_rainfall = 0.0
            for i, time_str in enumerate(times):
                try:
                    time_obj = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                    if three_hours_ago <= time_obj <= now:
                        total_rainfall += float(precip[i]) if precip[i] else 0.0
                except (ValueError, IndexError):
                    continue

            return total_rainfall
        except Exception as e:
            logger.warning(f"Error fetching rainfall data: {e}")
            return None

    async def get_aqi_data(self, latitude: float, longitude: float) -> Optional[float]:
        """
        Fetch AQI data from WAQI (World Air Quality Index).
        Returns: AQI value, or None if API fails or key not available.
        Note: Requires API key. Falls back gracefully.
        """
        try:
            if not settings.waqi_api_key:
                logger.debug("WAQI_API_KEY not configured, skipping AQI fetch")
                return None

            params = {
                "token": settings.waqi_api_key,
            }
            url = f"{WAQI_BASE}/feed/geo:{latitude};{longitude}/index.json"
            data = await self._fetch_json(url, params)

            if not data or data.get("status") != "ok":
                return None

            aqi_value = data.get("data", {}).get("aqi")
            return float(aqi_value) if aqi_value else None
        except Exception as e:
            logger.warning(f"Error fetching AQI data: {e}")
            return None

    async def get_traffic_speed(self, latitude: float, longitude: float) -> Optional[float]:
        """
        Fetch average speed from TomTom Traffic API.
        Returns: average speed in kmph, or None if API fails.
        Note: Requires API key. Falls back gracefully.
        """
        try:
            if not settings.tomtom_api_key:
                logger.debug("TOMTOM_API_KEY not configured, skipping traffic fetch")
                return None

            params = {
                "key": settings.tomtom_api_key,
                "point": f"{latitude},{longitude}",
            }
            data = await self._fetch_json(TOMTOM_BASE, params)

            if not data or "flowSegmentData" not in data:
                return None

            current_speed = data["flowSegmentData"].get("currentSpeed")
            return float(current_speed) if current_speed else None
        except Exception as e:
            logger.warning(f"Error fetching traffic speed: {e}")
            return None

    async def get_heat_humidity_data(self, latitude: float, longitude: float) -> Optional[Dict[str, float]]:
        """
        Fetch temperature and humidity from Open-Meteo.
        Returns: dict with 'temperature' and 'humidity' keys, or None if API fails.
        """
        try:
            params = {
                "latitude": latitude,
                "longitude": longitude,
                "current": "temperature_2m,relative_humidity_2m",
                "timezone": "Asia/Kolkata",
            }
            data = await self._fetch_json(OPEN_METEO_BASE, params)
            if not data or "current" not in data:
                return None

            current = data["current"]
            return {
                "temperature": float(current.get("temperature_2m", 25)),
                "humidity": float(current.get("relative_humidity_2m", 60)),
            }
        except Exception as e:
            logger.warning(f"Error fetching heat/humidity data: {e}")
            return None

    async def get_zone_disruption_news(self, zone_name: str, pincode: str) -> Optional[str]:
        """
        Fetch recent news about disruptions (curfew, bandh, strike) in zone.
        Returns: disruption keyword if found, or None.
        Note: Requires NewsAPI key. Falls back gracefully.
        """
        try:
            if not settings.news_api_key:
                logger.debug("NEWS_API_KEY not configured, skipping disruption news fetch")
                return None

            params = {
                "q": f"{zone_name} OR {pincode} (curfew OR bandh OR strike OR disruption)",
                "sortBy": "publishedAt",
                "language": "en",
                "apiKey": settings.news_api_key,
            }
            data = await self._fetch_json(NEWS_API_BASE, params)

            if not data or data.get("articles") is None or len(data["articles"]) == 0:
                return None

            # Check first article for disruption keywords
            first_article = data["articles"][0]
            title = str(first_article.get("title", "")).lower()
            description = str(first_article.get("description", "")).lower()
            content = f"{title} {description}"

            disruption_keywords = ["curfew", "bandh", "strike", "shutdown", "closure", "lockdown"]
            for keyword in disruption_keywords:
                if keyword in content:
                    return keyword

            return None
        except Exception as e:
            logger.warning(f"Error fetching zone disruption news: {e}")
            return None


# Global client instance
_api_client: Optional[ExternalAPIClient] = None


async def initialize_api_client():
    """Initialize the global API client."""
    global _api_client
    _api_client = ExternalAPIClient()
    await _api_client.initialize()


async def close_api_client():
    """Close the global API client."""
    global _api_client
    if _api_client:
        await _api_client.close()


def get_api_client() -> ExternalAPIClient:
    """Get the global API client."""
    global _api_client
    if _api_client is None:
        _api_client = ExternalAPIClient()
    return _api_client
