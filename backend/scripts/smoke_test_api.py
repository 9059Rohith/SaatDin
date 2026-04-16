from __future__ import annotations

import json
import os
import random
import re
import sys
from typing import Any

import requests


def fail(message: str) -> None:
    print(f"[FAIL] {message}")
    raise SystemExit(1)


def ok(message: str) -> None:
    print(f"[OK] {message}")


def require_env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or not value.strip():
        fail(f"Missing required environment variable: {name}")
    return value.strip()


def parse_data(payload: dict[str, Any]) -> Any:
    if "success" in payload:
        if payload.get("success") is not True:
            fail(f"API returned success=false: {payload}")
        return payload.get("data")
    return payload


def main() -> None:
    base_url = require_env("API_BASE_URL", "http://127.0.0.1:8000/api/v1").rstrip("/")
    timeout = float(os.getenv("API_TIMEOUT_SECONDS", "20"))

    phone_suffix = random.randint(100000, 999999)
    phone = f"98{phone_suffix}12"

    session = requests.Session()

    # 1) Health checks
    health = requests.get(base_url.replace("/api/v1", "/healthz"), timeout=timeout)
    if health.status_code != 200:
        fail(f"Health endpoint failed: {health.status_code} {health.text}")
    ok("Health endpoint reachable")

    health_api = session.get(f"{base_url}/health", timeout=timeout)
    if health_api.status_code not in (200, 503):
        fail(f"API health endpoint failed: {health_api.status_code} {health_api.text}")
    ok("API health endpoint reachable")

    # 2) Auth flow
    send_resp = session.post(
        f"{base_url}/auth/send-otp",
        json={"phoneNumber": phone},
        timeout=timeout,
    )
    if send_resp.status_code != 200:
        fail(f"send-otp failed: {send_resp.status_code} {send_resp.text}")

    send_data = parse_data(send_resp.json())
    debug_otp = None
    if isinstance(send_data, dict):
        debug_otp = send_data.get("debugOtp")

    otp = os.getenv("TEST_OTP", "").strip() or (debug_otp or "")
    if not otp:
        fail("No OTP available. Set TEST_OTP for production-like env where debug OTP is disabled.")
    ok("OTP requested")

    verify_resp = session.post(
        f"{base_url}/auth/verify-otp",
        json={"phoneNumber": phone, "otp": otp},
        timeout=timeout,
    )
    if verify_resp.status_code != 200:
        fail(f"verify-otp failed: {verify_resp.status_code} {verify_resp.text}")

    verify_data = parse_data(verify_resp.json())
    token = verify_data.get("token") if isinstance(verify_data, dict) else None
    if not token:
        fail("No bearer token in verify-otp response")

    session.headers.update({"Authorization": f"Bearer {token}"})
    ok("OTP verification and token auth successful")

    # 3) Reference endpoints used by frontend
    platforms_resp = session.get(f"{base_url}/platforms", timeout=timeout)
    if platforms_resp.status_code != 200:
        fail(f"platforms failed: {platforms_resp.status_code} {platforms_resp.text}")
    platforms = parse_data(platforms_resp.json())
    if not isinstance(platforms, list) or not platforms:
        fail("platforms response is empty")

    zones_resp = session.get(f"{base_url}/zones", timeout=timeout)
    if zones_resp.status_code != 200:
        fail(f"zones failed: {zones_resp.status_code} {zones_resp.text}")
    zones = parse_data(zones_resp.json())
    if not isinstance(zones, list) or not zones:
        fail("zones response is empty")

    platform_name = str(platforms[0].get("name") or "Blinkit")
    zone_name = str(zones[0].get("name") or "Bellandur")

    plans_resp = session.get(
        f"{base_url}/plans",
        params={"zone": zone_name, "platform": platform_name},
        timeout=timeout,
    )
    if plans_resp.status_code != 200:
        fail(f"plans failed: {plans_resp.status_code} {plans_resp.text}")
    plans = parse_data(plans_resp.json())
    if not isinstance(plans, list) or not plans:
        fail("plans response is empty")

    plan_name = str(plans[0].get("name") or "Basic")

    register_resp = session.post(
        f"{base_url}/register",
        json={
            "phone": phone,
            "name": "Smoke Test User",
            "platformName": platform_name,
            "zone": zone_name,
            "planName": plan_name,
        },
        timeout=timeout,
    )
    if register_resp.status_code not in (200, 201):
        fail(f"register failed: {register_resp.status_code} {register_resp.text}")
    ok("Worker register/upsert successful")

    # 4) Worker + policy endpoints
    for path in ("workers/status", "workers/me", "policy/me"):
        resp = session.get(f"{base_url}/{path}", timeout=timeout)
        if resp.status_code != 200:
            fail(f"{path} failed: {resp.status_code} {resp.text}")
    ok("Worker and policy endpoints successful")

    # 5) Triggers and manual report
    triggers_resp = session.get(
        f"{base_url}/triggers/active",
        params={"zone": zone_name},
        timeout=timeout,
    )
    if triggers_resp.status_code != 200:
        fail(f"triggers/active failed: {triggers_resp.status_code} {triggers_resp.text}")

    zonelock_resp = session.post(
        f"{base_url}/triggers/zonelock/report",
        json={"description": "Smoke test ZoneLock report"},
        timeout=timeout,
    )
    if zonelock_resp.status_code not in (200, 201):
        fail(f"zonelock/report failed: {zonelock_resp.status_code} {zonelock_resp.text}")
    ok("Trigger and ZoneLock report endpoints successful")

    # 6) Claims and escalation
    submit_claim_resp = session.post(
        f"{base_url}/claims/submit",
        json={"claimType": "RainLock", "description": "Smoke test claim"},
        timeout=timeout,
    )
    if submit_claim_resp.status_code not in (200, 201):
        fail(f"claims/submit failed: {submit_claim_resp.status_code} {submit_claim_resp.text}")

    claim_data = parse_data(submit_claim_resp.json())
    claim_id_raw = str((claim_data or {}).get("id", ""))
    match = re.search(r"(\d+)", claim_id_raw)
    if not match:
        fail(f"Could not parse claim id from response: {claim_data}")

    claim_numeric_id = int(match.group(1))
    escalate_resp = session.post(
        f"{base_url}/claims/{claim_numeric_id}/escalate",
        json={"reason": "Smoke test escalation"},
        timeout=timeout,
    )
    if escalate_resp.status_code not in (200, 201):
        fail(f"claims escalate failed: {escalate_resp.status_code} {escalate_resp.text}")

    claims_list_resp = session.get(f"{base_url}/claims", timeout=timeout)
    if claims_list_resp.status_code != 200:
        fail(f"claims list failed: {claims_list_resp.status_code} {claims_list_resp.text}")
    ok("Claim submit/list/escalation endpoints successful")

    print("\nAll smoke tests passed.")
    print(json.dumps({"baseUrl": base_url, "testPhone": phone}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except requests.RequestException as exc:
        fail(f"Network error: {exc}")
