"""Hand-written skeleton templates for the synthetic corpus.

Every sentence below is authored by hand in fixed pools -- no LLM-generated text, no network.
Bodies avoid literal type-name phrases ("this contract", "this invoice", ...); the generator
still post-checks every rendered body through :func:`strip_label_phrases` and rewrites leaks.
Literal "PKR <amount>" is reserved for salary fact lines so entity cross-checks stay exact.

# allow: SIZE_OK — body is dominated by hand-written sentence-pool data tables; the task
# pins this exact file list, so the pools cannot move to a separate data module.
"""

from __future__ import annotations

import random
import re
from collections.abc import Callable
from dataclasses import dataclass

LABEL_PHRASES: tuple[str, ...] = (
    "this contract",
    "this vendor msa",
    "this invoice",
    "this hr letter",
    "this disciplinary notice",
    "this monthly report",
    "this policy memo",
)
_REWRITE_TARGET = "the attached document"


@dataclass(frozen=True, slots=True)
class RenderContext:
    """Everything a template needs to render one synthetic record."""

    doc_type: str
    level: str
    company: str
    person_names: tuple[str, ...]
    facts: tuple[str, ...]


def strip_label_phrases(text: str) -> str:
    """Rewrite any leaked type-name phrase to a neutral reference."""
    result = text
    for phrase in LABEL_PHRASES:
        result = re.sub(re.escape(phrase), _REWRITE_TARGET, result, flags=re.IGNORECASE)
    return result


def _pick(rng: random.Random, pool: tuple[str, ...]) -> str:
    return rng.choice(pool)


def _render_contract(rng: random.Random, ctx: RenderContext) -> list[str]:
    lead = _pick(
        rng,
        (
            "The parties recorded below confirm their service engagement terms.",
            "Following procurement review, the engagement described here is approved.",
            "Commercial terms were settled during the spring sourcing cycle.",
        ),
    )
    terms = _pick(
        rng,
        (
            "Deliverables are due within thirty days of the effective date.",
            "Payment follows acceptance of the agreed milestones.",
            "Either party may end the arrangement with sixty days written notice.",
        ),
    )
    close = _pick(
        rng,
        (
            "Signed for and on behalf of the parties named above.",
            "Authorised signatories have executed the enclosed pages.",
            "Countersignature returns the file to the records office.",
        ),
    )
    return [
        f"Service Engagement Summary - {ctx.company}",
        lead,
        f"The appointed representative is {ctx.person_names[0]} of {ctx.company}.",
        terms,
        "Schedule of particulars:",
        *ctx.facts,
        close,
    ]


def _render_vendor_msa(rng: random.Random, ctx: RenderContext) -> list[str]:
    scope = _pick(
        rng,
        (
            "The supplier provides managed support for the platform described in schedule A.",
            "Ongoing maintenance covers patching, monitoring, and incident triage.",
            "Support tiers and response targets are listed in the operations annex.",
        ),
    )
    clause = _pick(
        rng,
        (
            "Liability is capped at the fees paid over the trailing twelve months.",
            "Confidential information stays within the receiving organisation.",
            "Termination for convenience requires ninety days notice.",
        ),
    )
    close = _pick(
        rng,
        (
            "Executed by the authorised officers of both organisations.",
            "The annexes form an integral part of the arrangement.",
            "Amendments are valid only when made in writing.",
        ),
    )
    return [
        f"Master Services Arrangement Abstract - {ctx.company}",
        scope,
        f"Supplier liaison: {ctx.person_names[0]}; internal owner: {ctx.person_names[1]}.",
        clause,
        "Recorded particulars:",
        *ctx.facts,
        close,
    ]


def _render_invoice(rng: random.Random, ctx: RenderContext) -> list[str]:
    note = _pick(
        rng,
        (
            "Amounts are payable within thirty days of the billing date.",
            "Late amounts accrue interest at the rate stated in the annex.",
            "Queries on line items go to the billing contact within seven days.",
        ),
    )
    detail = _pick(
        rng,
        (
            "Line items reflect the rates agreed for the current period.",
            "Withholding tax is applied where a valid exemption is absent.",
            "Credit notes issued in the period are already netted off.",
        ),
    )
    total = rng.randint(10_000, 900_000)
    return [
        f"Billing Statement - {ctx.company}",
        f"Billing cycle handled by {ctx.person_names[0]}.",
        note,
        detail,
        f"Total amount due: {total:,}",
        "Reference particulars:",
        *ctx.facts,
        "Issued by the finance shared services desk.",
    ]


def _render_hr_letter(rng: random.Random, ctx: RenderContext) -> list[str]:
    opening = _pick(
        rng,
        (
            "This letter confirms the employment details summarised below.",
            "The human resources office issues the following confirmation.",
            "At the employee's request, the particulars below are certified.",
        ),
    )
    body = _pick(
        rng,
        (
            "Employment continues under the terms signed at onboarding.",
            "Benefits follow the standard staff handbook for the grade.",
            "Probation was completed satisfactorily earlier this year.",
        ),
    )
    close = _pick(
        rng,
        (
            "For verification, contact the human resources office.",
            "Issued on organisational letterhead for official use.",
            "The record keeper retains the original on file.",
        ),
    )
    return [
        f"Personnel Confirmation - {ctx.company}",
        opening,
        f"Employee: {ctx.person_names[0]}. Counter-signed by {ctx.person_names[1]}.",
        body,
        "Certified particulars:",
        *ctx.facts,
        close,
    ]


def _render_disciplinary_notice(rng: random.Random, ctx: RenderContext) -> list[str]:
    finding = _pick(
        rng,
        (
            "An inquiry found a breach of the attendance procedure.",
            "The panel recorded a violation of the acceptable use rules.",
            "Repeated late submissions were confirmed by the supervisor.",
        ),
    )
    action = _pick(
        rng,
        (
            "A first written warning is placed on the personnel file.",
            "Mandatory refresher training must be completed within two weeks.",
            "Conduct is to be reviewed again after ninety days.",
        ),
    )
    appeal = _pick(
        rng,
        (
            "Appeals reach the appeals committee within ten working days.",
            "The decision takes effect on the date of issue.",
            "A copy is retained in the confidential personnel file.",
        ),
    )
    return [
        f"Corrective Action Record - {ctx.company}",
        f"Subject: {ctx.person_names[0]}. Presiding officer: {ctx.person_names[1]}.",
        finding,
        action,
        "Case particulars:",
        *ctx.facts,
        appeal,
    ]


def _render_monthly_report(rng: random.Random, ctx: RenderContext) -> list[str]:
    summary = _pick(
        rng,
        (
            "Operations stayed within the planned envelope for the month.",
            "Throughput matched the forecast within the reported tolerance.",
            "Two minor incidents were logged and closed during the period.",
        ),
    )
    metric = _pick(
        rng,
        (
            "Backlog age improved against the previous period.",
            "System availability met the internal target.",
            "Staff utilisation remained steady across teams.",
        ),
    )
    outlook = _pick(
        rng,
        (
            "Next month focuses on clearing the remaining change queue.",
            "Hiring continues according to the approved plan.",
            "No escalation to the steering group is required.",
        ),
    )
    return [
        f"Periodic Operations Report - {ctx.company}",
        f"Prepared by {ctx.person_names[0]}; reviewed by {ctx.person_names[1]}.",
        summary,
        metric,
        outlook,
        "Appendix of particulars:",
        *ctx.facts,
        "Distribution: department heads and the records office.",
    ]


def _render_policy_memo(rng: random.Random, ctx: RenderContext) -> list[str]:
    purpose = _pick(
        rng,
        (
            "The guidance below takes effect on the first day of next quarter.",
            "Staff are asked to review the updated handling steps.",
            "The change aligns internal practice with the audit findings.",
        ),
    )
    rule = _pick(
        rng,
        (
            "Documents are stored only in the approved repository.",
            "Access requests route through the line manager first.",
            "Removable media remain prohibited for classified work.",
        ),
    )
    close = _pick(
        rng,
        (
            "Questions go to the governance mailbox.",
            "Compliance checks begin the week after publication.",
            "Department heads confirm rollout completion in writing.",
        ),
    )
    return [
        f"Internal Guidance Note - {ctx.company}",
        f"Issued by {ctx.person_names[0]}; acknowledged by {ctx.person_names[1]}.",
        purpose,
        rule,
        "Referenced particulars:",
        *ctx.facts,
        close,
    ]


TEMPLATES: dict[str, Callable[[random.Random, RenderContext], list[str]]] = {
    "contract": _render_contract,
    "vendor_msa": _render_vendor_msa,
    "invoice": _render_invoice,
    "hr_letter": _render_hr_letter,
    "disciplinary_notice": _render_disciplinary_notice,
    "monthly_report": _render_monthly_report,
    "policy_memo": _render_policy_memo,
}
