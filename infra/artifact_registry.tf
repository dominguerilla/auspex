resource "google_artifact_registry_repository" "this" {
  location      = var.region
  repository_id = var.app_name
  format        = "DOCKER"
  description   = "Auspex MCP server container images"

  depends_on = [google_project_service.apis]
}
