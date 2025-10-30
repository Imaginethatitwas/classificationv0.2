output "bucket_name" {
  value = aws_s3_bucket.scrape_bucket.bucket
}

output "lambda_function_name" {
  value = aws_lambda_function.ingestion.function_name
}
