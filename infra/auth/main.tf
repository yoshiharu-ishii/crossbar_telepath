# 認証基盤 (Amazon Cognito) — 本体基盤(../)とはstateを分離している。
#
# 分離の理由: User Poolは「ユーザー登録」というデータを持つ層であり、
# 本体の作り直し(terraform destroy)に巻き込まれてはならない。
# realtime_voiceで一度、ターゲットなしのdestroyでユーザーごと消す事故が起きた。
# このディレクトリでは原則destroyしないこと(deletion_protectionでも防いでいる)。

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.70"
    }
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = "crossbar-telepath"
      ManagedBy = "terraform"
    }
  }
}

resource "aws_cognito_user_pool" "this" {
  name                     = "crossbar-telepath"
  user_pool_tier           = "ESSENTIALS"
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]
  deletion_protection      = "ACTIVE" # 事故対策: destroyやコンソール操作での削除を拒否する
  mfa_configuration        = "OFF"

  # セルフサインアップ禁止(ユーザー作成は管理者のみ)。通話内容を扱う製品なので、
  # 登録経路はコード管理された users.tf だけにする
  admin_create_user_config {
    allow_admin_create_user_only = true

    # 招待メールの文面をカスタム。既定文面は一時パスワードの直後に文末ピリオドが
    # 付いており、コピーで巻き込んでログインに失敗する事故が実際に起きた
    # (realtime_voiceの教訓)。パスワードは独立した行に置き、末尾に何も付けない
    invite_message_template {
      email_subject = "crossbar-telepath への招待"
      email_message = <<-EOT
        crossbar-telepath (通話モニタ) に招待されました。<br><br>
        ユーザー名: {username}<br>
        一時パスワード(この行をそのままコピー):<br>
        {####}<br><br>
        アプリにアクセスし、上記でログインすると新しいパスワードの設定を求められます。
      EOT
      sms_message   = "ユーザー名 {username} 一時パスワード {####}"
    }
  }

  password_policy {
    minimum_length                   = 8
    require_uppercase                = true
    require_lowercase                = true
    require_numbers                  = true
    require_symbols                  = true
    temporary_password_validity_days = 7
  }
}

# SPA用の公開クライアント(シークレットなし)。ログイン画面は自前なので
# Hosted UI(OAuthフロー・ドメイン)は使わず、SRPだけを許可する
resource "aws_cognito_user_pool_client" "web" {
  name         = "web"
  user_pool_id = aws_cognito_user_pool.this.id

  explicit_auth_flows = [
    "ALLOW_USER_SRP_AUTH",            # SPAのログイン(パスワードを平文で送らない)
    "ALLOW_REFRESH_TOKEN_AUTH",       # トークンの自動更新
    "ALLOW_ADMIN_USER_PASSWORD_AUTH", # 自動テストでのトークン発行用(要AWS資格情報)
  ]

  # IDトークン1時間 / リフレッシュ30日
  id_token_validity      = 60
  access_token_validity  = 60
  refresh_token_validity = 30
  token_validity_units {
    id_token      = "minutes"
    access_token  = "minutes"
    refresh_token = "days"
  }
}

# ロール。IDトークンの cognito:groups クレームにそのまま載る。
# sv       = 監視卓。全呼のゲージ・アラート通知・通話カードを見る
# operator = 応対者。自分の呼だけ・画面は静かに(PH4後半で認可を実装)
resource "aws_cognito_user_group" "sv" {
  name         = "sv"
  user_pool_id = aws_cognito_user_pool.this.id
  description  = "監視卓(全呼・通知・カード)"
}

resource "aws_cognito_user_group" "operator" {
  name         = "operator"
  user_pool_id = aws_cognito_user_pool.this.id
  description  = "応対者(自分の呼のみ・通知なし)"
}
