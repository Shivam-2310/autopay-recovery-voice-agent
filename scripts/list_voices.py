"""List available ElevenLabs voices with accent, gender, and use-case details."""

from __future__ import annotations

import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv()


def list_voices() -> None:
    api_key = os.environ.get("ELEVEN_API_KEY") or os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        print("ERROR: ELEVEN_API_KEY (or ELEVENLABS_API_KEY) is not set in environment.", file=sys.stderr)
        sys.exit(1)

    url = "https://api.elevenlabs.io/v1/voices"
    headers = {"xi-api-key": api_key}

    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
        voices = data.get("voices", [])
    except Exception as e:
        print(f"ERROR: Failed to fetch voices from ElevenLabs: {e}", file=sys.stderr)
        sys.exit(1)

    print("\n" + "=" * 90)
    print(f"{'ELEVENLABS AVAILABLE VOICES':^90}")
    print("=" * 90)
    print(f"{'Voice Name':<20} | {'Voice ID':<24} | {'Gender':<8} | {'Accent':<16} | {'Use Case'}")
    print("-" * 90)

    for v in voices:
        name = v.get("name", "Unknown")[:19]
        vid = v.get("voice_id", "")
        labels = v.get("labels", {})
        gender = labels.get("gender", labels.get("accent_gender", "N/A"))[:7]
        accent = labels.get("accent", "N/A")[:15]
        use_case = labels.get("use_case", labels.get("description", "general"))[:18]

        # Highlight Indian-English or neutral voices
        marker = " ★" if "indian" in accent.lower() or "india" in name.lower() else "  "
        print(f"{name:<20}{marker}| {vid:<24} | {gender:<8} | {accent:<16} | {use_case}")

    print("=" * 90)
    print("★ = Recommended Indian-English voice candidate\n")


if __name__ == "__main__":
    list_voices()
