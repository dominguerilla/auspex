# Auspex MCP server — AWS infrastructure (Terraform)

Provisions the hosted MCP server per [docs/adr/0004](../docs/adr/0004-host-mcp-server-on-aws-postgres.md):
**App Runner** (HTTPS, the service) → **RDS PostgreSQL** (job store) via a **VPC
connector**, with **Secrets Manager** for credentials and **ECR** for the image.
Single instance, polished-core v1 (no worker split / scale-to-zero yet).

> **Not apply-tested in this repo.** It was written without AWS credentials, so
> treat it as a reviewed starting point: run `terraform fmt`, `terraform
> validate`, and **read `terraform plan` carefully** before `apply`. It creates
> billable resources.

## What it creates

| Resource | Purpose |
|---|---|
| `aws_db_instance.postgres` | RDS Postgres 16 (`db.t4g.micro`, free-tier-eligible), private |
| `aws_ecr_repository.this` | Holds the container image |
| `aws_secretsmanager_secret.*` | `DATABASE_URL`, `AUSPEX_MCP_TOKEN`, LLM API key |
| `aws_apprunner_service.this` | The MCP server (HTTPS, port 8080), TCP health check |
| `aws_apprunner_vpc_connector.this` | Lets App Runner reach RDS privately |
| IAM roles + security groups | ECR pull, Secrets read, `RDS ← App Runner only` |

## Prerequisites

- Terraform ≥ 1.5, AWS CLI, and configured credentials (`aws configure`).
- A working Docker to build/push the image (the build is a Linux image — the
  Windows libpq/langgraph runtime conflict does **not** affect builds or the
  Linux runtime).

## Deploy

Because App Runner pulls the image at create time, ECR must exist and contain
the image **before** the service is created — so this is a two-stage apply.

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars   # then fill in secrets
terraform init

# 1. Create just the ECR repo first.
terraform apply -target=aws_ecr_repository.this

# 2. Build + push the image. Stay in infra/ (terraform output needs it); the
#    Docker build context is the repo root (..), where the Dockerfile lives.
REGION=us-east-1                              # match aws_region
REPO=$(terraform output -raw ecr_repository_url)
aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "${REPO%/*}"
docker build -t "$REPO:latest" ..
docker push "$REPO:latest"

# 3. Apply everything else (RDS takes ~10 min, then App Runner).
terraform apply
```

Get the URL:

```bash
terraform output service_url      # https://xxxx.<region>.awsapprunner.com
```

## Wire your agent

The cron'd agent calls `<service_url>/mcp` with the bearer token you set in
`mcp_token`. Same MCP client config as the LAN setup, the AWS URL instead of the
Pi's IP, over real HTTPS (managed cert — no `mkcert`):

```yaml
# ~/.hermes/config.yaml
mcp_servers:
  auspex:
    url: "https://xxxx.us-east-1.awsapprunner.com/mcp"
    headers:
      Authorization: "Bearer <the same mcp_token>"
```

## Update the deployment

Push a new image tag and bump `image_tag` (or re-push `latest` and trigger a
deploy):

```bash
docker build -t "$REPO:v2" .. && docker push "$REPO:v2"
terraform apply -var=image_tag=v2
```

## Tear down

```bash
terraform destroy
```

## Notes & caveats

- **Cost:** RDS free tier (12 mo) + ~$5–10/mo for one small App Runner instance
  + LLM pay-per-token. Add an **AWS Budgets** alert.
- **Single instance:** a job survives normally, but if App Runner recycles the
  instance mid-run (deploy/crash) that job is lost — acceptable for a daily
  report the agent can retry. The deferred worker split (0002) fixes this.
- **Migrations** run at container startup via `deploy/entrypoint-mcp.sh`
  (`alembic upgrade head`). Safe at single instance.
- **Default VPC:** `network.tf` uses the account's default VPC/subnets to stay
  small. Swap for a dedicated VPC module if you want isolation.
- **Auth:** one static `AUSPEX_MCP_TOKEN`. Per-agent API keys are deferred
  (0002) — fine while it's just your own agent.
