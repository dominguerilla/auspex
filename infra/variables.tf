variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-east-1"
}

variable "app_name" {
  description = "Name prefix for all resources."
  type        = string
  default     = "auspex-mcp"
}

variable "db_instance_class" {
  description = "RDS instance class (db.t4g.micro is free-tier-eligible)."
  type        = string
  default     = "db.t4g.micro"
}

variable "db_username" {
  description = "RDS master username."
  type        = string
  default     = "auspex"
}

variable "db_password" {
  description = "RDS master password. Set via TF_VAR_db_password or tfvars — never commit it."
  type        = string
  sensitive   = true
}

variable "mcp_token" {
  description = "Bearer token agents must present (AUSPEX_MCP_TOKEN). Use a long random string."
  type        = string
  sensitive   = true
}

variable "llm_provider" {
  description = "LLM_PROVIDER for get_llm() (e.g. openai_compatible, nous, huggingface)."
  type        = string
  default     = "openai_compatible"
}

variable "llm_api_key_env" {
  description = "Env var name the chosen provider reads its key from (OPENAI_API_KEY, NOUS_API_KEY, HF_TOKEN, ...)."
  type        = string
  default     = "OPENAI_API_KEY"
}

variable "llm_api_key" {
  description = "API key for the LLM provider. Set via TF_VAR_llm_api_key or tfvars — never commit it."
  type        = string
  sensitive   = true
}

variable "image_tag" {
  description = "ECR image tag App Runner deploys."
  type        = string
  default     = "latest"
}

variable "service_cpu" {
  description = "App Runner vCPU units (1024 = 1 vCPU)."
  type        = string
  default     = "1024"
}

variable "service_memory" {
  description = "App Runner memory in MB."
  type        = string
  default     = "2048"
}
