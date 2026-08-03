"""Entirely synthetic knowledge base used by the offline demo and tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

from knowledge_librarian.chunking import content_hash, stable_id
from knowledge_librarian.models import SourceDocument, SourceKind

SYNTHETIC_ARTICLES: tuple[tuple[str, str, str], ...] = (
    (
        "Remote Work Handbook",
        "kb://people/remote-work",
        """Northstar Labs supports hybrid work for all permanent employees. Team members may work
remotely up to three days each week after agreeing on anchor days with their manager.

Core collaboration hours are 10:00–15:00 in the employee's local time. Employees receive an
annual home-office allowance of $600 for ergonomic equipment. Expenses must be submitted through
the expense portal within 30 days and include a receipt.

International remote work is limited to 20 business days per calendar year and requires written
People Operations approval before travel.""",
    ),
    (
        "Customer Incident Playbook",
        "kb://support/incidents",
        """A severity-one incident is a complete production outage, confirmed data loss, or a
security event affecting customer information. The on-call engineer must acknowledge a Sev-1
alert within 10 minutes and open an incident channel immediately.

Customer Support posts the first public status update within 20 minutes of confirmation. Updates
continue at least every 30 minutes until service is restored. The incident commander owns the
timeline; the communications lead owns customer messages.

A blameless post-incident review is due within five business days. It must document impact, root
cause, contributing factors, corrective actions, owners, and due dates.""",
    ),
    (
        "Data Retention Standard",
        "kb://security/data-retention",
        """Northstar Labs retains application audit logs for 400 days. Customer workspace content
is retained while the subscription is active and for 30 days after cancellation, unless a legal
hold applies.

Support exports containing customer data must be stored only in the approved encrypted workspace
and deleted within 14 days. Never place customer exports in personal cloud storage or source code
repositories.

Deletion requests are verified by Privacy Operations. Verified requests are completed within
30 days, with backups aging out within an additional 60 days.""",
    ),
    (
        "Product Release Process",
        "kb://engineering/releases",
        """Production releases normally occur Tuesday through Thursday between 09:00 and 14:00
Pacific Time. Every release requires a reviewed change request, passing automated checks, a named
release owner, and a documented rollback plan.

High-risk changes require staged rollout at 5%, 25%, 50%, and 100%. The release owner checks error
rate, latency, and customer support volume for at least 20 minutes at each stage.

Emergency fixes may bypass the normal window with approval from the incident commander. They
still require peer review, automated checks, and a retrospective change record by the next
business day.""",
    ),
    (
        "Travel and Expenses",
        "kb://finance/travel",
        """Travel must be approved before booking. Employees should choose reasonable economy fares
for flights under six hours. Premium economy is permitted for longer flights with manager approval.

The standard meal allowance is $85 per day for domestic travel. Hotel rates should remain below
$250 per night before tax unless the conference hotel or local market makes that impractical.

Expense reports are due within 10 business days after travel. Itemized receipts are required for
individual purchases of $25 or more.""",
    ),
)


class DemoDocumentSource:
    name = "demo"

    async def documents(self, *, cursor: str | None = None) -> AsyncIterator[SourceDocument]:
        del cursor
        updated_at = datetime(2026, 1, 15, 9, 0, tzinfo=UTC)
        for title, uri, body in SYNTHETIC_ARTICLES:
            yield SourceDocument(
                id=stable_id(SourceKind.DEMO.value, uri, prefix="doc_"),
                source=SourceKind.DEMO,
                source_uri=uri,
                title=title,
                content=body,
                content_hash=content_hash(body),
                updated_at=updated_at,
                metadata={"synthetic": True, "audience": "demo"},
            )
