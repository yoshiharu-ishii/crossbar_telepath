variable "aws_region" {
  description = "デプロイ先リージョン"
  type        = string
  default     = "ap-northeast-1"
}

variable "project" {
  description = "リソース名のプレフィックス"
  type        = string
  default     = "crossbar-telepath"
}

variable "connect_instance_alias" {
  description = "Connectインスタンスのエイリアス(グローバル一意)"
  type        = string
  default     = "crossbar-telepath"
}

variable "phone_number_country_code" {
  description = "取得する電話番号の国コード。JPは書類審査が必要なため、検証はUSで行う"
  type        = string
  default     = "US"
}

variable "phone_number_type" {
  description = "電話番号種別(DID or TOLL_FREE)"
  type        = string
  default     = "DID"
}

variable "kvs_retention_hours" {
  description = "KVSの音声保持時間。開発中はデバッグ用に24h、本番は短縮を検討"
  type        = number
  default     = 24
}
