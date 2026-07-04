"""Persistence layer — Firestore in cloud mode, local JSON files in dev.

v3 §5 Definition of Done drives this module: every write happens the moment
the data exists (the API endpoints call save_* immediately after each state
change — after JD analysis, after EACH gap answer, after approval, after
finalize). Nothing is batched or saved-on-exit. The module-level function API
is identical for both backends so route handlers never care which is active.

Firestore layout (database: (default), project from ADC / Cloud Run SA):
  resume_agent/resume                  — current ResumeJSON
  resume_agent_versions/{version}      — ResumeVersion snapshots
  resume_agent_applications/{id}       — ApplicationRecord
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .schemas import (
    ApplicationRecord,
    CatalogEntry,
    MarketFitReport,
    ResumeJSON,
    ResumeVersion,
    StudyGuideEntry,
    UserSettings,
)

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "jithin_resume.json"
STATE_DIR = Path(__file__).resolve().parent.parent / "local_state"
RESUME_PATH = STATE_DIR / "resume.json"
APPS_PATH = STATE_DIR / "applications.json"
VERSIONS_PATH = STATE_DIR / "resume_versions.json"

USE_FIRESTORE = (
    os.environ.get("USE_FIRESTORE", "").lower() in ("1", "true")
    or os.environ.get("APP_MODE", "local") == "cloud"
)

_db = None


def _firestore():
    global _db
    if _db is None:
        from google.cloud import firestore

        _db = firestore.Client()
    return _db


# ---------------------------------------------------------------------------
# Base resume + versions
# ---------------------------------------------------------------------------

_base_resume: ResumeJSON | None = None


def get_base_resume() -> ResumeJSON:
    global _base_resume
    if _base_resume is not None:
        return _base_resume

    if USE_FIRESTORE:
        doc = _firestore().collection("resume_agent").document("resume").get()
        if doc.exists:
            _base_resume = ResumeJSON.model_validate(doc.to_dict())
            return _base_resume
    elif RESUME_PATH.exists():
        _base_resume = ResumeJSON.model_validate(json.loads(RESUME_PATH.read_text()))
        return _base_resume

    _base_resume = ResumeJSON.model_validate(json.loads(FIXTURE_PATH.read_text()))
    return _base_resume


def save_base_resume(resume: ResumeJSON, change_reason: str = "manual edit") -> None:
    global _base_resume
    _base_resume = resume
    if USE_FIRESTORE:
        _firestore().collection("resume_agent").document("resume").set(resume.model_dump())
    else:
        STATE_DIR.mkdir(exist_ok=True)
        RESUME_PATH.write_text(resume.model_dump_json(indent=2))
    _snapshot_version(resume, change_reason)


def _snapshot_version(resume: ResumeJSON, change_reason: str) -> None:
    versions = list_resume_versions()
    version = ResumeVersion(
        version=len(versions) + 1,
        created_at=datetime.now(timezone.utc).isoformat(),
        change_reason=change_reason,
        resume_json_snapshot=resume,
    )
    if USE_FIRESTORE:
        _firestore().collection("resume_agent_versions").document(
            str(version.version)
        ).set(version.model_dump())
    else:
        STATE_DIR.mkdir(exist_ok=True)
        VERSIONS_PATH.write_text(
            json.dumps([v.model_dump() for v in [*versions, version]], indent=2)
        )


def list_resume_versions() -> list[ResumeVersion]:
    if USE_FIRESTORE:
        docs = _firestore().collection("resume_agent_versions").stream()
        versions = [ResumeVersion.model_validate(d.to_dict()) for d in docs]
        return sorted(versions, key=lambda v: v.version)
    if not VERSIONS_PATH.exists():
        return []
    return [ResumeVersion.model_validate(v) for v in json.loads(VERSIONS_PATH.read_text())]


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

_applications_cache: dict[str, ApplicationRecord] | None = None


def _local_applications() -> dict[str, ApplicationRecord]:
    global _applications_cache
    if _applications_cache is None:
        _applications_cache = {}
        if APPS_PATH.exists():
            raw = json.loads(APPS_PATH.read_text())
            _applications_cache = {
                app_id: ApplicationRecord.model_validate(rec) for app_id, rec in raw.items()
            }
    return _applications_cache


def _persist_local_applications() -> None:
    STATE_DIR.mkdir(exist_ok=True)
    apps = _local_applications()
    APPS_PATH.write_text(
        json.dumps({app_id: rec.model_dump() for app_id, rec in apps.items()}, indent=2)
    )


def create_application(record: ApplicationRecord) -> ApplicationRecord:
    record.id = record.id or str(uuid.uuid4())
    save_application(record)
    return record


def save_application(record: ApplicationRecord) -> None:
    if USE_FIRESTORE:
        _firestore().collection("resume_agent_applications").document(record.id).set(
            record.model_dump()
        )
    else:
        _local_applications()[record.id] = record
        _persist_local_applications()


def get_application(application_id: str) -> ApplicationRecord | None:
    if USE_FIRESTORE:
        doc = (
            _firestore()
            .collection("resume_agent_applications")
            .document(application_id)
            .get()
        )
        return ApplicationRecord.model_validate(doc.to_dict()) if doc.exists else None
    return _local_applications().get(application_id)


def list_applications() -> list[ApplicationRecord]:
    if USE_FIRESTORE:
        docs = _firestore().collection("resume_agent_applications").stream()
        records = [ApplicationRecord.model_validate(d.to_dict()) for d in docs]
    else:
        records = list(_local_applications().values())
    return sorted(records, key=lambda r: r.created_at or r.id, reverse=True)


# ---------------------------------------------------------------------------
# Generic keyed-document persistence for catalog / study guides / settings /
# market-fit reports. Same dual-backend pattern; local files are one JSON
# object per collection keyed by document id.
# ---------------------------------------------------------------------------

def _local_file_for(collection: str) -> Path:
    return STATE_DIR / f"{collection}.json"


def _local_collection(name: str) -> dict:
    path = _local_file_for(name)
    return json.loads(path.read_text()) if path.exists() else {}


def _save_local_collection(name: str, data: dict) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    _local_file_for(name).write_text(json.dumps(data, indent=2, ensure_ascii=False))


def _doc_set(collection: str, doc_id: str, payload: dict) -> None:
    if USE_FIRESTORE:
        _firestore().collection(collection).document(doc_id).set(payload)
    else:
        data = _local_collection(collection)
        data[doc_id] = payload
        _save_local_collection(collection, data)


def _doc_get(collection: str, doc_id: str) -> dict | None:
    if USE_FIRESTORE:
        doc = _firestore().collection(collection).document(doc_id).get()
        return doc.to_dict() if doc.exists else None
    return _local_collection(collection).get(doc_id)


def _doc_list(collection: str) -> list[dict]:
    if USE_FIRESTORE:
        return [d.to_dict() for d in _firestore().collection(collection).stream()]
    return list(_local_collection(collection).values())


def get_catalog_entry(canonical_id: str) -> CatalogEntry | None:
    data = _doc_get("resume_agent_catalog", canonical_id)
    return CatalogEntry.model_validate(data) if data else None


def save_catalog_entry(entry: CatalogEntry) -> None:
    _doc_set("resume_agent_catalog", entry.canonical_id, entry.model_dump())


def list_catalog() -> list[CatalogEntry]:
    entries = [CatalogEntry.model_validate(d) for d in _doc_list("resume_agent_catalog")]
    return sorted(entries, key=lambda e: e.priority_score, reverse=True)


def get_study_guide(canonical_id: str) -> StudyGuideEntry | None:
    data = _doc_get("resume_agent_study_guides", canonical_id)
    return StudyGuideEntry.model_validate(data) if data else None


def save_study_guide(entry: StudyGuideEntry) -> None:
    _doc_set("resume_agent_study_guides", entry.canonical_id, entry.model_dump())


def list_study_guides() -> list[StudyGuideEntry]:
    entries = [
        StudyGuideEntry.model_validate(d) for d in _doc_list("resume_agent_study_guides")
    ]
    return sorted(entries, key=lambda e: e.priority_score, reverse=True)


def get_settings() -> UserSettings:
    data = _doc_get("resume_agent_settings", "user")
    return UserSettings.model_validate(data) if data else UserSettings()


def save_settings(settings: UserSettings) -> None:
    _doc_set("resume_agent_settings", "user", settings.model_dump())


def save_market_report(report: MarketFitReport) -> None:
    report_id = report.generated_at or datetime.now(timezone.utc).isoformat()
    _doc_set("resume_agent_market_reports", report_id, report.model_dump())


def latest_market_report() -> MarketFitReport | None:
    reports = [
        MarketFitReport.model_validate(d)
        for d in _doc_list("resume_agent_market_reports")
    ]
    if not reports:
        return None
    return max(reports, key=lambda r: r.generated_at)
