# ---------------------------------------------------------------
# 局舎: Amazon Connect インスタンス
# ---------------------------------------------------------------
resource "aws_connect_instance" "this" {
  instance_alias           = var.connect_instance_alias
  identity_management_type = "CONNECT_MANAGED"

  inbound_calls_enabled     = true
  outbound_calls_enabled    = false
  contact_flow_logs_enabled = true
  contact_lens_enabled      = false
}

# ---------------------------------------------------------------
# 通話路の分岐トランク: 通話音声を KVS へライブ配信する設定
# コールフローの StartStreaming ブロックより先にこれが必要
# ---------------------------------------------------------------
resource "aws_kms_key" "kvs" {
  description             = "crossbar-telepath: KVS live media streams encryption"
  deletion_window_in_days = 7
}

resource "aws_kms_alias" "kvs" {
  name          = "alias/${var.project}-kvs"
  target_key_id = aws_kms_key.kvs.key_id
}

resource "aws_connect_instance_storage_config" "live_media" {
  instance_id   = aws_connect_instance.this.id
  resource_type = "MEDIA_STREAMS"

  storage_config {
    storage_type = "KINESIS_VIDEO_STREAM"

    kinesis_video_stream_config {
      prefix                 = var.project
      retention_period_hours = var.kvs_retention_hours

      encryption_config {
        encryption_type = "KMS"
        key_id          = aws_kms_key.kvs.arn
      }
    }
  }
}

# ---------------------------------------------------------------
# 呼処理シナリオ: 録音同意アナウンス → KVS ストリーミング開始 → 無音保留
# ---------------------------------------------------------------
resource "aws_connect_contact_flow" "inbound" {
  instance_id = aws_connect_instance.this.id
  name        = "${var.project}-inbound"
  description = "録音同意アナウンス後にKVSへのメディアストリーミングを開始する検証用フロー"
  type        = "CONTACT_FLOW"

  # Lambda ARNを埋め込む。フローはSCPへのシグナリング(通知)を含む
  content = templatefile("${path.module}/flows/inbound.json.tftpl", {
    lambda_arn = aws_lambda_function.call_notifier.arn
  })

  # Connectインスタンスに関数が紐付いてからフローを作る
  depends_on = [aws_connect_lambda_function_association.call_notifier]
}

# ---------------------------------------------------------------
# 局番の割当: DID 取得(JPは書類審査があるため検証はUS)
# ---------------------------------------------------------------
resource "aws_connect_phone_number" "main" {
  target_arn   = aws_connect_instance.this.arn
  country_code = var.phone_number_country_code
  type         = var.phone_number_type
  description  = "crossbar-telepath inbound verification number"
}

# 着信呼を検証用フローへルーティング(番号→フローの紐付け)
resource "aws_connect_phone_number_contact_flow_association" "main" {
  instance_id     = aws_connect_instance.this.id
  phone_number_id = aws_connect_phone_number.main.id
  contact_flow_id = aws_connect_contact_flow.inbound.contact_flow_id
}
