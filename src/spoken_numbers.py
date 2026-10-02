"""Spoken text utilities for currency, dates, numbers, and digit-word normalization."""

from __future__ import annotations

import re
from datetime import date, datetime

_ONES = [
    "", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
    "seventeen", "eighteen", "nineteen",
]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]

_DIGIT_WORDS = {
    "zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3",
    "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
}

_ORDINALS = {
    1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth",
    6: "sixth", 7: "seventh", 8: "eighth", 9: "ninth", 10: "tenth",
    11: "eleventh", 12: "twelfth", 13: "thirteenth", 14: "fourteenth",
    15: "fifteenth", 16: "sixteenth", 17: "seventeenth", 18: "eighteenth",
    19: "nineteenth", 20: "twentieth", 21: "twenty-first", 22: "twenty-second",
    23: "twenty-third", 24: "twenty-fourth", 25: "twenty-fifth",
    26: "twenty-sixth", 27: "twenty-seventh", 28: "twenty-eighth",
    29: "twenty-ninth", 30: "thirtieth", 31: "thirty-first",
}

_MONTHS = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def int_to_words(n: int) -> str:
    """Convert an integer (0 to 999,999) to spoken English words."""
    if n == 0:
        return "zero"
    if n < 0:
        return f"minus {int_to_words(abs(n))}"

    parts = []
    if n >= 100000:
        lakhs = n // 100000
        parts.append(f"{int_to_words(lakhs)} lakh")
        n %= 100000

    if n >= 1000:
        thousands = n // 1000
        parts.append(f"{int_to_words(thousands)} thousand")
        n %= 1000

    if n >= 100:
        hundreds = n // 100
        parts.append(f"{_ONES[hundreds]} hundred")
        n %= 100

    if n >= 20:
        tens = n // 10
        rem = n % 10
        if rem:
            parts.append(f"{_TENS[tens]}-{_ONES[rem]}")
        else:
            parts.append(_TENS[tens])
    elif n > 0:
        parts.append(_ONES[n])

    return " ".join(parts)


def amount_to_spoken_inr(amount: float) -> str:
    """Convert an INR amount (e.g. 2499.00) to spoken English."""
    rupees = int(round(amount))
    return f"{int_to_words(rupees)} rupees"


def date_to_spoken(date_str: str) -> str:
    """Convert an ISO date string (e.g. '2026-09-25') to spoken English ('the twenty-fifth of September')."""
    try:
        dt = datetime.fromisoformat(date_str).date()
        day_ordinal = _ORDINALS.get(dt.day, f"{dt.day}th")
        month_name = _MONTHS[dt.month]
        return f"the {day_ordinal} of {month_name}"
    except Exception:
        return date_str


def normalize_digit_words_to_digits(text: str) -> str:
    """Convert spoken number words ('four five three two') into raw digit strings ('4532').

    Handles spoken numbers that customers might say over phone STT when asked for
    PINs, card numbers, or birth years.
    """
    words = text.lower().split()
    normalized = []
    current_digits = []

    for word in words:
        # Strip punctuation
        clean_word = re.sub(r"[^\w]", "", word)
        if clean_word in _DIGIT_WORDS:
            current_digits.append(_DIGIT_WORDS[clean_word])
        else:
            if current_digits:
                normalized.append("".join(current_digits))
                current_digits = []
            normalized.append(word)

    if current_digits:
        normalized.append("".join(current_digits))

    return " ".join(normalized)
