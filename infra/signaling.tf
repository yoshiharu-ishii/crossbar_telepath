# ---------------------------------------------------------------
# シグナリング経路: 呼の設定をSCPへ伝える共通線
#
# 通話路(KVS)とは分離する。コールフローがLambdaを叩き、Lambdaが
# ContactId・StreamARN・StartFragmentNumber をSQSへ流す。SCPはこれを
# 読んで呼ごとに受信を始めるので、ストリーム一覧の推測が要らなくなる。
# ---------------------------------------------------------------

resource "aws_sqs_queue" "call_events" {
  name = "${var.project}-call-events"
  # SCPが取りこぼしても再受信できるよう、可視性タイムアウトは短めに
  visibility_timeout_seconds = 30
  # KVSの保持期間(24h)に揃える。SCP停止中に来た呼はキューで待ち、
  # SCP起動時にStartFragmentNumberからアーカイブを遡って自動処理される
  # (=シグナリングがそのまま留守番録音の再生キューになる)
  message_retention_seconds  = 86400
}

data "archive_file" "call_notifier" {
  type        = "zip"
  source_file = "${path.module}/lambda/call_notifier.py"
  output_path = "${path.module}/.build/call_notifier.zip"
}

resource "aws_iam_role" "call_notifier" {
  name = "${var.project}-call-notifier"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "call_notifier" {
  role = aws_iam_role.call_notifier.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["sqs:SendMessage"]
        Resource = aws_sqs_queue.call_events.arn
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:*:*:*"
      },
    ]
  })
}

resource "aws_lambda_function" "call_notifier" {
  function_name    = "${var.project}-call-notifier"
  role             = aws_iam_role.call_notifier.arn
  handler          = "call_notifier.handler"
  runtime          = "python3.12"
  filename         = data.archive_file.call_notifier.output_path
  source_code_hash = data.archive_file.call_notifier.output_base64sha256
  timeout          = 5

  environment {
    variables = {
      QUEUE_URL = aws_sqs_queue.call_events.url
    }
  }
}

# コールフローの「外部リソース呼び出し」から叩けるようにする
resource "aws_lambda_permission" "connect" {
  statement_id  = "AllowConnectInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.call_notifier.function_name
  principal     = "connect.amazonaws.com"
  source_arn    = aws_connect_instance.this.arn
}

# Connectインスタンス側にも関数を登録する(これがないとフローから選べない)
resource "aws_connect_lambda_function_association" "call_notifier" {
  instance_id  = aws_connect_instance.this.id
  function_arn = aws_lambda_function.call_notifier.arn
}
