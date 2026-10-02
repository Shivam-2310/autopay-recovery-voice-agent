"""Deterministic, zero-extra-LLM guardrails for the autopay recovery voice agent.

All guardrails use keyword scanning, regex patterns, state counters, and input/output
normalizers. Every triggered guardrail emits a structured telemetry event:
{"id": int, "name": str, "action": str, "timestamp": str}.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Callable

from src.spoken_numbers import normalize_digit_words_to_digits

logger = logging.getLogger("guardrails")

# ── 1. AI Disclosure & Recording Notice ───────────────────────────────────────
_AI_KEYWORDS = ["ai", "artificial intelligence", "automated", "virtual assistant", "ai assistant"]
_RECORDING_KEYWORDS = ["recorded", "recording", "quality and training", "quality purposes"]


def check_turn_one_disclosure(spoken_text: str) -> tuple[bool, str]:
    """Verify that the agent disclosed AI identity and call recording in the first turn."""
    lower = spoken_text.lower()
    has_ai = any(kw in lower for kw in _AI_KEYWORDS)
    has_recording = any(kw in lower for kw in _RECORDING_KEYWORDS)

    if not (has_ai and has_recording):
        missing = []
        if not has_ai:
            missing.append("AI disclosure")
        if not has_recording:
            missing.append("call recording notice")
        return False, f"Missing {' and '.join(missing)} in first turn"
    return True, "Compliant"


# ── 2. Pre-Verification Output Shield ─────────────────────────────────────────
_CURRENCY_PATTERN = re.compile(
    r"(?:₹|\b(?:rs|inr|rupees?|bucks?)\b|\b\d{3,6}\b)",
    re.IGNORECASE,
)
_DATE_WORDS = re.compile(
    r"\b(?:january|february|march|april|may|june|july|august|september|october|november|december|"
    r"\d{4}-\d{2}-\d{2}|\b\d{1,2}(?:st|nd|rd|th)\b)\b",
    re.IGNORECASE,
)


def shield_unverified_output(text: str, verified: bool) -> tuple[str, bool]:
    """If identity is NOT verified, block any spoken text leaking amounts, currency, or dates.

    Acts as a sentence-level backstop.
    """
    if verified:
        return text, False

    sentences = re.split(r"(?<=[.!?])\s+", text)
    safe_sentences = []
    triggered = False

    for sentence in sentences:
        if _CURRENCY_PATTERN.search(sentence) or _DATE_WORDS.search(sentence):
            triggered = True
            logger.warning("Guardrail 2 (Pre-verification shield) suppressed sensitive sentence: %s", sentence)
        else:
            safe_sentences.append(sentence)

    if triggered and not safe_sentences:
        return (
            "For your security and privacy, I need to confirm your birth year before we discuss any account details.",
            True,
        )

    return (" ".join(safe_sentences).strip(), triggered)


# ── 3. Wrong Party / Voicemail Detector ───────────────────────────────────────
_WRONG_PARTY_PATTERNS = [
    r"\bwrong (?:number|person)\b",
    r"\bnot (?:me|him|her)\b",
    r"\bwho is (?:this|calling)\b",
    r"\bdon'?t know (?:any|who)\b",
    r"\bno one (?:by that name|here)\b",
    r"\bleave a message (?:after|at) the tone\b",
    r"\bplease record your message\b",
]
_WRONG_PARTY_RE = re.compile("|".join(_WRONG_PARTY_PATTERNS), re.IGNORECASE)


def detect_wrong_party(user_text: str) -> bool:
    """Detect if customer indicates we have reached the wrong person or voicemail."""
    return bool(_WRONG_PARTY_RE.search(user_text))


# ── 4. Card / OTP / CVV / PIN Blocker ─────────────────────────────────────────
_CARD_PAN_RE = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
_CVV_OTP_RE = re.compile(
    r"\b(?:cvv|cvc|otp|pin|security code|password)\b\s*(?:is|:)?\s*(\d{3,6})\b",
    re.IGNORECASE,
)


def detect_card_or_credentials(user_text: str) -> tuple[bool, str]:
    """Detect spoken card numbers, CVVs, OTPs, or PINs.

    Normalizes spoken digit-words ('four five three two' -> '4532') before inspection.
    """
    normalized = normalize_digit_words_to_digits(user_text)

    # Check for credit/debit card numbers (13 to 19 digits)
    if _CARD_PAN_RE.search(normalized):
        return True, "Payment card PAN detected"

    # Check for CVV or OTP patterns
    if _CVV_OTP_RE.search(normalized):
        return True, "CVV or OTP credential detected"

    return False, ""


# ── 5. Dispute, Hardship, Abuse & Human Request ──────────────────────────────
_DISPUTE_PATTERNS = [
    r"\b(?:already paid|paid (?:it|yesterday|earlier))\b",
    r"\b(?:never (?:signed up|authorized|agreed))\b",
    r"\b(?:fraud|scam|cheating|rip off|police|court|lawyer|legal action)\b",
]
_HARDSHIP_PATTERNS = [
    r"\b(?:lost my job|unemployed|no money|bankrupt|hospital|medical emergency)\b",
]
_HUMAN_REQUEST_PATTERNS = [
    r"\b(?:talk to a (?:human|person|agent|representative|manager|supervisor))\b",
    r"\b(?:transfer me|connect me to someone)\b",
]
_ESCALATE_RE = re.compile(
    "|".join(_DISPUTE_PATTERNS + _HARDSHIP_PATTERNS + _HUMAN_REQUEST_PATTERNS),
    re.IGNORECASE,
)


def detect_dispute_or_escalation(user_text: str) -> tuple[bool, str]:
    """Detect disputes, hardship claims, or human transfer requests."""
    match = _ESCALATE_RE.search(user_text)
    if match:
        matched_phrase = match.group(0)
        return True, f"Triggered by '{matched_phrase}'"
    return False, ""


# ── 6. Do Not Call (DND) Enforcer ─────────────────────────────────────────────
_DND_PATTERNS = [
    r"\b(?:stop calling|don'?t call (?:me )?again|remove my (?:number|phone)|delete my (?:data|number)|dnd|opt out)\b",
]
_DND_RE = re.compile("|".join(_DND_PATTERNS), re.IGNORECASE)


def detect_do_not_call(user_text: str) -> bool:
    """Detect explicit Do Not Call requests."""
    return bool(_DND_RE.search(user_text))


# ── 7. Anti-Coercion & Max 2 Offers ───────────────────────────────────────────
def check_offer_limit(offers_made: int, max_offers: int = 2) -> bool:
    """Return True if the agent is still permitted to make another resolution offer."""
    return offers_made < max_offers


# ── 8. Prompt Injection & Jailbreak Resistance ────────────────────────────────
_INJECTION_PATTERNS = [
    r"\bignore\s+(?:all\s+)?(?:previous\s+|prior\s+)?(?:your\s+)?instructions\b",
    r"\b(?:repeat|what is|tell me|show me)\s+(?:your\s+)?(?:system\s+)?prompt\b",
    r"\b(?:system prompt|hidden prompt|instructions prompt)\b",
    r"\b(?:reveal (?:your )?instructions|developer mode|dan mode)\b",
    r"\b(?:pretend to be|you are now a)\b",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)


def detect_prompt_injection(user_text: str) -> bool:
    """Detect adversarial prompt-injection or jailbreak phrases."""
    return bool(_INJECTION_RE.search(user_text))


# ── 9. Hard Max Duration (4 Minutes) ──────────────────────────────────────────
MAX_CALL_DURATION_SEC = 240.0  # 4 minutes
WARNING_DURATION_SEC = 225.0   # 3m45s


def check_duration_limit(elapsed_sec: float) -> tuple[bool, bool]:
    """Check if call has reached duration warning or hard cutoff.

    Returns:
        (is_expired, should_warn)
    """
    if elapsed_sec >= MAX_CALL_DURATION_SEC:
        return True, False
    if elapsed_sec >= WARNING_DURATION_SEC:
        return False, True
    return False, False


_PHONE_RE = re.compile(r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")
_DIGIT_STRING_RE = re.compile(r"\b\d{4}\b")  # Potential birth year or 4-digit PIN
_CVV_PIN_RE = re.compile(r"\b(?:cvv|cvc|pin|security code|code)\s*(?:is|:)?\s*(\d{3,6})\b", re.IGNORECASE)


def redact_pii_for_transcript(text: str, birth_year: int | None = None) -> str:
    """Scrub sensitive phone numbers, card numbers, and birth years from persistent text."""
    redacted = text

    # Redact birth year if present
    if birth_year and str(birth_year) in redacted:
        redacted = redacted.replace(str(birth_year), "[YEAR REDACTED]")

    # Redact full phone numbers to +91XXXXXX1234 format
    def _mask_match(m: re.Match) -> str:
        clean = re.sub(r"\D", "", m.group(0))
        if len(clean) >= 10:
            return f"+91XXXXXX{clean[-4:]}"
        return "[PHONE REDACTED]"

    redacted = _PHONE_RE.sub(_mask_match, redacted)

    # Redact card PANs and security codes/CVVs
    redacted = _CARD_PAN_RE.sub("[CARD NUMBER REDACTED]", redacted)
    redacted = _CVV_PIN_RE.sub("[CREDENTIALS REDACTED]", redacted)

    return redacted
