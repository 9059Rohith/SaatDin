from __future__ import annotations

from pathlib import Path
from typing import Any, List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "SaatDin API"
    app_version: str = "0.2.0"

    base_rate: float = 45.0
    jwt_secret: str = "replace-me-in-env"
    jwt_algorithm: str = "HS256"
    jwt_expiration_minutes: int = 60 * 24

    admin_username: str = "admin"
    admin_password: str = "saatdin-admin"
    admin_session_minutes: int = 12 * 60

    otp_ttl_seconds: int = 300
    otp_max_attempts: int = 5
    otp_send_cooldown_seconds: int = 30
    expose_debug_otp: bool = True

    supabase_db_url: str = ""
    db_pool_min_size: int = 1
    db_pool_max_size: int = 10
    zone_data_path: str = ""

    # External API keys (optional; graceful fallback if missing)
    waqi_api_key: str = ""
    tomtom_api_key: str = ""
    news_api_key: str = ""

    # Fraud scoring (Isolation Forest)
    fraud_scoring_enabled: bool = True
    fraud_model_path: str = ""
    fraud_anomaly_threshold: float = -0.05
    fraud_fail_open: bool = True
    fraud_metrics_log_every_n: int = 25

    # Ambiguous-case LLM fallback (LangGraph + provider failover)
    fraud_llm_fallback_enabled: bool = True
    fraud_llm_ambiguity_margin: float = 0.02
    fraud_llm_trigger_confidence_min: float = 0.35
    fraud_llm_trigger_confidence_max: float = 0.75
    fraud_llm_provider_order: str = "groq,gemini"
    fraud_llm_request_timeout_seconds: int = 8
    fraud_llm_max_retries_per_provider: int = 1
    fraud_llm_max_output_tokens: int = 350
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # Co-claim cluster graph detection
    co_claim_graph_enabled: bool = True
    co_claim_graph_schedule_hours: int = 24
    co_claim_graph_lookback_days: int = 30
    co_claim_graph_time_bucket_minutes: int = 10
    co_claim_graph_min_edge_support: int = 2
    co_claim_graph_recency_half_life_days: float = 7.0
    co_claim_graph_min_cluster_members: int = 3
    co_claim_graph_medium_risk_threshold: float = 0.50
    co_claim_graph_high_risk_threshold: float = 0.75
    co_claim_graph_max_clusters_per_run: int = 250

    # Cell-tower validation signal
    tower_validation_enabled: bool = True
    tower_signal_freshness_minutes: int = 30
    tower_signal_max_neighbors: int = 8
    tower_validation_score_weight: float = 0.12
    tower_validation_adjustment_cap: float = 0.12
    tower_validation_distance_match_km: float = 3.0
    tower_validation_distance_mismatch_km: float = 12.0

    # Motion signal validation
    motion_validation_enabled: bool = True
    motion_signal_freshness_minutes: int = 30
    motion_min_window_seconds: int = 60
    motion_min_sample_count: int = 12
    motion_min_distance_meters: float = 25.0
    motion_max_speed_mps: float = 33.0
    motion_validation_score_weight: float = 0.10
    motion_validation_adjustment_cap: float = 0.10
    motion_signal_retention_days: int = 14

    cors_origins_raw: str = Field(
        default="http://localhost,http://localhost:3000,http://localhost:8080",
        validation_alias="CORS_ORIGINS",
    )
    cors_allow_origin_regex: str = (
        r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"
        r"|^https://saatdin(?:-[A-Za-z0-9-]+)?\.onrender\.com$"
    )

    model_config = SettingsConfigDict(env_file=(".env", "backend/.env"), extra="ignore")

    @property
    def cors_origins(self) -> List[str]:
        return [item.strip() for item in str(self.cors_origins_raw).split(",") if item.strip()]

    @field_validator("fraud_llm_provider_order", mode="before")
    @classmethod
    def _normalize_llm_provider_order(cls, value: Any) -> str:
        if not isinstance(value, str):
            return "groq,gemini"
        parts = [item.strip().lower() for item in value.split(",") if item.strip()]
        if not parts:
            return "groq,gemini"
        deduped: list[str] = []
        for item in parts:
            if item in {"groq", "gemini"} and item not in deduped:
                deduped.append(item)
        return ",".join(deduped or ["groq", "gemini"])

    @field_validator(
        "co_claim_graph_schedule_hours",
        "co_claim_graph_lookback_days",
        "co_claim_graph_time_bucket_minutes",
        "co_claim_graph_min_edge_support",
        "co_claim_graph_min_cluster_members",
        "co_claim_graph_max_clusters_per_run",
        "tower_signal_freshness_minutes",
        "tower_signal_max_neighbors",
        "motion_signal_freshness_minutes",
        "motion_min_window_seconds",
        "motion_min_sample_count",
        "motion_signal_retention_days",
        mode="before",
    )
    @classmethod
    def _coerce_positive_ints(cls, value: Any) -> int:
        parsed = int(value)
        return max(1, parsed)

    @field_validator(
        "co_claim_graph_recency_half_life_days",
        "tower_validation_score_weight",
        "tower_validation_adjustment_cap",
        "tower_validation_distance_match_km",
        "tower_validation_distance_mismatch_km",
        "motion_min_distance_meters",
        "motion_max_speed_mps",
        "motion_validation_score_weight",
        "motion_validation_adjustment_cap",
        mode="before",
    )
    @classmethod
    def _coerce_positive_float(cls, value: Any) -> float:
        parsed = float(value)
        return max(0.1, parsed)

    @field_validator("co_claim_graph_medium_risk_threshold", "co_claim_graph_high_risk_threshold", mode="before")
    @classmethod
    def _coerce_threshold(cls, value: Any) -> float:
        parsed = float(value)
        return max(0.0, min(1.0, parsed))

    @property
    def zone_file_path(self) -> Path:
        if self.zone_data_path:
            return Path(self.zone_data_path)
        candidates = [
            Path(__file__).resolve().parents[2] / "assets" / "data" / "zone_risk_runtime.json",  # backend/assets/data (Docker)
            Path(__file__).resolve().parents[3] / "assets" / "data" / "zone_risk_runtime.json",  # repo-root assets/data (local)
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        # Return the Docker-oriented default path for clearer operational expectations.
        return candidates[0]

    @property
    def fraud_model_file_path(self) -> Path:
        if self.fraud_model_path:
            configured = Path(self.fraud_model_path)
            if configured.is_absolute():
                return configured
            return Path(__file__).resolve().parents[3] / configured
        return Path(__file__).resolve().parents[2] / "models" / "fraud" / "fraud_iforest_latest.joblib"

    @property
    def database_url(self) -> str:
        if not self.supabase_db_url.strip():
            raise ValueError("SUPABASE_DB_URL is required. Example: postgresql://postgres:<password>@<host>:5432/postgres")
        return self.supabase_db_url.strip()

    @property
    def fraud_llm_provider_sequence(self) -> List[str]:
        parts = [item.strip().lower() for item in self.fraud_llm_provider_order.split(",") if item.strip()]
        sequence: list[str] = []
        for item in parts:
            if item in {"groq", "gemini"} and item not in sequence:
                sequence.append(item)
        if sequence:
            return sequence
        return ["groq", "gemini"]

    @property
    def co_claim_high_threshold(self) -> float:
        return max(self.co_claim_graph_medium_risk_threshold, self.co_claim_graph_high_risk_threshold)

    @property
    def co_claim_medium_threshold(self) -> float:
        return min(self.co_claim_graph_medium_risk_threshold, self.co_claim_high_threshold)


settings = Settings()
