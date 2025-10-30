variable "aws_region" {
  description = "AWS region where resources will be created"
  type        = string
  default     = "us-east-1"
}

variable "bucket_name" {
  description = "Name of the bucket that stores raw and curated scrapes"
  type        = string
}

variable "lambda_package" {
  description = "Path to the packaged Lambda zip archive"
  type        = string
}

variable "raw_transition_after_days" {
  description = "Number of days after which raw scrapes are moved to infrequent access"
  type        = number
  default     = 30
}

variable "raw_expiration_after_days" {
  description = "Number of days after which raw scrapes are expired"
  type        = number
  default     = 365
}

variable "curated_expiration_after_days" {
  description = "Number of days after which curated scrapes are expired"
  type        = number
  default     = 730
}

variable "default_tags" {
  description = "Tags applied to all resources"
  type        = map(string)
  default     = {
    Project = "tiktok-scraper"
  }
}
