variable "project_id" {
  description = "GCP project ID to deploy into."
  type        = string
}

variable "region" {
  description = "GCP region."
  type        = string
  default     = "us-central1"
}

variable "app_name" {
  description = "Name prefix for resources (Cloud Run service, AR repo, etc.)."
  type        = string
  default     = "auspex-mcp"
}

variable "db_tier" {
  description = "Cloud SQL machine tier (db-f1-micro is the smallest/cheapest)."
  type        = string
  default     = "db-f1-micro"
}

variable "db_username" {
  description = "Cloud SQL database user."
  type        = string
  default     = "auspex"
}

variable "db_password" {
  description = "Cloud SQL user password. Set via TF_VAR_db_password or tfvars — never commit."
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
  description = "API key for the LLM provider. Set via TF_VAR_llm_api_key or tfvars — never commit."
  type        = string
  sensitive   = true
}

variable "image_tag" {
  description = "Artifact Registry image tag Cloud Run deploys."
  type        = string
  default     = "latest"
}

variable "cpu" {
  description = "Cloud Run vCPU per instance."
  type        = string
  default     = "1"
}

variable "memory" {
  description = "Cloud Run memory per instance."
  type        = string
  default     = "512Mi"
}

variable "min_instances" {
  description = "Minimum Cloud Run instances (0 = scale to zero)."
  type        = number
  default     = 0
}

variable "max_instances" {
  description = "Maximum Cloud Run instances."
  type        = number
  default     = 2
}

variable "llm_model_env" {
  description = "Env var the provider reads its model from (e.g. ANTHROPIC_MODEL, OPENAI_MODEL). Only used when llm_model is set."
  type        = string
  default     = "ANTHROPIC_MODEL"
}

variable "llm_model" {
  description = "Model ID to pin (e.g. claude-sonnet-4-6). Empty = the provider's built-in default (Anthropic: claude-haiku-4-5)."
  type        = string
  default     = ""
}
