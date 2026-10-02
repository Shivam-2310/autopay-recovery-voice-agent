# Autopay Recovery Voice Agent

AI-powered outbound voice agent that calls customers with failed autopay payments and helps them resolve the issue — either by sending a payment link or scheduling a callback.

Built for the **Razorpay FDE Agent Studio** assignment.

## Architecture

```
customers.json → dial.py → LiveKit Cloud Room
                              ↕
                           agent.py (AgentSession)
                              │
                    ┌─────────┼─────────┐
                    ↓         ↓         ↓
              Deepgram    LangGraph   ElevenLabs
              STT         Brain       TTS
              (nova-3)    (ReAct)     (turbo v2.5)
                          ↓
                    In-process tools
                          ↓
                    SQLite (outcomes.db)
```

**Telephony path:** Twilio US number → SIP trunk → LiveKit Cloud → Agent

## Stack

| Layer | Technology |
|---|---|
| Telephony | Twilio Elastic SIP Trunk → LiveKit outbound SIP |
| Realtime | LiveKit Cloud + livekit-agents |
| STT | Deepgram (nova-3) |
| TTS | ElevenLabs (eleven_turbo_v2_5) |
| Brain | LangGraph ReAct graph via livekit-plugins-langchain LLMAdapter |
| LLM | Plug-and-play: Groq / Gemini / DeepSeek / any OpenAI-compatible |
| Data | customers.json → SQLite (outcomes + transcripts) |

## Quick Start

### 1. Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- LiveKit Cloud account with outbound SIP trunk configured
- Twilio account with Elastic SIP Trunk
- API keys for: Deepgram, ElevenLabs, and at least one LLM provider

### 2. Install

```bash
git clone <repo-url> && cd voice-agent
uv sync
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env with your credentials
```

Required env vars:

| Variable | Purpose |
|---|---|
| `LIVEKIT_URL` | LiveKit Cloud project URL (wss://...) |
| `LIVEKIT_API_KEY` | LiveKit API key |
| `LIVEKIT_API_SECRET` | LiveKit API secret |
| `SIP_TRUNK_ID` | LiveKit outbound SIP trunk ID |
| `TWILIO_PHONE_NUMBER` | Outbound caller ID (defaults to trunk number) |
| `COMPANY_NAME` | Organization name in prompts/greetings (default: `PayEase`) |
| `LLM_PROVIDER` | `groq` / `gemini` / `deepseek` / `openai_compatible` |
| `GROQ_API_KEY` | Groq API key (if using Groq) |
| `DEEPGRAM_API_KEY` | Deepgram STT key |
| `DEEPGRAM_MODEL` | Deepgram model (default: `nova-3`) |
| `ELEVENLABS_API_KEY` | ElevenLabs TTS key |
| `ELEVENLABS_VOICE_ID` | ElevenLabs voice ID (default: `TX3LPaxmHKxFdv7VOQHJ` - Liam) |
| `ELEVENLABS_ENCODING` | Audio format: `pcm_24000` (lossless, default) or `mp3_44100_128` |

### 4. Verify LLM

```bash
uv run python check_llm.py
```

This confirms your LLM provider returns valid tool calls and reports time-to-first-token.

### 5. Start the Agent Worker

```bash
uv run python src/agent.py dev
```

The worker registers with LiveKit Cloud and waits for dispatched jobs.

### 6. Place a Call

In a **separate terminal**:

```bash
# Dial your test number (uses first customer record):
uv run python -m src.dial --phone +1XXXXXXXXXX

# Dial a specific customer:
uv run python -m src.dial --customer CUST-001

# Dial all 10 customers sequentially:
uv run python -m src.dial --all
```

### 7. Check Results & Analytics

View formatted call outcomes and recovery conversion metrics:

```bash
# Formatted table with executive summary:
uv run python -m src.report

# Filter by a specific customer:
uv run python -m src.report --customer CUST-001

# Export to JSON or CSV:
uv run python -m src.report --format json
uv run python -m src.report --format csv
```

## Plug-and-Play LLM

The LLM is selected **entirely by env vars** — no code changes needed.

| Provider | `LLM_PROVIDER` | Default Model | Key Env |
|---|---|---|---|
| Groq | `groq` | `qwen/qwen3.8-27b` | `GROQ_API_KEY` |
| Gemini | `gemini` | `gemini-2.0-flash` | `GEMINI_API_KEY` |
| DeepSeek | `deepseek` | `deepseek-chat` | `DEEPSEEK_API_KEY` |
| Any OpenAI-compatible | `openai_compatible` | (set `LLM_MODEL`) | `LLM_API_KEY` + `LLM_BASE_URL` |

**Fallbacks:** Set `LLM_FALLBACKS=deepseek,gemini` to auto-retry on timeout/5xx.

## Agent Behavior

1. **Greets** and discloses it's an AI calling from PayEase
2. **Verifies identity** by asking for last 4 digits of card/account
3. **Informs** about the failed payment (amount, date, reason)
4. **Offers resolution**: payment link via SMS or scheduled callback
5. **Handles objections** politely — re-offers once, never pressures
6. **Closes** the call and records the outcome to SQLite

**Guardrails:** "Do not call" requests are honored immediately. Max 2 offers before marking refused. No internal data disclosed.

## Project Structure

```
voice-agent/
├── pyproject.toml          # Dependencies (uv)
├── .env.example            # Env var template
├── customers.json          # 10 fictional customer records
├── check_llm.py            # LLM smoke test (tool call + TTFT)
├── outcomes.db             # SQLite — created at runtime
│
└── src/
    ├── models.py           # Pydantic: Customer, Outcome
    ├── db.py               # SQLite schema + CRUD
    ├── llm.py              # Plug-and-play LLM factory
    ├── prompts.py          # System prompt builder
    ├── tools.py            # @tool: payment link, callback, refuse, end
    ├── graph.py            # LangGraph ReAct brain
    ├── agent.py            # LiveKit agent worker
    ├── dial.py             # Outbound dialer CLI
    └── report.py           # Outcomes & analytics reporter CLI
```

## Twilio + LiveKit SIP Setup

1. **Twilio Console** → Elastic SIP Trunking → Create Trunk
   - Set Termination URI: your Twilio SIP domain
   - Add a phone number to the trunk
   - Note the SIP Auth credentials

2. **LiveKit Cloud** → SIP → Create Outbound Trunk
   - Address: `your-trunk.pstn.twilio.com`
   - Auth username + password from Twilio
   - Numbers: your Twilio phone number (E.164)
   - Copy the trunk ID → `SIP_TRUNK_ID` in `.env`

3. Calls flow: `dial.py` → LiveKit API → SIP trunk → Twilio → PSTN → Customer phone

## License

MIT
