"""Integration and unit tests for FastAPI backend and endpoints (Step 4)."""

from __future__ import annotations

import os
import pytest
from fastapi.testclient import TestClient

from src.api.main import app, INTERNAL_SECRET
from src.db import init_db, create_call_record, get_call_details


@pytest.fixture(autouse=True)
def setup_test_env():
    os.environ["DEMO_PHONE"] = "+919876543210"
    os.environ["DEMO_OVERRIDE"] = "true"
    os.environ["SMS_MODE"] = "mock"
    os.environ["LIVEKIT_API_KEY"] = "devkey"
    os.environ["LIVEKIT_API_SECRET"] = "secret" * 8
    os.environ["LIVEKIT_URL"] = "wss://livekit.cloud"
    init_db()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_health_endpoint(client: TestClient):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "timestamp" in data


def test_config_endpoint_masks_phone_and_exposes_status(client: TestClient):
    resp = client.get("/api/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "demo_phone_masked" in data
    # Full phone must NEVER be exposed
    assert data["demo_phone_masked"] == "+91XXXXXX3210"
    assert "9876543210" not in data["demo_phone_masked"]
    assert data["demo_override"] is True
    assert data["sms_mode"] == "mock"


def test_customers_endpoint_strictly_omits_birth_year(client: TestClient):
    resp = client.get("/api/customers")
    assert resp.status_code == 200
    customers = resp.json()
    assert len(customers) == 10

    for c in customers:
        # Mandatory privacy constraint
        assert "birth_year" not in c, f"birth_year must NEVER be returned in customer API: {c}"
        assert "id" in c
        assert "name" in c
        assert "amount_due" in c
        assert "do_not_call" in c
        # Masked phone check
        assert "XXXXXX" in c["phone"]


def test_internal_events_protected_by_secret(client: TestClient):
    call_id = "test-call-101"
    create_call_record(call_id=call_id, customer_id="CUST-001", room_name=call_id, source="live")

    payload = {
        "call_id": call_id,
        "event_type": "turn",
        "payload": {"speaker": "agent", "text": "Hello, this is Aanya.", "is_final": True},
    }

    # 1. Missing secret -> 401
    resp_no_auth = client.post("/internal/events", json=payload)
    assert resp_no_auth.status_code == 401

    # 2. Invalid secret -> 401
    resp_bad_auth = client.post("/internal/events", json=payload, headers={"X-Internal-Secret": "wrong_secret"})
    assert resp_bad_auth.status_code == 401

    # 3. Valid secret -> 200
    resp_ok = client.post("/internal/events", json=payload, headers={"X-Internal-Secret": INTERNAL_SECRET})
    assert resp_ok.status_code == 200
    assert resp_ok.json()["status"] == "received"

    # Verify event stored in DB
    details = get_call_details(call_id)
    assert details is not None
    assert len(details["turns"]) >= 1
    assert details["turns"][0]["speaker"] == "agent"


def test_internal_sms_protected_and_dispatches_mock(client: TestClient):
    call_id = "test-call-102"
    create_call_record(call_id=call_id, customer_id="CUST-002", room_name=call_id, source="live")

    sms_payload = {
        "call_id": call_id,
        "customer_id": "CUST-002",
        "first_name": "Pooja",
        "amount": 1850.0,
    }

    # Missing auth -> 401
    assert client.post("/internal/sms", json=sms_payload).status_code == 401

    # Valid auth -> 200 and mock SMS created
    resp = client.post("/internal/sms", json=sms_payload, headers={"X-Internal-Secret": INTERNAL_SECRET})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["mode"] == "mock"
    assert "token" in data
    assert "/pay/" in data["url"]


def test_listen_token_issuance(client: TestClient):
    call_id = "test-call-103"
    resp = client.get(f"/api/calls/{call_id}/listen-token")
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    assert data["room"] == call_id
    assert "livekit" in data["url"]


def test_metrics_and_voices_endpoints(client: TestClient):
    resp_m = client.get("/api/metrics")
    assert resp_m.status_code == 200
    metrics = resp_m.json()
    assert "total_calls" in metrics
    assert "recovery_rate" in metrics

    resp_v = client.get("/api/voices")
    assert resp_v.status_code == 200
    voices = resp_v.json()
    assert len(voices) >= 1
    assert any(v["recommended"] for v in voices)
    assert all("voice_id" in v and "gender" in v and "accent" in v for v in voices)


def test_mock_payment_portal_and_completion(client: TestClient):
    call_id = "test-call-104"
    create_call_record(call_id=call_id, customer_id="CUST-003", room_name=call_id, source="live")

    # Send SMS to generate token
    sms_res = client.post(
        "/internal/sms",
        json={"call_id": call_id, "customer_id": "CUST-003", "first_name": "Vikram", "amount": 3200.0},
        headers={"X-Internal-Secret": INTERNAL_SECRET},
    ).json()

    token = sms_res["token"]

    # View portal HTML
    page_resp = client.get(f"/pay/{token}")
    assert page_resp.status_code == 200
    assert "text/html" in page_resp.headers["content-type"]
    assert "Complete Autopay Recovery" in page_resp.text

    # Complete payment
    pay_resp = client.post(f"/pay/{token}/complete")
    assert pay_resp.status_code == 200
    assert pay_resp.json()["status"] == "paid"

    # Verify call outcome upgraded to recovered
    details = get_call_details(call_id)
    assert details["outcome"] == "recovered"
