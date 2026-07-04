"""Content-source integration (v3 §7) + URL validation (v3 §6).

- Medium: public per-tag RSS (medium.com/feed/tag/{topic}) — zero auth.
  Recent article titles+links are passed to the Study Guide curator as
  candidate resources.
- LinkedIn/Udemy: no practical free personal API; the curator's search
  prompt is instructed to prefer those domains instead (see
  source_preferences()).
- validate_urls: deterministic link-check before storage; dead links are
  dropped, never shipped.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import httpx

from .schemas import StudyGuideEntry, UserSettings

_UA = {"User-Agent": "resume-agent/1.0 (personal tool)"}


def medium_tag_feed(topic: str, limit: int = 5) -> list[dict]:
    """Recent Medium articles for a tag. Best-effort: failures return []."""
    tag = re.sub(r"[^a-z0-9-]+", "-", topic.lower()).strip("-")
    if not tag:
        return []
    try:
        resp = httpx.get(
            f"https://medium.com/feed/tag/{tag}", headers=_UA, timeout=8,
            follow_redirects=True,
        )
        if resp.status_code != 200:
            return []
        root = ET.fromstring(resp.text)
        items = []
        for item in root.iter("item"):
            title = item.findtext("title") or ""
            link = item.findtext("link") or ""
            if title and link:
                items.append({"title": title, "url": link.split("?")[0], "source": "medium"})
            if len(items) >= limit:
                break
        return items
    except Exception:
        return []


def source_preferences(settings: UserSettings) -> str:
    """Flavor text for the search-grounded curator prompt."""
    parts = []
    if settings.medium_url:
        parts.append(f"prefer medium.com articles (user's profile: {settings.medium_url})")
    if settings.linkedin_url:
        parts.append("prefer linkedin.com/pulse articles when relevant")
    if settings.newsletters:
        parts.append(
            "match the coverage style of these newsletters the user reads: "
            + ", ".join(settings.newsletters)
        )
    if not parts:
        return ""
    return "Source preferences: " + "; ".join(parts) + "."


def validate_urls_in_guide(entry: StudyGuideEntry) -> StudyGuideEntry:
    """HEAD-check every URL; drop dead resource links, blank dead repo links."""
    all_ok = True
    with httpx.Client(timeout=5, follow_redirects=True, headers=_UA) as client:

        def check(url: str) -> bool:
            if not url:
                return False
            try:
                resp = client.head(url)
                if resp.status_code == 405:  # some hosts reject HEAD
                    resp = client.get(url)
                return resp.status_code < 400
            except Exception:
                return False

        for step in entry.steps:
            kept = []
            for resource in step.resources:
                if check(resource.url):
                    resource.url_valid = True
                    kept.append(resource)
                else:
                    all_ok = False  # dropped, not shipped
            step.resources = kept
            if step.hands_on_lab and step.hands_on_lab.repo_url:
                if not check(step.hands_on_lab.repo_url):
                    step.hands_on_lab.repo_url = ""
                    all_ok = False
            if step.sample_project and step.sample_project.repo_url:
                if not check(step.sample_project.repo_url):
                    step.sample_project.repo_url = ""
                    all_ok = False

    entry.url_validation_status = "all_checked" if all_ok else "some_stale"
    return entry
