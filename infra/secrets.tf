# DATABASE_URL is composed from the RDS instance + the master credentials so it
# always matches the provisioned database.
resource "aws_secretsmanager_secret" "database_url" {
  name = "${var.app_name}/database-url"
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id = aws_secretsmanager_secret.database_url.id
  secret_string = format(
    "postgresql://%s:%s@%s:5432/%s",
    var.db_username,
    var.db_password,
    aws_db_instance.postgres.address,
    aws_db_instance.postgres.db_name,
  )
}

resource "aws_secretsmanager_secret" "mcp_token" {
  name = "${var.app_name}/mcp-token"
}

resource "aws_secretsmanager_secret_version" "mcp_token" {
  secret_id     = aws_secretsmanager_secret.mcp_token.id
  secret_string = var.mcp_token
}

resource "aws_secretsmanager_secret" "llm_api_key" {
  name = "${var.app_name}/llm-api-key"
}

resource "aws_secretsmanager_secret_version" "llm_api_key" {
  secret_id     = aws_secretsmanager_secret.llm_api_key.id
  secret_string = var.llm_api_key
}
