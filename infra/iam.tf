# The identity Cloud Run runs as. GCP "assumes" it implicitly — no trust policy
# to write (contrast AWS's two-role trust+permission model).
resource "google_service_account" "runtime" {
  account_id   = "${var.app_name}-run"
  display_name = "Auspex MCP Cloud Run runtime"
}

# Least privilege: allow the runtime SA to read *only* our three secrets.
resource "google_secret_manager_secret_iam_member" "database_url" {
  secret_id = google_secret_manager_secret.database_url.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_secret_manager_secret_iam_member" "mcp_token" {
  secret_id = google_secret_manager_secret.mcp_token.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_secret_manager_secret_iam_member" "llm_api_key" {
  secret_id = google_secret_manager_secret.llm_api_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

# Allow the runtime SA to open Cloud SQL connections (via the connector).
resource "google_project_iam_member" "cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}
