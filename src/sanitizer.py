"""TTS Input Sanitizer and Spoken Text Normalizer.

Ensures that any text passed to ElevenLabs TTS contains strictly speakable English
words, stripping all markdown, stage directions, asterisks, brackets, emojis, HTML/XML
tags, speaker labels, URLs, and converting any un-normalized currency symbols or numbers
into natural spoken words.
"""

from __future__ import annotations

import re
from collections.abc import AsyncGenerator, AsyncIterable
from typing import Any

from src.spoken_numbers import amount_to_spoken_inr, date_to_spoken

# Regex patterns for cleanup
_SPEAKER_LABELS_RE = re.compile(r"^(?:agent|customer|ai|human|user|assistant):\s*", re.IGNORECASE | re.MULTILINE)
_BRACKETED_DIRECTIONS_RE = re.compile(r"\[[^\]]*\]|\([^\)]*(?:pause|laugh|sigh|chuckle|breath|groan)[^\)]*\)", re.IGNORECASE)
_STAGE_ACTION_RE = re.compile(r"\*(?:smiles?|laughs?|chuckles?|sighs?|giggles?|clears throat|pauses?)[^*]*\*", re.IGNORECASE)
_MARKDOWN_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*|__([^_]+)__")
_MARKDOWN_ITALIC_RE = re.compile(r"(?<!\w)\*([^*]+)\*(?!\w)|(?<!\w)_([^_]+)_(?!\w)")
_MARKDOWN_CODE_RE = re.compile(r"`([^`]+)`")
_MARKDOWN_CHARS_RE = re.compile(r"[*_~`#>]")
_TAGS_RE = re.compile(r"<[^>]+>")
_URLS_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_EMOJI_RE = re.compile(
    r"[\U00010000-\U0010ffff]|[\uD800-\uDBFF][\uDC00-\uDFFF]|"
    r"[\u2600-\u27BF]|[\uE000-\uF8FF]",
    flags=re.UNICODE,
)
_BULLETS_RE = re.compile(r"^\s*[-*•\d+.]+\s+", re.MULTILINE)
_RUPEES_CURRENCY_RE = re.compile(r"(?:₹|rs\.?|inr)\s*(\d+(?:,\d+)*(?:\.\d+)?)", re.IGNORECASE)

# Patterns for internal meta-instructions or tool return leakage
_INTERNAL_JSON_RE = re.compile(r"\{[^{}]*\"status\"[^{}]*\}", re.DOTALL)
_INTERNAL_BRACKET_RE = re.compile(r"\[INTERNAL[^\]]*\]\s*", re.IGNORECASE)
_ACCOUNT_DATA_PREAMBLE_RE = re.compile(r"Account data:\s*Autopay payment of[^.]*\.\s*", re.IGNORECASE)
_INTERNAL_LEAKAGE_RE = re.compile(
    r"(?:The payment link has been dispatched to the customer's registered phone number via SMS\.?|"
    r"Inform them that the link is valid for 24 hours[^.]*\.?|"
    r"Now politely explain this failure[^.]*\.?|"
    r"Politely ask the customer to re-confirm[^.]*\.?|"
    r"For privacy and security reasons, inform the customer[^.]*\.?|"
    r"Confirm this success with the customer[^.]*\.?|"
    r"Explain this to the customer and offer[^.]*\.?|"
    r"Say a brief, courteous goodbye[^.]*\.?|"
    r"VERIFICATION_\w+|LINK_SENT_\w+|RETRY_\w+|CALLBACK_\w+|ESCALATION_\w+)",
    re.IGNORECASE,
)


def sanitize_tts_text(text: str) -> str:
    """Sanitize and normalize text before speech synthesis."""
    if not text:
        return ""

    cleaned = text

    # Strip raw JSON tool returns, bracketed internal statuses, or account data preambles
    cleaned = _INTERNAL_JSON_RE.sub("", cleaned)
    cleaned = _INTERNAL_BRACKET_RE.sub("", cleaned)
    cleaned = _ACCOUNT_DATA_PREAMBLE_RE.sub("", cleaned)
    cleaned = _INTERNAL_LEAKAGE_RE.sub("", cleaned)

    # 1. Remove speaker labels (e.g. 'Agent: ', 'AI: ')
    cleaned = _SPEAKER_LABELS_RE.sub("", cleaned)

    # 2. Remove markdown bullet points and headers
    cleaned = _BULLETS_RE.sub("", cleaned)

    # 3. Remove URLs
    cleaned = _URLS_RE.sub("link", cleaned)

    # 4. Remove stage directions: [pause], *smiles*, (chuckles)
    cleaned = _BRACKETED_DIRECTIONS_RE.sub("", cleaned)
    cleaned = _STAGE_ACTION_RE.sub("", cleaned)

    # 5. Extract content from markdown bold, italic, code
    cleaned = _MARKDOWN_BOLD_RE.sub(lambda m: m.group(1) or m.group(2) or "", cleaned)
    cleaned = _MARKDOWN_ITALIC_RE.sub(lambda m: m.group(1) or m.group(2) or "", cleaned)
    cleaned = _MARKDOWN_CODE_RE.sub(r"\1", cleaned)

    # 6. Remove HTML/XML tags
    cleaned = _TAGS_RE.sub("", cleaned)

    # 7. Remove emojis
    cleaned = _EMOJI_RE.sub("", cleaned)

    # 8. Remove any remaining markdown syntax characters (*, _, `, ~, #, >)
    cleaned = _MARKDOWN_CHARS_RE.sub("", cleaned)

    # 8. Normalize currency symbols (₹2,499 -> two thousand four hundred ninety-nine rupees)
    def _replace_inr(m: re.Match) -> str:
        amt_str = m.group(1).replace(",", "")
        try:
            return amount_to_spoken_inr(float(amt_str))
        except ValueError:
            return m.group(0)

    cleaned = _RUPEES_CURRENCY_RE.sub(_replace_inr, cleaned)

    # 9. Clean up extra whitespace and newlines
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    return cleaned


async def tts_sanitizer_transform(stream: AsyncIterable[str]) -> AsyncGenerator[str, None]:
    """Streaming text transform callable compatible with LiveKit AgentSession `tts_text_transforms`.

    Optimized for ultra-low latency: yields on sentence boundaries (. ! ? \n)
    AND on natural clause boundaries (, ; :) once at least 3 words have accumulated,
    allowing ElevenLabs to synthesize and speak the beginning of sentences without waiting
    for the entire multi-clause generation to complete.
    """
    buffer = ""
    async for chunk in stream:
        buffer += chunk
        should_yield = False

        if any(punct in chunk for punct in (".", "!", "?", "\n")):
            should_yield = True
        elif any(punct in chunk for punct in (",", ";", ":")):
            # Only split on comma/semicolon if at least 3 words have accumulated and not inside a number (e.g. 2,499)
            words = buffer.strip().split()
            if len(words) >= 3 and not re.search(r"\d,\d*$", buffer):
                should_yield = True

        if should_yield:
            sanitized = sanitize_tts_text(buffer)
            if sanitized:
                yield sanitized + " "
            buffer = ""

    # Flush remainder
    if buffer:
        sanitized = sanitize_tts_text(buffer)
        if sanitized:
            yield sanitized
