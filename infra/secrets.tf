# DATABASE_URL uses the Cloud SQL unix socket the Cloud Run connector mounts at
# /cloudsql/<connection_name> — so there is no host:port, just ?host=<socket>.
resource "google_secret_manager_secret" "database_url" {
  secret_id  = "${var.app_name}-database-url"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "database_url" {
  secret = google_secret_manager_secret.database_url.id
  secret_data = format(
    "postgresql://%s:%s@/auspex?host=/cloudsql/%s",
    var.db_username,
    var.db_password,
    google_sql_database_instance.postgres.connection_name,
  )
}

resource "google_secret_manager_secret" "mcp_token" {
  secret_id  = "${var.app_name}-mcp-token"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "mcp_token" {
  secret      = google_secret_manager_secret.mcp_token.id
  secret_data = var.mcp_token
}

resource "google_secret_manager_secret" "llm_api_key" {
  secret_id  = "${var.app_name}-llm-api-key"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "llm_api_key" {
  secret      = google_secret_manager_secret.llm_api_key.id
  secret_data = var.llm_api_key
}
