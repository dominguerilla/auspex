data "google_project" "this" {}

# Durable job queue (docs/adr/0005): start_research enqueues here; Cloud Tasks
# POSTs each task to the Cloud Run worker route.
resource "google_cloud_tasks_queue" "jobs" {
  name     = "${var.app_name}-jobs"
  location = var.region

  depends_on = [google_project_service.apis]
}

locals {
  # Cloud Tasks must POST to the service's own public URL. Cloud Run v2's default
  # hostname is deterministic from the project number, so it can be computed
  # without a dependency cycle (referencing the service's own .uri would be one).
  # Override via worker_base_url if your service URL differs — verify against
  # `terraform output service_url` after the first apply.
  worker_base_url = (
    var.worker_base_url != "" ? var.worker_base_url
    : "https://${var.app_name}-${data.google_project.this.number}.${var.region}.run.app"
  )
}
