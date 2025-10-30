terraform {
  required_version = ">= 1.4.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

resource "aws_s3_bucket" "scrape_bucket" {
  bucket = var.bucket_name

  force_destroy = true

  lifecycle_rule {
    id      = "transition-raw-to-infrequent"
    enabled = true

    prefix = "raw/"

    transition {
      days          = var.raw_transition_after_days
      storage_class = "STANDARD_IA"
    }

    expiration {
      expired_object_delete_marker = true
      days                          = var.raw_expiration_after_days
    }
  }

  lifecycle_rule {
    id      = "expire-curated"
    enabled = true

    prefix = "curated/"

    expiration {
      days = var.curated_expiration_after_days
    }
  }

  versioning {
    enabled = true
  }

  server_side_encryption_configuration {
    rule {
      apply_server_side_encryption_by_default {
        sse_algorithm = "aws:kms"
      }
    }
  }

  tags = var.default_tags
}

resource "aws_s3_bucket_public_access_block" "scrape_bucket" {
  bucket = aws_s3_bucket.scrape_bucket.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_lambda_function" "ingestion" {
  function_name = "scrape-batch-ingestion"
  role          = aws_iam_role.lambda_role.arn
  handler       = "ingestion_lambda.ingestion_handler.lambda_handler"
  runtime       = "python3.11"
  filename      = var.lambda_package

  environment {
    variables = {
      BUCKET_NAME           = aws_s3_bucket.scrape_bucket.bucket
      CURATED_PREFIX        = "curated/"
      RAW_PREFIX            = "raw/"
      CURATED_BATCH_MANIFEST_PREFIX = "curated_manifests/"
    }
  }

  depends_on = [aws_iam_role_policy_attachment.lambda_basic_execution]
}

resource "aws_lambda_permission" "allow_s3_invoke" {
  statement_id  = "AllowExecutionFromS3"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingestion.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.scrape_bucket.arn
}

resource "aws_s3_bucket_notification" "scrape_bucket" {
  bucket = aws_s3_bucket.scrape_bucket.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.ingestion.arn
    events              = ["s3:ObjectCreated:Put"]
    filter_prefix       = "raw/"
    filter_suffix       = "manifest.json"
  }

  depends_on = [aws_lambda_permission.allow_s3_invoke]
}

resource "aws_iam_role" "lambda_role" {
  name = "scrape-batch-ingestion-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "lambda_policy" {
  name = "scrape-batch-ingestion-policy"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.scrape_bucket.arn,
          "${aws_s3_bucket.scrape_bucket.arn}/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic_execution" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}
