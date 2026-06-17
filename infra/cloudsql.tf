resource "google_sql_database_instance" "postgres" {
  name             = "${var.app_name}-db"
  database_version = "POSTGRES_16"
  region           = var.region

  settings {
    tier = var.db_tier

    # Public IP is how the Cloud Run → Cloud SQL connector reaches the instance.
    # Access is still authenticated (IAM + the connector); the DB is not open to
    # arbitrary clients.
    ip_configuration {
      ipv4_enabled = true
    }

    backup_configuration {
      enabled = true
    }
  }

  deletion_protection = false

  depends_on = [google_project_service.apis]
}

resource "google_sql_database" "auspex" {
  name     = "auspex"
  instance = google_sql_database_instance.postgres.name
}

resource "google_sql_user" "auspex" {
  name     = var.db_username
  instance = google_sql_database_instance.postgres.name
  password = var.db_password
}
