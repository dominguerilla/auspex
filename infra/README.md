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
| `google_cloud_run_v2_service.this` | The MCP server (HTTPS, port 8080), CPU always allocated |
| `google_sql_database_instance.postgres` | Cloud SQL Postgres 16 (`db-f1-micro`) |
| `google_artifact_registry_repository.this` | Holds the container image |
| `google_secret_manager_secret.*` | `DATABASE_URL`, `AUSPEX_MCP_TOKEN`, LLM key |
| `google_service_account.runtime` + IAM | Read secrets, connect to Cloud SQL |
| `google_project_service.apis` | Enables run / sqladmin / secretmanager / AR |

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
- **`cpu_idle = false`** (CPU always allocated) is required so the in-process
  background research job keeps running after `start_research` returns. With
  `min_instances = 0` the instance still scales to zero when idle, so you pay
  only for the minutes it's actually active.
- **Single instance, in-process jobs:** if Cloud Run reclaims the instance
  mid-run, that job is lost — acceptable for a daily report the agent retries;
  the deferred worker split (0002) removes this.
- **Public endpoint:** `allUsers` has `run.invoker` so the URL is reachable; the
  app enforces its own `AUSPEX_MCP_TOKEN` bearer auth.
