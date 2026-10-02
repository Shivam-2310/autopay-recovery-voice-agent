"""Unit tests for TTS input sanitizer and spoken normalizer (Step 3)."""

from __future__ import annotations

import pytest

from src.sanitizer import sanitize_tts_text


def test_sanitize_strips_markdown():
    text = "Here is your **account** details: _please_ check `#header` and `code`."
    cleaned = sanitize_tts_text(text)
    assert "**" not in cleaned
    assert "_" not in cleaned
    assert "`" not in cleaned
    assert "#" not in cleaned
    assert "account details: please check header and code." in cleaned


def test_sanitize_strips_stage_directions_and_brackets():
    text = "Hello there. [pause] I am happy to help you. *smiles warmly* (chuckles)"
    cleaned = sanitize_tts_text(text)
    assert "[pause]" not in cleaned
    assert "*smiles warmly*" not in cleaned
    assert "(chuckles)" not in cleaned
    assert "Hello there. I am happy to help you." in cleaned


def test_sanitize_strips_speaker_labels():
    text = "Agent: Hello, am I speaking with Priya?\nAI: How can I help?"
    cleaned = sanitize_tts_text(text)
    assert "Agent:" not in cleaned
    assert "AI:" not in cleaned
    assert "Hello, am I speaking with Priya? How can I help?" in cleaned


def test_sanitize_strips_emojis_and_tags():
    text = "Welcome to PayEase! 😊 <tag>Secure payments</tag> for everyone 🎉"
    cleaned = sanitize_tts_text(text)
    assert "😊" not in cleaned
    assert "🎉" not in cleaned
    assert "<tag>" not in cleaned
    assert "</tag>" not in cleaned
    assert "Welcome to PayEase! Secure payments for everyone" in cleaned


def test_sanitize_normalizes_currency_symbols():
    text = "Your pending balance is ₹2,499 from your bank."
    cleaned = sanitize_tts_text(text)
    assert "₹" not in cleaned
    assert "two thousand four hundred ninety-nine rupees" in cleaned


def test_sanitize_replaces_urls():
    text = "You can visit https://payease.mock/pay/abc123xyz to pay."
    cleaned = sanitize_tts_text(text)
    assert "https://" not in cleaned
    assert "link" in cleaned
