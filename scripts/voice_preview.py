"""Synthesize a sample spoken line to a local mp3 file using ElevenLabs."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
import requests
from dotenv import load_dotenv

load_dotenv()

DEFAULT_SAMPLE = (
    "Hello, this is Aanya, an automated AI assistant calling from PayEase on a recorded line. "
    "I am calling regarding a notification on your recurring autopay account."
)


def preview_voice(voice_id: str, text: str, output_path: Path) -> None:
    api_key = os.environ.get("ELEVEN_API_KEY") or os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        print("ERROR: ELEVEN_API_KEY (or ELEVENLABS_API_KEY) is not set in environment.", file=sys.stderr)
        sys.exit(1)

    model_id = os.environ.get("ELEVEN_MODEL") or os.environ.get("ELEVENLABS_MODEL", "eleven_turbo_v2_5")
    stability = float(os.environ.get("ELEVEN_STABILITY") or os.environ.get("ELEVENLABS_STABILITY", "0.50"))
    similarity = float(os.environ.get("ELEVEN_SIMILARITY") or os.environ.get("ELEVENLABS_SIMILARITY", "0.75"))
    style = float(os.environ.get("ELEVEN_STYLE", "0.0"))
    speed = float(os.environ.get("ELEVEN_SPEED", "1.0"))

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    payload = {
        "text": text,
        "model_id": model_id,
        "voice_settings": {
            "stability": stability,
            "similarity_boost": similarity,
            "style": style,
            "speed": speed,
            "use_speaker_boost": True,
        },
    }

    print(f"Synthesizing sample with voice {voice_id} (model: {model_id})...")
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(response.content)
        print(f"✓ Saved voice preview audio to: {output_path} ({len(response.content)} bytes)")
    except Exception as e:
        print(f"ERROR: Speech synthesis failed: {e}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="ElevenLabs voice preview generator")
    parser.add_argument(
        "--voice-id",
        type=str,
        default=os.environ.get("ELEVEN_VOICE_ID") or os.environ.get("ELEVENLABS_VOICE_ID", "TX3LPaxmHKxFdv7VOQHJ"),
        help="ElevenLabs Voice ID (default from env)",
    )
    parser.add_argument(
        "--text",
        type=str,
        default=DEFAULT_SAMPLE,
        help="Text to synthesize",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("recordings/preview.mp3"),
        help="Output mp3 file path (default: recordings/preview.mp3)",
    )
    args = parser.parse_args()

    preview_voice(args.voice_id, args.text, args.out)


if __name__ == "__main__":
    main()
