"""Outcomes and recovery reporting CLI for the autopay recovery voice agent.

Queries the multi-table schema (`calls`, `customers_state`, `link_events`, `messages`)
and generates executive summary metrics and per-customer recovery logs.

Features:
- CLI formatted table, JSON, and CSV exports
- Detailed metrics: recovery via retry vs link, escalations, callbacks, refusal breakdown
- Strict privacy redaction: phone numbers masked (+91XXXXXX1234), birth year omitted everywhere
- Distinguishes live telephony vs simulated persona calls

Usage:
    python -m src.report
    python -m src.report --customer CUST-001
    python -m src.report --format json
    python -m src.report --format csv
    python -m src.report --transcripts
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db import get_calls, get_metrics, init_db


def generate_report(customer_id: str | None = None, limit: int = 200) -> list[dict]:
    """Retrieve and format call records from the multi-table schema."""
    init_db()
    calls = get_calls(limit=limit, customer_id=customer_id)

    enriched = []
    for c in calls:
        # Strictly ensure birth_year is NOT present
        record = {
            "call_id": c["id"],
            "customer_id": c["customer_id"],
            "name": c.get("customer_name") or "Unknown",
            "phone_masked": c.get("phone_masked") or "+91XXXXXX1234",
            "bank": c.get("bank_name") or "N/A",
            "amount_due": float(c.get("amount_due") or 0.0),
            "source": c.get("source") or "live",
            "status": c.get("status") or "completed",
            "outcome": c.get("outcome") or "pending",
            "duration_sec": float(c.get("duration_sec") or 0.0),
            "note": c.get("note") or "",
            "started_at": c.get("started_at") or "",
            "transcript": c.get("transcript") or "",
        }
        enriched.append(record)

    return enriched


def print_table(records: list[dict]) -> None:
    """Print executive terminal summary and formatted call log table."""
    metrics = get_metrics()

    print("\n" + "=" * 115)
    print(f"{'AUTOPAY RECOVERY SYSTEM — EXECUTIVE METRICS & AUDIT REPORT':^115}")
    print("=" * 115)

    print(f"  • Total Recovery Calls:      {metrics['total_calls']}")
    print(f"  • Total Recovered:           {metrics['total_recovered']} (Recovery Rate: {metrics['recovery_rate']}%)")
    print(f"    └─ Direct Bank Retries:    {metrics['recovered_count']}")
    print(f"    └─ Link Settlements (Paid):{metrics['paid_links_count']}")
    print(f"  • SMS Payment Links Sent:    {metrics['link_sent_count']}")
    print(f"  • Callbacks Scheduled:       {metrics['scheduled_count']}")
    print(f"  • Escalated to Specialist:   {metrics['escalated_count']}")
    print(f"  • Explicitly Declined:       {metrics['declined_count']}")
    print(f"  • Average Call Duration:     {metrics['average_duration_sec']}s")
    print("-" * 115)

    if not records:
        print(f"{'No call logs recorded yet in outcomes.db.':^115}\n")
        return

    header = (
        f"{'Call ID':<18} | {'Cust ID':<9} | {'Customer Name':<16} | {'Bank':<10} | "
        f"{'Amount':<9} | {'Src':<4} | {'Outcome':<18} | {'Note'}"
    )
    print(header)
    print("-" * 115)

    for r in records:
        cid_display = r["call_id"][:17]
        name_display = r["name"][:15]
        bank_display = r["bank"][:9]
        amt = r["amount_due"]
        src = "SIM" if r["source"] == "simulated" else "LIVE"
        outcome_disp = r["outcome"]
        note_disp = r["note"][:22] + ("..." if len(r["note"]) > 22 else "")

        print(
            f"{cid_display:<18} | {r['customer_id']:<9} | {name_display:<16} | {bank_display:<10} | "
            f"₹{amt:<8,.0f} | {src:<4} | {outcome_disp:<18} | {note_disp}"
        )

    print("=" * 115 + "\n")


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
        # Ensure birth_year is nowhere in output
        clean_records = [{k: v for k, v in r.items() if k != "birth_year"} for r in records]
        print(json.dumps(clean_records, indent=2))
    elif args.format == "csv":
        if not records:
            return
        fieldnames = [k for k in records[0].keys() if k not in ("birth_year", "transcript")]
        writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in records:
            writer.writerow({k: r[k] for k in fieldnames})
    else:
        print_table(records)
        if args.transcripts:
            for r in records:
                if r.get("transcript"):
                    print(f"\n--- TRANSCRIPT: Call {r['call_id']} ({r['customer_id']} - {r['name']}) ---")
                    print(r["transcript"])
                    print("-" * 70)


if __name__ == "__main__":
    main()
