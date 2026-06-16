output "service_url" {
  description = "Base HTTPS URL of the MCP server. Agents call <service_url>/mcp."
  value       = "https://${aws_apprunner_service.this.service_url}"
}

output "ecr_repository_url" {
  description = "Push the image here before applying the App Runner service."
  value       = aws_ecr_repository.this.repository_url
}

output "rds_endpoint" {
  description = "RDS Postgres endpoint (host)."
  value       = aws_db_instance.postgres.address
}
