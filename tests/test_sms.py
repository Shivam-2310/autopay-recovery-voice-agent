"""Unit and integration tests for SMS payment link and tracking (Step 5)."""

from __future__ import annotations

import asyncio
import os
import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.db import create_call_record, get_call_details, get_conn, init_db
from src.sms import generate_payment_token, send_payment_link_sms


@pytest.fixture(autouse=True)
def setup_env():
    os.environ["DEMO_PHONE"] = "+919876543210"
    os.environ["DEMO_OVERRIDE"] = "true"
    os.environ["SMS_MODE"] = "mock"
    init_db()


@pytest.mark.anyio
async def test_generate_payment_token():
    t1 = generate_payment_token()
    t2 = generate_payment_token()
    assert len(t1) >= 16
    assert t1 != t2


@pytest.mark.anyio
async def test_send_payment_link_sms_mock_lifecycle():
    call_id = "sms-call-test-1"
    create_call_record(call_id=call_id, customer_id="CUST-001", room_name=call_id, source="live")

    res = await send_payment_link_sms(
        call_id=call_id,
        customer_id="CUST-001",
        first_name="Aarav",
        amount=2499.0,
    )

    assert res["status"] == "success"
    assert res["mode"] == "mock"
    assert "token" in res
    assert "/pay/" in res["url"]

    # Verify link events in DB
    token = res["token"]
    with get_conn() as conn:
        events = conn.execute(
            "SELECT event_type FROM link_events WHERE token = ? ORDER BY id ASC", (token,)
        ).fetchall()
        event_types = [e["event_type"] for e in events]
        assert "created" in event_types
        assert "sent" in event_types

    # Wait for mock delivery simulation
    await asyncio.sleep(2.2)
    with get_conn() as conn:
        events_after = conn.execute(
            "SELECT event_type FROM link_events WHERE token = ? ORDER BY id ASC", (token,)
        ).fetchall()
        types_after = [e["event_type"] for e in events_after]
        assert "delivered" in types_after


@pytest.mark.anyio
async def test_send_payment_link_sms_rejects_invalid_demo_phone():
    os.environ["DEMO_PHONE"] = "invalid_phone"
    with pytest.raises(SystemExit):
        await send_payment_link_sms(
            call_id="sms-call-test-2",
            customer_id="CUST-002",
            first_name="Rohan",
            amount=1500.0,
        )


def test_link_full_funnel_tracking():
    with TestClient(app) as client:
        call_id = "sms-funnel-call"
        create_call_record(call_id=call_id, customer_id="CUST-003", room_name=call_id, source="live")

        # 1. Dispatch link via internal endpoint
        res = client.post(
            "/internal/sms",
            json={"call_id": call_id, "customer_id": "CUST-003", "first_name": "Priya", "amount": 3499.0},
            headers={"X-Internal-Secret": os.environ.get("INTERNAL_SECRET", "secret_internal_token_change_me")},
        ).json()
        token = res["token"]

        # 2. Click link (customer opens SMS link)
        page_resp = client.get(f"/pay/{token}")
        assert page_resp.status_code == 200

        with get_conn() as conn:
            click_event = conn.execute(
                "SELECT event_type FROM link_events WHERE token = ? AND event_type = 'clicked'", (token,)
            ).fetchone()
            assert click_event is not None

        # 3. Pay link (customer completes payment)
        pay_resp = client.post(f"/pay/{token}/complete")
        assert pay_resp.status_code == 200

        # Outcome upgraded to recovered with note 'recovered via link'
        details = get_call_details(call_id)
        assert details["outcome"] == "recovered"
        assert details["note"] == "recovered via link"


def test_twilio_status_webhook_tracking():
    with TestClient(app) as client:
        call_id = "twilio-status-call"
        create_call_record(call_id=call_id, customer_id="CUST-004", room_name=call_id, source="live")

        # Directly send status webhook payload
        resp = client.post(
            "/api/twilio/status",
            data={
                "MessageSid": "SM_webhook_test_123",
                "MessageStatus": "delivered",
                "ErrorCode": "",
                "ErrorMessage": "",
            },
        )
        assert resp.status_code == 200
        assert "text/xml" in resp.headers["content-type"]
