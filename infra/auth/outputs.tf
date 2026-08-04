output "user_pool_id" {
  value = aws_cognito_user_pool.this.id
}

output "web_client_id" {
  value = aws_cognito_user_pool_client.web.id
}

output "region" {
  value = var.region
}

# backend/.env にそのまま貼れる形
output "env_snippet" {
  value = <<-EOT
    AUTH_ENABLED=1
    COGNITO_USER_POOL_ID=${aws_cognito_user_pool.this.id}
    COGNITO_CLIENT_ID=${aws_cognito_user_pool_client.web.id}
  EOT
}
