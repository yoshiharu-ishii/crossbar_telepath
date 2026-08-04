# ユーザーアカウントもコード管理する(terraform applyでアカウントまで生える)。
# セルフサインアップ無効のため、ここに書くことが唯一の登録経路。
#
# 人間のユーザー(invite = true):
#   applyするとCognitoが一時パスワード入りの招待メールを送る(無料枠50通/日)。
#   初回ログイン時にアプリのログイン画面が本パスワードの設定を求める
#   (FORCE_CHANGE_PASSWORDフロー)。管理者は最終パスワードを一切知らない
#
# 自動化ユーザー(invite = false):
#   メールは送らない。パスワードは admin-set-user-password --permanent で
#   自動化側が設定する

locals {
  users = {
    "yoshiharu.ishii@pocraft.net" = { invite = true, groups = ["sv"] }  # 管理者本人
    "claude-e2e@pocraft.net"      = { invite = false, groups = ["sv"] } # E2E検証専用
  }
}

resource "aws_cognito_user" "this" {
  for_each     = local.users
  user_pool_id = aws_cognito_user_pool.this.id
  username     = each.key

  attributes = {
    email          = each.key
    email_verified = "true"
  }

  desired_delivery_mediums = each.value.invite ? ["EMAIL"] : []
  message_action           = each.value.invite ? null : "SUPPRESS"
}

locals {
  memberships = merge([
    for user, cfg in local.users : {
      for g in cfg.groups : "${user}:${g}" => { user = user, group = g }
    }
  ]...)
}

resource "aws_cognito_user_in_group" "this" {
  for_each     = local.memberships
  user_pool_id = aws_cognito_user_pool.this.id
  username     = aws_cognito_user.this[each.value.user].username
  group_name   = each.value.group == "sv" ? aws_cognito_user_group.sv.name : aws_cognito_user_group.operator.name
}
