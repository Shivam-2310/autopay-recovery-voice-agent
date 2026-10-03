"""Smoke test: verify the selected LLM provider returns valid tool calls.

Usage:
    python check_llm.py

Reports:
    - Provider and model
    - Whether a tool call was returned
    - Time-to-first-token (TTFT)
    - Tool call arguments
"""

from __future__ import annotations

import os
import sys
import time

from dotenv import load_dotenv

load_dotenv()


def main() -> None:
    # Import after dotenv so env vars are available
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_core.tools import tool

    from src.llm import get_llm

    # Dummy tool for testing tool-call generation
    @tool
    def send_payment_link(customer_id: str) -> str:
        """Send a payment link to the customer via SMS.

        Args:
            customer_id: The customer's unique identifier.

        Returns:
            Confirmation message.
        """
        return f"Payment link sent to {customer_id}"

    provider = os.environ.get("LLM_PROVIDER", "not set")
    model = os.environ.get("LLM_MODEL", "default")
    print(f"\n{'='*60}")
    print(f"  LLM Smoke Test")
    print(f"  Provider: {provider}")
    print(f"  Model:    {model}")
    print(f"{'='*60}\n")

    try:
        llm = get_llm()
    except Exception as e:
        print(f"❌ Failed to initialize LLM: {e}")
        sys.exit(1)

    print("✅ LLM initialized successfully")

    # Bind tools and invoke
    llm_with_tools = llm.bind_tools([send_payment_link])

    messages = [
        SystemMessage(content="You are a payment recovery agent. Use tools when appropriate."),
        HumanMessage(content="Please send a payment link to customer CUST-001."),
    ]

    print("\n📤 Sending test message with tool binding...")

    # Measure TTFT via streaming
    ttft: float | None = None
    full_response = None

    try:
        start = time.perf_counter()

        # Try streaming first for TTFT measurement
        chunks = []
        for chunk in llm_with_tools.stream(messages):
            if ttft is None:
                ttft = (time.perf_counter() - start) * 1000  # ms
            chunks.append(chunk)

        # Combine chunks to get final response
        if chunks:
            full_response = chunks[0]
            for c in chunks[1:]:
                full_response = full_response + c  # type: ignore[operator]

    except Exception as e:
        # Fallback to non-streaming invoke
        print(f"⚠️  Streaming failed ({e}), falling back to invoke...")
        start = time.perf_counter()
        full_response = llm_with_tools.invoke(messages)
        ttft = (time.perf_counter() - start) * 1000

    if full_response is None:
        print("❌ No response received")
        sys.exit(1)

    # Report results
    print(f"\n⏱️  Time-to-first-token: {ttft:.0f}ms" if ttft else "\n⏱️  TTFT: N/A")

    if hasattr(full_response, "tool_calls") and full_response.tool_calls:
        print(f"✅ Tool call received: {len(full_response.tool_calls)} call(s)")
        for tc in full_response.tool_calls:
            print(f"   📎 {tc['name']}({tc['args']})")
    else:
        print("⚠️  No tool calls in response (LLM may have responded with text instead)")
        if hasattr(full_response, "content"):
            print(f"   Response: {full_response.content[:200]}")

    print(f"\n{'='*60}")
    print("  Smoke test complete")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
