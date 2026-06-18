resource "google_cloud_run_v2_service" "this" {
  name     = var.app_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account = google_service_account.runtime.email

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    # Mounts the Cloud SQL unix socket at /cloudsql/<connection_name>.
    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.postgres.connection_name]
      }
    }

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/${var.app_name}/${var.app_name}:${var.image_tag}"

      # Run the MCP entrypoint (migrate, then serve) instead of the image's
      # default web-app CMD — the "one image, two entrypoints" split.
      command = ["bash", "deploy/entrypoint-mcp.sh"]

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = var.cpu
          memory = var.memory
        }
        # CPU always allocated — required so the in-process background research
        # job keeps running after start_research returns its HTTP response.
        cpu_idle = false
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }

      env {
        name  = "LLM_PROVIDER"
        value = var.llm_provider
      }

      # Pin the model only when llm_model is set; otherwise the provider falls
      # back to its built-in default (Anthropic: claude-haiku-4-5).
      dynamic "env" {
        for_each = var.llm_model != "" ? [1] : []
        content {
          name  = var.llm_model_env
          value = var.llm_model
        }
      }

      env {
        name = "DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.database_url.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "AUSPEX_MCP_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.mcp_token.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = var.llm_api_key_env
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.llm_api_key.secret_id
            version = "latest"
          }
        }
      }
    }
  }

  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret_version.database_url,
    google_secret_manager_secret_version.mcp_token,
    google_secret_manager_secret_version.llm_api_key,
    google_secret_manager_secret_iam_member.database_url,
    google_secret_manager_secret_iam_member.mcp_token,
    google_secret_manager_secret_iam_member.llm_api_key,
    google_project_iam_member.cloudsql_client,
  ]

  # The API always returns a service-level `scaling` block populated with
  # defaults (manual_instance_count / min_instance_count = 0). We manage scaling
  # via template.scaling instead, so this top-level block produces a perpetual
  # no-op diff. Ignore it. (Does not affect template.scaling min/max.)
  lifecycle {
    ignore_changes = [scaling]
  }
}

# Make the service publicly reachable. The app does its own bearer-token auth
# (AUSPEX_MCP_TOKEN), so we don't gate the HTTP endpoint behind GCP IAM.
resource "google_cloud_run_v2_service_iam_member" "public" {
  name     = google_cloud_run_v2_service.this.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}
