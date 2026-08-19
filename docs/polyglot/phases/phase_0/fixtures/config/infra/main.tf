resource "aws_s3_bucket" "assets" {
  bucket = "example-assets"
}

resource "aws_cloudfront_distribution" "cdn" {
  origin {
    domain_name = aws_s3_bucket.assets.bucket_regional_domain_name
    origin_id   = "assets-origin"
  }
  enabled = true
}
