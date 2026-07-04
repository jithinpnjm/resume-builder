output "service_url" {
  value = google_cloud_run_v2_service.service.uri
}

output "artifact_registry_repo" {
  value = google_artifact_registry_repository.repo.name
}

output "templates_bucket" {
  value = google_storage_bucket.templates.name
}
