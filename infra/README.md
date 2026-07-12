# infra — Amazon Connect 基盤(PH1)

TerraformでコールセンターをフルIaC構築する。PH1のスコープは
**「架電すると録音同意アナウンスが流れ、通話音声がKVSにライブ配信される」**まで。

## 構成

```mermaid
flowchart TD
    PSTN[公衆電話網] --> DID["DID(aws_connect_phone_number)"]
    DID -->|aws_connect_phone_number_contact_flow_association| Flow["コールフロー(flows/inbound.json)"]
    Flow -->|"aws_connect_instance_storage_config(MEDIA_STREAMS)"| KVS["Kinesis Video Streams<br>KMS暗号化、保持24h<br>crossbar-telepath-connect-…-contact-*"]
```

架電時の呼処理:

```mermaid
sequenceDiagram
    actor Caller as 発信者(携帯)
    participant Connect as Amazon Connect
    participant Flow as コールフロー(IVR)
    participant KVS as Kinesis Video Streams

    Caller->>Connect: DIDへ着信
    Connect->>Flow: 呼処理開始
    Flow->>Flow: ログ有効化・日本語音声(Takumi)設定
    Flow->>Caller: 録音同意アナウンス
    Flow->>KVS: メディアストリーミング開始(To/Fromの2トラック)
    loop 無音SSML 1分 × 10回(通話維持)
        Flow-->>Caller: 無音プロンプト再生
        Caller-->>KVS: 発話がFROM_CUSTOMERトラックに積まれる
    end
    Caller->>Connect: 切断(またはループ満了で切断)
```

- 自分(To)と相手(From)の音声は**同一KVSストリーム内の別トラック**で届く(トラック1=TO、トラック2=FROM)
- コールフローは新フロー言語(`Version: 2019-10-30`)。旧形式(modules)ではないので注意

## 使い方

```bash
cd infra
terraform init
terraform plan
terraform apply
# outputs の phone_number に携帯から架電して検証
```

state はローカル管理(gitignore済み)。**tfstateは絶対にコミットしない**。

## 検証手順

1. `terraform output phone_number` の番号に架電
2. 録音同意アナウンス(日本語)が流れることを確認
3. 何か話してから切断
4. KVSにストリームができていることを確認:
   ```bash
   aws kinesisvideo list-streams --output table
   ```

## コストメモ

- Connectインスタンス自体: 無料(従量課金のみ)
- US DID: 日額課金(月額数百円級)+着信従量。**検証しない期間が長いなら destroy 推奨**
- KMSキー: 約$1/月
- KVS: 取り込み・保持とも従量。検証通話レベルなら誤差
- 日本の+81番号は書類審査が必要。必要になったら `phone_number_country_code = "JP"`
  に変えるのではなく、まずAWSサポートで番号申請の要件を確認すること

## 既知の注意点

- `aws_connect_phone_number` は在庫の取り合いで
  「Phone number not available」で失敗することがある。再applyでリトライすれば別番号で取れる
- インスタンスエイリアス(`connect_instance_alias`)はグローバル一意
- メディアストリーミングのstorage config(`MEDIA_STREAMS`)はコールフローの
  ストリーミング開始ブロックより**先に**存在している必要がある(このmoduleでは依存関係で保証済み)
