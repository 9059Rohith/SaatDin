from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ..core.config import settings
from .co_claim_graph import generate_co_claim_clusters_snapshot

logger = logging.getLogger(__name__)


class CoClaimClusterMonitor:
    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler(timezone="UTC")
        self._started = False
        self._scheduler_running = False

    async def _run_job(self) -> None:
        try:
            await generate_co_claim_clusters_snapshot()
        except Exception:
            logger.exception("co_claim_cluster_job_failed")

    async def start(self) -> None:
        if self._started:
            return
        if not settings.co_claim_graph_enabled:
            logger.info("co_claim_cluster_monitor_disabled")
            return

        self._scheduler.add_job(
            self._run_job,
            "interval",
            hours=max(1, int(settings.co_claim_graph_schedule_hours)),
            id="co_claim_cluster_refresh",
            replace_existing=True,
        )
        # Initial snapshot can be expensive; keep boot fast and run it in background.
        asyncio.create_task(self._run_job())
        self._scheduler.start()
        self._scheduler_running = True
        self._started = True
        logger.info(
            "co_claim_cluster_monitor_started schedule_hours=%s",
            max(1, int(settings.co_claim_graph_schedule_hours)),
        )

    async def stop(self) -> None:
        if not self._started and not self._scheduler_running:
            return
        if self._scheduler_running:
            self._scheduler.shutdown(wait=False)
            self._scheduler_running = False
        self._started = False
        logger.info("co_claim_cluster_monitor_stopped")


co_claim_cluster_monitor = CoClaimClusterMonitor()
