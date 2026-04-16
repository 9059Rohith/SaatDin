from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging

from fastapi import APIRouter, HTTPException, status

from ..core.config import settings
from ..core.db import delete_otp, get_otp, increment_otp_attempts, save_otp
from ..core.phone import normalize_phone_number
from ..core.security import create_access_token, generate_otp, hash_otp
from ..models.schemas import ApiResponse, AuthTokenOut, OtpRequest, OtpVerifyRequest

router = APIRouter(tags=["auth"])
logger = logging.getLogger(__name__)


async def _send_sms(phone_number: str, otp: str) -> None:
    # Integrate Twilio/MSG91 or another SMS provider here.
    _ = (phone_number, otp)


@router.post("/send-otp", response_model=ApiResponse)
async def send_otp(payload: OtpRequest) -> ApiResponse:
    try:
        phone = normalize_phone_number(payload.phoneNumber)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    try:
        logger.info("otp_send_requested phone=%s", phone)
        existing = await get_otp(phone)
        now = datetime.now(timezone.utc)

        if existing:
            last_sent_at = datetime.fromisoformat(existing["last_sent_at"])
            elapsed = (now - last_sent_at).total_seconds()
            if elapsed < settings.otp_send_cooldown_seconds:
                remaining = int(settings.otp_send_cooldown_seconds - elapsed)
                logger.warning("otp_rate_limited phone=%s remaining=%s", phone, remaining)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"OTP recently sent. Try again in {remaining}s",
                )

        otp = generate_otp()
        expires_at = now + timedelta(seconds=settings.otp_ttl_seconds)
        await save_otp(phone, hash_otp(phone, otp), expires_at.isoformat())
        await _send_sms(phone, otp)

        if settings.expose_debug_otp:
            logger.info("otp_debug phone=%s otp=%s", phone, otp)

        data = {"phoneNumber": phone}
        if settings.expose_debug_otp:
            data["debugOtp"] = otp

        logger.info("otp_sent phone=%s", phone)
        return ApiResponse(success=True, data=data, message="OTP sent")
    except HTTPException:
        raise
    except Exception:
        logger.exception("otp_send_failed phone=%s", phone)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OTP service temporarily unavailable",
        )


@router.post("/verify-otp", response_model=ApiResponse)
async def verify_otp(payload: OtpVerifyRequest) -> ApiResponse:
    try:
        phone = normalize_phone_number(payload.phoneNumber)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    try:
        logger.info("otp_verify_requested phone=%s", phone)
        stored = await get_otp(phone)
        if not stored:
            logger.warning("otp_verify_missing_or_expired phone=%s", phone)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired OTP")

        if int(stored["attempts"]) >= settings.otp_max_attempts:
            await delete_otp(phone)
            logger.warning("otp_verify_attempt_limit_exceeded phone=%s", phone)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="OTP attempt limit exceeded")

        expires_at = datetime.fromisoformat(stored["expires_at"])
        if datetime.now(timezone.utc) > expires_at:
            await delete_otp(phone)
            logger.warning("otp_verify_expired phone=%s", phone)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired OTP")

        if hash_otp(phone, payload.otp) != stored["otp_hash"]:
            await increment_otp_attempts(phone)
            logger.warning("otp_verify_invalid phone=%s", phone)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired OTP")

        token = create_access_token(phone)
        await delete_otp(phone)
        logger.info("otp_verify_succeeded phone=%s", phone)
        return ApiResponse(success=True, data=AuthTokenOut(token=token), message="Authenticated")
    except HTTPException:
        raise
    except Exception:
        logger.exception("otp_verify_failed phone=%s", phone)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OTP verification service temporarily unavailable",
        )
