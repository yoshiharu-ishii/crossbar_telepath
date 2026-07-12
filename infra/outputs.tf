output "connect_instance_id" {
  description = "ConnectインスタンスID"
  value       = aws_connect_instance.this.id
}

output "connect_instance_arn" {
  description = "ConnectインスタンスARN"
  value       = aws_connect_instance.this.arn
}

output "phone_number" {
  description = "取得した電話番号(ここに架電して検証する)"
  value       = aws_connect_phone_number.main.phone_number
}

output "contact_flow_id" {
  description = "着信コールフローID"
  value       = aws_connect_contact_flow.inbound.contact_flow_id
}

output "kvs_stream_prefix" {
  description = "KVSストリーム名のプレフィックス(実ストリーム名は <prefix>-connect-<alias>-contact-...)"
  value       = var.project
}
