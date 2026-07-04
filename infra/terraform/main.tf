terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.40"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
  apis = [
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "secretmanager.googleapis.com",
    "firestore.googleapis.com",
    "storage.googleapis.com",
    "iam.googleapis.com"
  ]
}

resource "google_project_service" "apis" {
  for_each           = toset(local.apis)
  service            = each.value
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "repo" {
  location      = var.region
  repository_id = var.repo_name
  format        = "DOCKER"
  depends_on    = [google_project_service.apis]
}

resource "google_storage_bucket" "templates" {
  name                        = var.bucket_name
  location                    = var.region
  uniform_bucket_level_access = true
  depends_on                  = [google_project_service.apis]
}

resource "google_storage_bucket" "archive" {
  name                        = "${var.project_id}-resume-agent-archive"
  location                    = var.region
  uniform_bucket_level_access = true
  # no lifecycle rule — this data is meant to persist and compound
  depends_on = [google_project_service.apis]
}

resource "google_bigquery_dataset" "analytics" {
  dataset_id = "resume_agent_analytics"
  location   = var.region
  depends_on = [google_project_service.apis]
}

resource "google_bigquery_table" "requirement_events" {
  dataset_id          = google_bigquery_dataset.analytics.dataset_id
  table_id            = "requirement_events"
  deletion_protection = false
  schema = jsonencode([
    { name = "application_id", type = "STRING" },
    { name = "company", type = "STRING" },
    { name = "role_title", type = "STRING" },
    { name = "requirement", type = "STRING" },
    { name = "canonical_id", type = "STRING" },
    { name = "category", type = "STRING" },
    { name = "must_have", type = "BOOL" },
    { name = "user_status", type = "STRING" },
    { name = "matched", type = "BOOL" },
    { name = "source_type", type = "STRING" }, # "application" | "trend_scan"
    { name = "event_date", type = "TIMESTAMP" },
  ])
}

resource "google_bigquery_table" "application_snapshots" {
  dataset_id          = google_bigquery_dataset.analytics.dataset_id
  table_id            = "application_snapshots"
  deletion_protection = false
  schema = jsonencode([
    { name = "application_id", type = "STRING" },
    { name = "company", type = "STRING" },
    { name = "role_title", type = "STRING" },
    { name = "created_at", type = "TIMESTAMP" },
    { name = "finalized_at", type = "TIMESTAMP" },
    { name = "match_pct", type = "FLOAT64" },
    { name = "must_have_count", type = "INT64" },
    { name = "matched_count", type = "INT64" },
    { name = "resume_version", type = "INT64" },
  ])
}

resource "google_bigquery_table" "resume_versions" {
  dataset_id          = google_bigquery_dataset.analytics.dataset_id
  table_id            = "resume_versions"
  deletion_protection = false
  schema = jsonencode([
    { name = "version", type = "INT64" },
    { name = "created_at", type = "TIMESTAMP" },
    { name = "change_reason", type = "STRING" },
    { name = "skills_flat", type = "STRING", mode = "REPEATED" },
    { name = "core_bullet_count", type = "INT64" },
    { name = "total_bullet_count", type = "INT64" },
  ])
}

resource "google_service_account" "runtime" {
  account_id   = "${var.service_name}-runtime"
  display_name = "Resume Agent Cloud Run runtime"
}

resource "google_secret_manager_secret" "gemini_api_key" {
  secret_id = "GEMINI_API_KEY"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_project_iam_member" "secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_project_iam_member" "datastore_user" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_project_iam_member" "bq_data_editor" {
  project = var.project_id
  role    = "roles/bigquery.dataEditor"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_project_iam_member" "bq_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_storage_bucket_iam_member" "archive_access" {
  bucket = google_storage_bucket.archive.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_storage_bucket_iam_member" "templates_access" {
  bucket = google_storage_bucket.templates.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_cloud_run_v2_service" "service" {
  name     = var.service_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.runtime.email
    timeout         = "300s"
    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }
    containers {
      image = var.image
      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
      }
      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "GEMINI_MODEL"
        value = var.gemini_model
      }
      env {
        name  = "RESUME_BUCKET"
        value = google_storage_bucket.templates.name
      }
      env {
        name = "GEMINI_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.gemini_api_key.secret_id
            version = "latest"
          }
        }
      }
    }
  }
  depends_on = [google_project_service.apis]
}

resource "google_cloud_run_v2_service_iam_member" "public" {
  name     = google_cloud_run_v2_service.service.name
  location = google_cloud_run_v2_service.service.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}
