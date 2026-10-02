# PayEase — Autopay Recovery Voice Agent

[![FastAPI](https://img.shields.io/badge/FastAPI-0.142.2-009688?logo=fastapi)](https://fastapi.tiangolo.com)
[![LiveKit](https://img.shields.io/badge/LiveKit-Agents%201.8-002B49?logo=livekit)](https://livekit.io)
[![Deepgram](https://img.shields.io/badge/Deepgram-Nova--3-13EF93?logo=deepgram)](https://deepgram.com)
[![ElevenLabs](https://img.shields.io/badge/ElevenLabs-Turbo%20v2.5-F3A530)](https://elevenlabs.io)
[![LangGraph](https://img.shields.io/badge/LangGraph-ReAct%20Brain-FF6F00)](https://langchain.com)
[![React](https://img.shields.io/badge/React-19%20%2B%20TS%20%2B%20Tailwind-61DAFB?logo=react)](https://react.dev)

An enterprise-grade, deterministic, and compliance-hardened outbound voice agent designed for **Razorpay Autopay payment recovery**. Built with **LiveKit WebRTC + Twilio SIP + Deepgram + ElevenLabs + LangGraph**, featuring a real **FastAPI backend**, an executive **React dashboard**, full SMS payment link tracking, and a 10-persona synthetic evaluation suite.

---

## 1. System Architecture

```
                          ┌────────────────────────────────────────────────────────┐
                          │                FASTAPI BACKEND :8000                   │
                          │   - SQLite (WAL, busy_timeout)                         │
                          │   - WebSocket Telemetry Hub (/ws)                      │
                          │   - Twilio Messages API & Status Webhooks              │
                          │   - LiveKit Subscribe-Only Token Generator             │
                          │   - Mock Razorpay Payment Portal (/pay/{token})        │
                          └───────────▲───────────────────────────────▲────────────┘
                                      │                               │
                       HTTP /internal/events & /internal/sms          │ WebSockets / REST
                       (Protected by X-Internal-Secret)               │ LiveKit Token
                                      │                               │
┌─────────────────────────────────────▼───────┐   ┌───────────────────▼────────────────┐
│           LIVEKIT AGENT WORKER              │   │            REACT DASHBOARD         │
│  - Deepgram STT (tuned endpointing: 350ms)  │   │  - Vite + React + TS + Tailwind    │
│  - ElevenLabs TTS (Indian-English persona)  │   │  - Overview KPI Cards & Queue      │
│  - Spoken TTS Sanitizer (zero markdown)     │   │  - Real-time Streaming Transcript  │
│  - LangGraph ReAct brain                    │   │  - Guardrail & Tool Chips Feed     │
│  - 11 Deterministic Safety Guardrails       │   │  - WebRTC Live Listen Audio Player │
│  - Stateful in-process tools                │   │  - SMS Timeline & Audit History    │
└─────────────────────▲───────────────────────┘   └────────────────────────────────────┘
                      │
           SIP Trunk Outbound Call
                      │
            ┌─────────▼─────────┐
            │  LiveKit SIP Core │
            └─────────▲─────────┘
                      │
            ┌─────────▼─────────┐
            │ Twilio SIP Trunk  │
            └─────────▲─────────┘
                      │ PSTN
            ┌─────────▼─────────┐
            │    DEMO_PHONE     │ (Strict E.164 lock: +91XXXXXX1234)
            └───────────────────┘
```

### Architectural Guardrails & Separation of Concerns
1. **Worker Security Decoupling**: The agent worker **never** accesses SQLite directly and holds zero Twilio credentials. All telemetry, turns, guardrails, and SMS requests pass through `POST /internal/events` and `POST /internal/sms` using a shared header `X-Internal-Secret`.
2. **Zero Financial Leakage**: Amounts, due dates, failure reasons, and bank names are withheld from model context and prompts before identity verification. `verify_identity` returns them in spoken format (*"two thousand four hundred ninety-nine rupees"*).
3. **Deterministic Guardrails**: Disputing, DND, and prompt injection use keyword/regex backstops without secondary per-turn LLM calls.
4. **First Terminal Outcome Wins**: Once a call outcome is finalized (`recovered`, `link_sent`, `scheduled`, `escalate`, `declined`, `verification_failed`, `wrong_party`), subsequent tool calls cannot overwrite it.

---

## 2. The 11 Guardrails

| # | Guardrail Name | Enforcement Mechanism | Failure Action |
|---|---|---|---|
| **1** | **Turn 1 AI & Recording Disclosure** | Mandatory template in first turn greeting | Verified at startup; fails if omitted |
| **2** | **Pre-Verification Output Shield** | Sentence-level regex suppressing ₹ amounts & dates | Replaces with birth year verification prompt |
| **3** | **Wrong Party / Voicemail Defense** | Keyword detection ("wrong number", "not here", "tone") | Invokes `end_call(wrong_party)`, reveals zero data |
| **4** | **Card / OTP / CVV / PIN Blocker** | Digit-word normalizer (`four five three` → `453`) + PAN/CVV regex | Interrupts politely; redirects to secure link; redacts transcript |
| **5** | **Dispute / Hardship / Escalation** | Deterministic regex backstop + prompt instructions | Invokes `escalate(reason)`; transfers to senior specialist |
| **6** | **Do Not Call (DND)** | Regex for "stop calling", "remove my number", "DND" | Sets `do_not_call=1` in DB; terminates politely |
| **7** | **Anti-Coercion & Max 2 Offers** | State counter `offers_made < 2` | Prohibits legal threats or pressure; ends gracefully |
| **8** | **Prompt Injection Resistance** | Pattern matcher (`ignore instructions`, `system prompt`) | Rejects adversarial jailbreaks immediately |
| **9** | **Hard Max Duration (4 min)** | Timer warning at 3m45s; hard termination at 4m00s | Wraps up conversation courteously |
| **10** | **Truth in Delivery** | SMS API response gate | Says *"sent"* ONLY if SMS API accepted; else offers callback |
| **11** | **PII Redaction in Persistence** | Regex scrubbing phone numbers, card PANs, CVVs, birth years | Stored in SQLite as `+91XXXXXX1234`, `[YEAR REDACTED]` |

---

## 3. Environment Variables Configuration

Copy `.env.example` to `.env` and configure your credentials:

```bash
cp .env.example .env
```

| Variable | Description | Example / Default |
|---|---|---|
| `DEMO_PHONE` | **Strict destination for all calls & SMS** (Strict E.164) | `+919876543210` |
| `DEMO_OVERRIDE` | Bypass 09:00–20:00 IST window & 1 attempt/day rule | `true` |
| `TWILIO_NUMBER` | Outbound caller ID on your Twilio trunk | `+14155550199` |
| `TWILIO_ACCOUNT_SID` | Twilio Account SID | `AC...` |
| `TWILIO_AUTH_TOKEN` | Twilio Auth Token | `...` |
| `LIVEKIT_URL` | LiveKit Cloud WebSocket URL | `wss://voice-agent-xxxx.livekit.cloud` |
| `LIVEKIT_API_KEY` | LiveKit API Key | `API...` |
| `LIVEKIT_API_SECRET` | LiveKit API Secret | `...` |
| `SIP_TRUNK_ID` | LiveKit Outbound SIP Trunk ID | `ST_...` |
| `DEEPGRAM_API_KEY` | Deepgram STT API Key | `...` |
| `DEEPGRAM_MODEL` | Deepgram model | `nova-3` |
| `DEEPGRAM_ENDPOINTING_MS`| Speech turn endpointing (optimized for phone) | `350` |
| `ELEVEN_API_KEY` | ElevenLabs TTS API Key | `...` |
| `ELEVEN_VOICE_ID` | Voice candidate ID (Aanya) | `TX3LPaxmHKxFdv7VOQHJ` |
| `ELEVEN_MODEL` | Low-latency synthesis model | `eleven_turbo_v2_5` |
| `LLM_PROVIDER` | LLM choice (`groq`, `gemini`, `deepseek`) | `groq` |
| `GROQ_API_KEY` | Groq API Key (if using Groq) | `gsk_...` |
| `INTERNAL_SECRET` | Secret token between worker and FastAPI | `secret_internal_token_change_me` |
| `SMS_MODE` | SMS delivery mode (`mock` or `twilio`) | `mock` |
| `PUBLIC_BASE_URL` | Optional tunnel URL for live webhook testing | `http://localhost:8000` |

---

## 4. Voice Catalog & Preview

To explore and sample available ElevenLabs voices with accent and gender metadata:

```bash
# List available voices and candidates
uv run python scripts/list_voices.py

# Synthesize an audio preview sample to preview.mp3
uv run python scripts/voice_preview.py --voice TX3LPaxmHKxFdv7VOQHJ --text "Hello, this is Aanya calling from PayEase."
```

---

## 5. Three-Terminal Run Guide

### Terminal 1: FastAPI Backend
```bash
uv run uvicorn src.api.main:app --host 127.0.0.1 --port 8000 --reload
```
*Initializes SQLite schema, WebSocket stream on `ws://127.0.0.1:8000/ws`, REST endpoints, and mock Razorpay payment portal.*

### Terminal 2: LiveKit Agent Worker
```bash
uv run python src/agent.py dev
```
*Pre-warms Silero VAD, registers with LiveKit Cloud as `autopay-recovery`, and listens for outbound call dispatches.*

### Terminal 3: React Dashboard
```bash
cd frontend
npm run dev
```
*Starts Vite development server on `http://127.0.0.1:5173` with proxy to the FastAPI backend.*

---

## 6. Live Demo Verification Checklist (4 Scenarios)

Before placing a live call, ensure `DEMO_PHONE` in `.env` is set to your verified physical phone number.

### Scenario 1: Successful Bank Retry (`recovered`)
1. In the Dashboard Overview, find **Aarav Sharma (CUST-001)** (Reason: `insufficient_funds`).
2. Click **Call**. Your phone will ring.
3. Answer and confirm: *"Yes, speaking."*
4. When asked for birth year, say: *"Nineteen eighty-eight"* (`1988`).
5. Aanya explains the failed debit of ₹2,499 from HDFC Bank due to insufficient funds.
6. Say: *"Please retry debiting my account now."*
7. **Verification**: Aanya confirms success, records `recovered` (via mandate retry), and cleanly disconnects.

### Scenario 2: SMS Payment Link Settlement (`link_sent` → `recovered via link`)
1. Click **Call** on **Priya Patel (CUST-002)** (Reason: `mandate_expired`).
2. Answer and verify with: *"Nineteen ninety-two"* (`1992`).
3. Aanya explains that the mandate has expired and offers a secure link.
4. Say: *"Please send me the link via SMS."*
5. Aanya calls `send_payment_link()`, confirms dispatch, and says goodbye.
6. Open the **SMS & Links** tab on the dashboard, click **Open Portal** on the link, and click **Pay Now**.
7. **Verification**: Call outcome immediately upgrades to `recovered (via link)`.

### Scenario 3: Wrong Party / Privacy Defense (`wrong_party`)
1. Click **Call** on **Ananya Reddy (CUST-006)**.
2. Answer and immediately say: *"You have the wrong number, there is nobody by that name here."*
3. **Verification**: Aanya apologizes, reveals **zero** account or bank details, invokes `end_call(wrong_party)`, and hangs up.

### Scenario 4: Transaction Dispute (`escalate`)
1. Click **Call** on **Rohan Mehta (CUST-003)**.
2. Answer and say: *"I already paid this amount yesterday! This is complete fraud, I dispute this charge!"*
3. **Verification**: Aanya's deterministic guardrail triggers immediately, invokes `escalate(reason)`, flags the account for senior support review, and disconnects.

---

## 7. Synthetic 10-Persona Simulation Suite

To verify all 10 customer journeys without placing telephone calls:

```bash
uv run python -m src.simulate
```

### Simulation Results Table

| Cust ID | Customer Name | Bank | Amount | Failure Reason | Persona Behavior | Terminal Outcome | Note |
|---|---|---|---|---|---|---|---|
| **CUST-001** | Aarav Sharma | HDFC Bank | ₹2,499 | `insufficient_funds` | Verifies birth year, requests retry | `recovered` | Mandate retry succeeded |
| **CUST-002** | Priya Patel | ICICI Bank | ₹1,299 | `mandate_expired` | Verifies birth year, retry fails, link sent | `link_sent` | Payment link sent via SMS |
| **CUST-003** | Rohan Mehta | State Bank of India | ₹4,999 | `bank_decline` | Disputes transaction as fraud | `escalate` | Escalated: Triggered by dispute |
| **CUST-004** | Sneha Gupta | Kotak Mahindra Bank | ₹799 | `bank_timeout` | Verifies birth year, retry recovers | `recovered` | Mandate retry succeeded |
| **CUST-005** | Vikram Singh | Axis Bank | ₹3,499 | `mandate_expired` | Offers credit card digits (blocked) | `link_sent` | Payment link sent via SMS |
| **CUST-006** | Ananya Reddy | Punjab National Bank | ₹1,599 | `bank_decline` | Wrong party answered | `wrong_party` | Wrong party answered |
| **CUST-007** | Karthik Nair | Yes Bank | ₹5,999 | `insufficient_funds` | Financial hardship (job loss) | `escalate` | Escalated: Triggered by hardship |
| **CUST-008** | Meera Joshi | Bank of Baroda | ₹999 | `bank_timeout` | Wrong birth year twice | `verification_failed` | Identity verification failed |
| **CUST-009** | Arjun Desai | IndusInd Bank | ₹2,199 | `insufficient_funds` | Requests follow-up callback | `scheduled` | Callback scheduled: tomorrow 3 PM |
| **CUST-010** | Divya Iyer | Federal Bank | ₹1,899 | `mandate_expired` | Demands Do Not Call | `declined` | Customer requested DND |

---

## 8. Reporting CLI

```bash
# Print executive terminal summary table
uv run python -m src.report

# Filter by customer ID
uv run python -m src.report --customer CUST-001

# Export structured JSON (strictly excludes birth_year)
uv run python -m src.report --format json

# Export CSV for audit
uv run python -m src.report --format csv

# Print conversation transcripts
uv run python -m src.report --transcripts
```

---

## 9. SMS & Telephony Notes

1. **Twilio Trial Account Constraints**: If using a Twilio trial account, outbound SMS will contain the prefix *"Sent from your Twilio trial account -"* and can only be dispatched to verified caller IDs.
2. **Indian DLT Compliance**: Telecommunications regulations in India mandate Distributed Ledger Technology (DLT) template registration for commercial SMS and strict 09:00–20:00 calling windows. `DEMO_OVERRIDE=true` allows full assessment outside operating hours.
3. **Webhook Reachability**: To test live Twilio SMS status callbacks from a physical phone, set `PUBLIC_BASE_URL` to an ngrok or cloudflared tunnel pointing to port 8000.

---

## 10. Production Roadmap

1. **Razorpay Webhooks Integration**: Ingest real-time `payment.failed`, `subscription.paused`, and `invoice.expired` webhooks to queue calls automatically.
2. **TRAI / DND Registry Scrubbing**: Integrate real-time National Do Not Call (NDNC) registry checks prior to SIP trunk dialing.
3. **Adaptive Cadence Engine**: Dynamic retry scheduling (e.g. 1st retry at T+4h, 2nd at T+24h, 3rd at T+72h) aligned with RBI recurring mandate guidelines.
4. **PCI-DSS L1 Compliant Links**: Integration with Razorpay Payment Links API generating short URLs (`rzp.io/l/...`) with automated token expiry and webhook callbacks.
5. **Automated LLM Evaluation**: Continuous evaluation of conversation transcripts against empathy, clarity, safety, and conciseness benchmarks.
6. **Enterprise Authentication**: Role-based access control (RBAC) with SSO on dashboard routes and audit logging for customer data access.
