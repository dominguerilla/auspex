# Auspex MCP server — GCP infrastructure (Terraform)

Provisions the hosted MCP server on **Google Cloud Run** per
[ADR 0004](../docs/adr/0004-host-mcp-server-on-aws-postgres.md):
**Cloud Run** (HTTPS, the service) → **Cloud SQL PostgreSQL** (job store) via the
built-in Cloud SQL connector, with **Secret Manager** for credentials and
**Artifact Registry** for the image. See [ARCHITECTURE.md](ARCHITECTURE.md) for
the diagram and a networking/IAM deep dive.

Chosen over AWS App Runner to avoid the ~$32/mo **NAT gateway** App Runner needs
to reach both a private database and the internet — Cloud Run reaches the
internet directly and Cloud SQL via a socket, so there's no VPC/NAT at all.

> **Not apply-tested in this repo** (no GCP credentials here). Treat it as a
> reviewed starting point: run `terraform fmt`, `terraform validate`, and read
> `terraform plan` carefully before `apply`. It creates billable resources.

## What it creates

| Resource | Purpose |
|---|---|
| `google_cloud_run_v2_service.this` | The MCP server (HTTPS, port 8080), scale-to-zero |
| `google_sql_database_instance.postgres` | Cloud SQL Postgres 16 (`db-f1-micro`) |
| `google_cloud_tasks_queue.jobs` | Durable job queue → worker route (docs/adr/0005) |
| `google_artifact_registry_repository.this` | Holds the container image |
| `google_secret_manager_secret.*` | `DATABASE_URL`, `AUSPEX_MCP_TOKEN`, LLM key |
| `google_service_account.runtime` + IAM | Read secrets, connect to Cloud SQL, enqueue tasks |
| `google_project_service.apis` | Enables run / sqladmin / secretmanager / AR / cloudtasks |

## Prerequisites

- Terraform ≥ 1.5 and the `gcloud` CLI.
- A GCP project with **billing enabled**.
- Authenticate:
  ```bash
  gcloud config set project YOUR_PROJECT_ID
  gcloud auth application-default login            # credentials Terraform uses
  gcloud auth configure-docker us-central1-docker.pkg.dev   # for docker push
  ```
- A working Docker to build/push the image (the Linux runtime conflict that
  blocks native Windows does not affect builds or the Linux runtime).

## Remote state (GCS backend)

State lives in a GCS bucket (`versions.tf` → `backend "gcs"`) so it's shared,
locked, and versioned across machines. The bucket must exist **before**
`terraform init` — create it once (it is not managed by this Terraform):

```bash
gcloud storage buckets create gs://auspex-499718-tfstate \
  --location=us-central1 --uniform-bucket-level-access
gcloud storage buckets update gs://auspex-499718-tfstate --versioning
```

Migrating an existing local state into it: `terraform init -migrate-state`.
On a fresh machine, a plain `terraform init` pulls state from the bucket — no
`terraform.tfstate` to copy. (Don't delete the bucket; `terraform destroy` of
the stack won't touch it.)

## Deploy

Cloud Run pulls the image at deploy time, so Artifact Registry must exist and
contain the image **before** the service is created — a two-stage apply.

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars   # then fill in project_id + secrets
terraform init

# 1. Create the Artifact Registry repo (and the API enablement it needs).
terraform apply -target=google_artifact_registry_repository.this

# 2. Build + push the image. Stay in infra/ (terraform output needs it); the
#    Docker build context is the repo root (..).
REPO=$(terraform output -raw artifact_registry_repo)
docker build -t "$REPO/auspex-mcp:latest" ..
docker push "$REPO/auspex-mcp:latest"

# 3. Apply everything else (Cloud SQL takes ~5-10 min, then Cloud Run).
terraform apply
```

Get the URL:

```bash
terraform output -raw service_url      # https://auspex-mcp-xxxx.<region>.run.app
```

Migrations run automatically at container startup (`deploy/entrypoint-mcp.sh` →
`alembic upgrade head`) over the Cloud SQL socket.

## Wire your agent

```yaml
# ~/.hermes/config.yaml
mcp_servers:
  auspex:
    url: "https://auspex-mcp-xxxx.us-central1.run.app/mcp"
    headers:
      Authorization: "Bearer <the same mcp_token>"
```

## Update / tear down

```bash
docker build -t "$REPO/auspex-mcp:v2" .. && docker push "$REPO/auspex-mcp:v2"
terraform apply -var=image_tag=v2

terraform destroy   # remove everything
```

## Notes & caveats

- **Cost:** Cloud Run compute is near-zero when idle; **Cloud SQL `db-f1-micro`
  (~$8–10/mo)** is the floor. No NAT gateway. Add a **budget alert** in GCP
  Billing. (Cheaper still: swap Cloud SQL for serverless Postgres like Neon over
  the public internet — Cloud Run needs no connector for that.)
- **Durable jobs (worker split, docs/adr/0005):** `start_research` persists the
  job to Cloud SQL and enqueues a **Cloud Tasks** task that runs it via
  `/internal/run-job`. Jobs survive instance churn and the service runs
  `min_instances = 0` + `cpu_idle = true` (scale-to-zero) — you pay only for the
  minutes a job is actually running.
- **`worker_base_url`:** Cloud Tasks must POST to the service's public URL. The
  Terraform computes it from the Cloud Run default hostname; after the first
  apply, **verify it matches `terraform output -raw service_url`** and, if not,
  set `worker_base_url` in `terraform.tfvars` and re-apply (otherwise jobs stay
  `queued` because the task 404s).
- **Public endpoint:** `allUsers` has `run.invoker` so the URL is reachable; the
  app enforces its own `AUSPEX_MCP_TOKEN` bearer auth on both `/mcp` and the
  worker route (Cloud Tasks attaches the token).
