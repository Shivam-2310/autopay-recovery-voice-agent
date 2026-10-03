"""SMS dispatch and tracking service via Twilio Messages API or mock."""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
from datetime import UTC, datetime
from typing import Any

from src.db import add_link_event, add_message, mask_phone_number, update_message_status
from src.dial import validate_demo_phone

logger = logging.getLogger("sms")


def generate_payment_token() -> str:
    """Generate a URL-safe random token for the mock payment portal."""
    return secrets.token_urlsafe(16)


def build_clean_sms_body(first_name: str, amount: float, pay_url: str) -> str:
    """Build a clean, compliant SMS body free from any debt or loan recovery triggers.

    Adheres strictly to Twilio Messaging Policy and Indian DLT / US A2P 10DLC
    spam-filtering guidelines. Avoids words like 'loan', 'recovery', 'overdue',
    'debt', or 'collection'.
    """
    template = os.environ.get(
        "SMS_BODY_TEMPLATE",
        "Hi {first_name}, here is your secure link from PayEase: {pay_url}",
    )
    return (
        template
        .replace("{first_name}", str(first_name))
        .replace("{amount}", str(int(amount)))
        .replace("{pay_url}", pay_url)
    )


async def send_payment_link_sms(
    call_id: str,
    customer_id: str,
    first_name: str,
    amount: float,
    to_phone: str | None = None,
) -> dict[str, Any]:
    """Send payment link via Twilio SMS to destination phone (or DEMO_PHONE from .env).

    SAFETY & COMPLIANCE:
    Customer destination phone (DEMO_PHONE) and Twilio sender/service credentials
    (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_MESSAGING_SERVICE_SID, TWILIO_NUMBER)
    are strictly loaded from .env and never hardcoded in application logic.
    Dispatches directly via Twilio Messages API using MessagingServiceSid or From caller ID,
    using HTTP Basic Authentication, with a clean compliant body.
    """
    if to_phone:
        from src.dial import normalize_phone_number
        demo_phone = normalize_phone_number(to_phone)
    else:
        raw_demo = os.environ.get("DEMO_PHONE")
        demo_phone = validate_demo_phone(raw_demo)
    masked_to = mask_phone_number(demo_phone)
    sms_mode = os.environ.get("SMS_MODE", "twilio").lower()
    public_base_url = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")

    token = generate_payment_token()
    pay_url = f"{public_base_url}/pay/{token}"
    body = build_clean_sms_body(first_name, amount, pay_url)

    # 1. Record link created
    add_link_event(token=token, call_id=call_id, event_type="created")

    # 2. Check mode: Twilio vs Mock
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
    messaging_service_sid = os.environ.get("TWILIO_MESSAGING_SERVICE_SID")
    from_number = os.environ.get("TWILIO_NUMBER") or os.environ.get("TWILIO_PHONE_NUMBER")

    if sms_mode == "twilio":
        if not (account_sid and auth_token and (messaging_service_sid or from_number)):
            logger.warning("Twilio credentials missing in .env. Falling back to mock SMS mode.")
            sms_mode = "mock"
        else:
            try:
                import httpx

                url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
                callback_url = f"{public_base_url}/api/twilio/status" if os.environ.get("PUBLIC_BASE_URL") else None

                form_data: dict[str, Any] = {
                    "To": demo_phone,
                    "Body": body,
                }
                if messaging_service_sid:
                    form_data["MessagingServiceSid"] = messaging_service_sid
                elif from_number:
                    form_data["From"] = from_number

                if callback_url:
                    form_data["StatusCallback"] = callback_url

                async with httpx.AsyncClient(timeout=15.0) as http_client:
                    resp = await http_client.post(
                        url,
                        data=form_data,
                        auth=(account_sid, auth_token),
                    )
                    resp_data = resp.json()

                if resp.status_code in (200, 201):
                    msg_sid = resp_data.get("sid", f"SM_{secrets.token_hex(8)}")
                    msg_status = resp_data.get("status", "sent")
                    logger.info(
                        "Twilio SMS dispatched successfully: sid=%s status=%s to=%s",
                        msg_sid,
                        msg_status,
                        masked_to,
                    )

                    add_message(
                        call_id=call_id,
                        sid=msg_sid,
                        to_masked=masked_to,
                        status=msg_status,
                        mode="twilio",
                        error_code=None,
                    )
                    add_link_event(token=token, call_id=call_id, event_type="sent")

                    # If no public callback URL, start background HTTP polling
                    if not callback_url:
                        asyncio.create_task(_poll_twilio_status_http(account_sid, auth_token, msg_sid, call_id, token))

                    return {
                        "status": "success",
                        "sid": msg_sid,
                        "token": token,
                        "url": pay_url,
                        "body": body,
                        "mode": "twilio",
                        "initial_status": msg_status,
                    }
                else:
                    err_code = str(resp_data.get("code") or resp.status_code)
                    err_msg = resp_data.get("message") or resp.text
                    logger.error(
                        "Twilio SMS dispatch failed: HTTP %s, code %s, message: %s",
                        resp.status_code,
                        err_code,
                        err_msg,
                    )
                    error_sid = f"err_{secrets.token_hex(4)}"
                    add_message(
                        call_id=call_id,
                        sid=error_sid,
                        to_masked=masked_to,
                        status="failed",
                        mode="twilio",
                        error_code=err_code,
                    )
                    return {
                        "status": "error",
                        "error": err_msg,
                        "error_code": err_code,
                        "sid": error_sid,
                        "body": body,
                        "mode": "twilio",
                    }

            except Exception as e:
                logger.error("Twilio SMS send exception: %s", e)
                error_sid = f"err_{secrets.token_hex(4)}"
                add_message(
                    call_id=call_id,
                    sid=error_sid,
                    to_masked=masked_to,
                    status="failed",
                    mode="twilio",
                    error_code="SEND_FAILED",
                )
                return {
                    "status": "error",
                    "error": str(e),
                    "sid": error_sid,
                    "body": body,
                    "mode": "twilio",
                }

    # Mock mode (deterministic, simulated lifecycle)
    mock_sid = f"SM_mock_{secrets.token_hex(8)}"
    logger.info("Mock SMS simulated: sid=%s to=%s (url: %s)", mock_sid, masked_to, pay_url)

    add_message(
        call_id=call_id,
        sid=mock_sid,
        to_masked=masked_to,
        status="sent",
        mode="mock",
    )
    add_link_event(token=token, call_id=call_id, event_type="sent")

    # Simulate delivery after 2 seconds
    asyncio.create_task(_simulate_mock_delivery(mock_sid, token, call_id))

    return {
        "status": "success",
        "sid": mock_sid,
        "token": token,
        "url": pay_url,
        "body": body,
        "mode": "mock",
        "initial_status": "sent",
    }


async def _simulate_mock_delivery(sid: str, token: str, call_id: str) -> None:
    """Simulate mock SMS delivery event after short delay."""
    await asyncio.sleep(2.0)
    update_message_status(sid=sid, status="delivered")
    add_link_event(token=token, call_id=call_id, event_type="delivered")
    logger.info("Mock SMS delivered: sid=%s", sid)


async def _poll_twilio_status_http(
    account_sid: str,
    auth_token: str,
    sid: str,
    call_id: str,
    token: str,
    max_duration_sec: int = 120,
) -> None:
    """Poll Twilio message status resource when webhook URL is not publicly reachable."""
    import httpx

    start_time = asyncio.get_event_loop().time()
    poll_interval = 4.0
    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages/{sid}.json"

    async with httpx.AsyncClient(timeout=10.0) as http_client:
        while asyncio.get_event_loop().time() - start_time < max_duration_sec:
            await asyncio.sleep(poll_interval)
            try:
                resp = await http_client.get(url, auth=(account_sid, auth_token))
                if resp.status_code == 200:
                    data = resp.json()
                    status = data.get("status")
                    error_code = str(data.get("error_code")) if data.get("error_code") else None
                    update_message_status(
                        sid=sid,
                        status=status,
                        error_code=error_code,
                        error_message=data.get("error_message"),
                    )

                    if status in ("delivered", "undelivered", "failed"):
                        if status == "delivered":
                            add_link_event(token=token, call_id=call_id, event_type="delivered")
                        break
            except Exception as e:
                logger.debug("Error polling Twilio status for %s: %s", sid, e)


def send_payment_link_sms_sync(
    call_id: str,
    customer_id: str,
    first_name: str,
    amount: float,
    to_phone: str | None = None,
) -> dict[str, Any]:
    """Synchronous version of send_payment_link_sms for in-process agent worker callers.

    SAFETY & COMPLIANCE:
    Customer destination phone (DEMO_PHONE) and Twilio sender/service credentials
    are strictly loaded from .env and never hardcoded in application logic.
    Dispatches directly via Twilio Messages API using MessagingServiceSid or From caller ID.
    """
    if to_phone:
        from src.dial import normalize_phone_number
        demo_phone = normalize_phone_number(to_phone)
    else:
        raw_demo = os.environ.get("DEMO_PHONE")
        demo_phone = validate_demo_phone(raw_demo)
    masked_to = mask_phone_number(demo_phone)
    sms_mode = os.environ.get("SMS_MODE", "twilio").lower()
    public_base_url = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")

    token = generate_payment_token()
    pay_url = f"{public_base_url}/pay/{token}"
    body = build_clean_sms_body(first_name, amount, pay_url)

    add_link_event(token=token, call_id=call_id, event_type="created")

    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
    messaging_service_sid = os.environ.get("TWILIO_MESSAGING_SERVICE_SID")
    from_number = os.environ.get("TWILIO_NUMBER") or os.environ.get("TWILIO_PHONE_NUMBER")

    if sms_mode == "twilio":
        if not (account_sid and auth_token and (messaging_service_sid or from_number)):
            logger.warning("Twilio credentials missing in .env. Falling back to mock SMS mode.")
            sms_mode = "mock"
        else:
            try:
                import requests as req

                url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
                form_data: dict[str, Any] = {
                    "To": demo_phone,
                    "Body": body,
                }
                if messaging_service_sid:
                    form_data["MessagingServiceSid"] = messaging_service_sid
                elif from_number:
                    form_data["From"] = from_number

                callback_url = f"{public_base_url}/api/twilio/status" if os.environ.get("PUBLIC_BASE_URL") else None
                if callback_url:
                    form_data["StatusCallback"] = callback_url

                resp = req.post(url, data=form_data, auth=(account_sid, auth_token), timeout=15.0)
                resp_data = resp.json()

                if resp.status_code in (200, 201):
                    msg_sid = resp_data.get("sid", f"SM_{secrets.token_hex(8)}")
                    msg_status = resp_data.get("status", "sent")
                    logger.info("Twilio SMS dispatched successfully (sync): sid=%s to=%s", msg_sid, masked_to)

                    add_message(
                        call_id=call_id,
                        sid=msg_sid,
                        to_masked=masked_to,
                        status=msg_status,
                        mode="twilio",
                        error_code=None,
                    )
                    add_link_event(token=token, call_id=call_id, event_type="sent")

                    return {
                        "status": "success",
                        "sid": msg_sid,
                        "token": token,
                        "url": pay_url,
                        "body": body,
                        "mode": "twilio",
                        "initial_status": msg_status,
                    }
                else:
                    err_code = str(resp_data.get("code") or resp.status_code)
                    err_msg = resp_data.get("message") or resp.text
                    logger.error("Twilio SMS dispatch failed: HTTP %s, code %s: %s", resp.status_code, err_code, err_msg)
                    error_sid = f"err_{secrets.token_hex(4)}"
                    add_message(
                        call_id=call_id,
                        sid=error_sid,
                        to_masked=masked_to,
                        status="failed",
                        mode="twilio",
                        error_code=err_code,
                    )
                    return {
                        "status": "error",
                        "error": err_msg,
                        "error_code": err_code,
                        "sid": error_sid,
                        "body": body,
                        "mode": "twilio",
                    }
            except Exception as e:
                logger.error("Twilio SMS sync exception: %s", e)
                error_sid = f"err_{secrets.token_hex(4)}"
                add_message(
                    call_id=call_id,
                    sid=error_sid,
                    to_masked=masked_to,
                    status="failed",
                    mode="twilio",
                    error_code="SEND_FAILED",
                )
                return {
                    "status": "error",
                    "error": str(e),
                    "sid": error_sid,
                    "body": body,
                    "mode": "twilio",
                }

    # Mock mode (deterministic, simulated lifecycle)
    mock_sid = f"SM_mock_{secrets.token_hex(8)}"
    logger.info("Mock SMS simulated (sync): sid=%s to=%s", mock_sid, masked_to)
    add_message(
        call_id=call_id,
        sid=mock_sid,
        to_masked=masked_to,
        status="sent",
        mode="mock",
    )
    add_link_event(token=token, call_id=call_id, event_type="sent")

    return {
        "status": "success",
        "sid": mock_sid,
        "token": token,
        "url": pay_url,
        "body": body,
        "mode": "mock",
        "initial_status": "sent",
    }
