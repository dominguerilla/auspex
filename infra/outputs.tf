output "service_url" {
  description = "Base HTTPS URL of the MCP server. Agents call <service_url>/mcp."
  value       = google_cloud_run_v2_service.this.uri
}

output "artifact_registry_repo" {
  description = "Push the image here (then bump image_tag if not 'latest')."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${var.app_name}"
}

output "cloudsql_connection_name" {
  description = "Cloud SQL instance connection name (PROJECT:REGION:INSTANCE)."
  value       = google_sql_database_instance.postgres.connection_name
}
