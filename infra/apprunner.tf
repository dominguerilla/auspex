resource "aws_apprunner_vpc_connector" "this" {
  vpc_connector_name = "${var.app_name}-vpc"
  subnets            = data.aws_subnets.default.ids
  security_groups    = [aws_security_group.apprunner.id]
}

resource "aws_apprunner_service" "this" {
  service_name = var.app_name

  source_configuration {
    authentication_configuration {
      access_role_arn = aws_iam_role.apprunner_access.arn
    }

    # Deploy explicitly via `terraform apply` / image pushes, not on every ECR push.
    auto_deployments_enabled = false

    image_repository {
      image_identifier      = "${aws_ecr_repository.this.repository_url}:${var.image_tag}"
      image_repository_type = "ECR"

      image_configuration {
        port          = "8080"
        start_command = "bash deploy/entrypoint-mcp.sh"

        runtime_environment_variables = {
          PORT         = "8080"
          LLM_PROVIDER = var.llm_provider
        }

        runtime_environment_secrets = {
          DATABASE_URL          = aws_secretsmanager_secret.database_url.arn
          AUSPEX_MCP_TOKEN      = aws_secretsmanager_secret.mcp_token.arn
          (var.llm_api_key_env) = aws_secretsmanager_secret.llm_api_key.arn
        }
      }
    }
  }

  instance_configuration {
    cpu               = var.service_cpu
    memory            = var.service_memory
    instance_role_arn = aws_iam_role.apprunner_instance.arn
  }

  # A plain GET to /mcp returns 406 (it expects an MCP handshake), so an HTTP
  # health check would fail — use a TCP check that the port is accepting.
  health_check_configuration {
    protocol            = "TCP"
    interval            = 10
    timeout             = 5
    healthy_threshold   = 1
    unhealthy_threshold = 5
  }

  network_configuration {
    egress_configuration {
      egress_type       = "VPC"
      vpc_connector_arn = aws_apprunner_vpc_connector.this.arn
    }
  }

  depends_on = [
    aws_secretsmanager_secret_version.database_url,
    aws_secretsmanager_secret_version.mcp_token,
    aws_secretsmanager_secret_version.llm_api_key,
    aws_iam_role_policy.apprunner_secrets,
  ]
}
