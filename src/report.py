"""Outcomes and recovery reporting CLI for the autopay recovery agent.

Usage:
    python -m src.report
    python -m src.report --customer CUST-001
    python -m src.report --format json
    python -m src.report --format csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db import get_outcomes

CUSTOMERS_FILE = Path(__file__).resolve().parent.parent / "customers.json"


def load_customers_map() -> dict[str, dict]:
    if not CUSTOMERS_FILE.exists():
        return {}
    with open(CUSTOMERS_FILE) as f:
        data = json.load(f)
    return {c["id"]: c for c in data if "id" in c}


def generate_report(customer_id: str | None = None) -> list[dict]:
    outcomes = get_outcomes(customer_id=customer_id)
    customers_map = load_customers_map()

    enriched = []
    for o in outcomes:
        cid = o["customer_id"]
        cinfo = customers_map.get(cid, {})
        enriched.append(
            {
                "call_id": o["id"],
                "customer_id": cid,
                "name": cinfo.get("name", "Unknown"),
                "phone": cinfo.get("phone", "N/A"),
                "bank": cinfo.get("bank_name", "N/A"),
                "amount_due": cinfo.get("amount_due", 0.0),
                "disposition": o["disposition"],
                "notes": o.get("notes", ""),
                "transcript": o.get("transcript", ""),
                "timestamp": o.get("timestamp", ""),
            }
        )
    return enriched


def print_table(records: list[dict]) -> None:
    if not records:
        print("\nNo recovery call outcomes found in outcomes.db.\n")
        return

    print("\n" + "=" * 105)
    print(f"{'AUTOPAY RECOVERY CALL OUTCOMES REPORT':^105}")
    print("=" * 105)
    header = (
        f"{'ID':<4} | {'Cust ID':<9} | {'Customer Name':<16} | {'Bank':<14} | "
        f"{'Amount':<10} | {'Disposition':<19} | {'Notes'}"
    )
    print(header)
    print("-" * 105)

    total_amount = 0.0
    recovered_amount = 0.0
    stats: dict[str, int] = {}

    for r in records:
        amt = r["amount_due"]
        total_amount += amt
        disp = r["disposition"]
        stats[disp] = stats.get(disp, 0) + 1
        if disp == "payment_link_sent":
            recovered_amount += amt

        notes_truncated = r["notes"][:28] + ("..." if len(r["notes"]) > 28 else "")
        print(
            f"{r['call_id']:<4} | {r['customer_id']:<9} | {r['name']:<16} | {r['bank']:<14} | "
            f"₹{amt:<9,.0f} | {disp:<19} | {notes_truncated}"
        )

    print("=" * 105)

    # Executive Summary
    total_calls = len(records)
    print("\n📊 EXECUTIVE SUMMARY:")
    print(f"  • Total Call Records:     {total_calls}")
    print(f"  • Payment Links Sent:     {stats.get('payment_link_sent', 0)} (₹{recovered_amount:,.2f})")
    print(f"  • Callbacks Scheduled:    {stats.get('callback_requested', 0)}")
    print(f"  • Explicit Refusals:      {stats.get('refused', 0)}")
    print(f"  • Voicemail / No Answer:  {stats.get('voicemail', 0) + stats.get('no_answer', 0)}")
    print(f"  • Errors / Incomplete:    {stats.get('error', 0)}")

    if total_calls > 0:
        rec_rate = (stats.get("payment_link_sent", 0) / total_calls) * 100
        print(f"  • Link Delivery Rate:     {rec_rate:.1f}%\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Autopay Recovery Outcomes Reporter")
    parser.add_argument("--customer", type=str, help="Filter by customer ID (e.g. CUST-001)")
    parser.add_argument(
        "--transcripts",
        action="store_true",
        help="Print conversation transcripts for all matched calls",
    )
    parser.add_argument(
        "--format",
        choices=["table", "json", "csv"],
        default="table",
        help="Output format (default: table)",
    )
    args = parser.parse_args()

    records = generate_report(customer_id=args.customer)

    if args.format == "json":
        print(json.dumps(records, indent=2))
    elif args.format == "csv":
        if not records:
            return
        writer = csv.DictWriter(sys.stdout, fieldnames=list(records[0].keys()))
        writer.writeheader()
        writer.writerows(records)
    else:
        print_table(records)
        if args.transcripts:
            for r in records:
                if r.get("transcript"):
                    print(f"\n--- TRANSCRIPT: Call #{r['call_id']} ({r['customer_id']} - {r['name']}) ---")
                    print(r["transcript"])
                    print("-" * 60)


if __name__ == "__main__":
    main()
