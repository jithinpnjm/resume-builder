"""Deterministic segment generation + v3 plan-integrity enforcement.

The LLM never decides bolding, and never gets to drop bullets or metrics:
- build_segments(): bold every number/metric (NUM_PATTERN) plus newly
  injected keywords, capped at ~3 bold spans — matching the original
  resume's restraint.
- enforce_plan_integrity(): every bullet id must be covered by the plan and
  every original metric must survive; violations fall back to the original
  segments for that bullet. Called by the renderer before anything renders,
  so an unchecked plan can never produce a document.
"""
from __future__ import annotations

import re

from .schemas import ResumeJSON, Segment, TailoringPlan

NUM_PATTERN = (
    r"\$?\d[\d,]*(?:\.\d+)?\s?(?:%|x|\+|K|M|B)?"
    r"(?:\s?[–-]\s?\d[\d,]*(?:\.\d+)?\s?%?)?\+?"
)

MAX_BOLD_SPANS = 3


def build_segments(text: str, extra_bold_phrases: list[str]) -> list[Segment]:
    """Split text into segments, bolding metric matches first, then injected
    keywords, up to MAX_BOLD_SPANS total."""
    spans: list[tuple[int, int]] = []

    for m in re.finditer(NUM_PATTERN, text):
        if len(spans) >= MAX_BOLD_SPANS:
            break
        if m.group().strip():
            spans.append((m.start(), m.end()))

    for phrase in extra_bold_phrases:
        if len(spans) >= MAX_BOLD_SPANS:
            break
        if not phrase.strip():
            continue
        idx = text.find(phrase)
        if idx >= 0 and not any(s <= idx < e for s, e in spans):
            spans.append((idx, idx + len(phrase)))

    spans.sort()
    segments: list[Segment] = []
    cursor = 0
    for start, end in spans:
        if start < cursor:
            continue  # overlapping span; keep the earlier one
        if start > cursor:
            segments.append(Segment(text=text[cursor:start], bold=False))
        segments.append(Segment(text=text[start:end], bold=True))
        cursor = end
    if cursor < len(text):
        segments.append(Segment(text=text[cursor:], bold=False))
    return segments or [Segment(text=text, bold=False)]


def _metrics(text: str) -> list[str]:
    return [m.strip() for m in re.findall(NUM_PATTERN, text) if m.strip()]


def flatten(segments: list[Segment]) -> str:
    return "".join(s.text for s in segments)


def enforce_plan_integrity(resume: ResumeJSON, plan: TailoringPlan) -> None:
    """v3 hard rule, enforced in code, mutating the plan in place:

    1. Every experience bullet id must appear in bullet_plan — missing ids
       get an untouched-passthrough entry appended.
    2. Any changed bullet whose final text lost a metric present in the
       original falls back to the original segments.
    """
    from .schemas import BulletPlanItem

    originals = {b.id: b for exp in resume.experience for b in exp.bullets}
    originals.update({b.id: b for b in resume.accomplishments})

    covered = {item.bullet_id for item in plan.bullet_plan}
    for bullet_id in originals:
        if bullet_id not in covered:
            plan.bullet_plan.append(
                BulletPlanItem(bullet_id=bullet_id, injection_type="none")
            )

    for item in plan.bullet_plan:
        original = originals.get(item.bullet_id)
        if original is None:
            continue
        final_text = (
            flatten(item.final_segments) if item.final_segments else item.final_text
        )
        if not final_text or final_text == original.text:
            continue
        lost = [m for m in _metrics(original.text) if m not in final_text]
        if lost:
            # Metric lost: never render this variant. Fall back to original.
            item.final_text = ""
            item.final_segments = list(original.segments)
            item.injection_type = "none"
