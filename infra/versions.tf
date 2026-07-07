terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  # Remote state in GCS: shared across machines, locked, and versioned. The
  # bucket must already exist (create it once with gcloud — see infra/README.md).
  # Backend config can't use variables, so the bucket name is literal.
  backend "gcs" {
    bucket = "auspex-499718-tfstate"
    prefix = "auspex-mcp"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
