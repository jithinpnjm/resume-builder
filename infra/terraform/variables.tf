variable "project_id" {
  type    = string
  default = "my-personal-data-430607"
}

variable "region" {
  type    = string
  default = "asia-south1"
}

variable "service_name" {
  type    = string
  default = "resume-agent"
}

variable "repo_name" {
  type    = string
  default = "resume-agent"
}

variable "bucket_name" {
  type    = string
  default = "resume-agent-templates"
}

variable "gemini_model" {
  type    = string
  default = "gemini-2.5-flash"
}

variable "image" {
  type        = string
  description = "Container image URI to deploy."
}
