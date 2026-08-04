# 動かし方と運用

仕組みは [architecture.md](architecture.md)、記録の持ち方は [data-model.md](data-model.md)。

## 1. 3つの動作モード

用途に応じて、立てるものが変わる。

```mermaid
flowchart LR
    A["① ファイルだけ<br/>コンテナ不要"] --> B["② コンテナあり<br/>DB + オブジェクトストレージ"]
    B --> C["③ 実架電<br/>AWS環境が必要"]
```

| モード | 必要なもの | 用途 |
|---|---|---|
| ① ファイルだけ | `.env` の `OPENAI_API_KEY` のみ | ロジックの試作。録音リプレイで画面まで通る |
| ② コンテナあり | + `docker compose up -d db minio` | 本番と同じ永続化で試す |
| ③ 実架電 | + `terraform apply` | シグナリングとKVS受信を含む通し確認 |

①②は**AWS環境なしで動く**。手元の録音がそのままテストデータになるので、
判定ロジックのイテレーションは架電せずに回せる。

## 2. 起動

```bash
cp backend/.env.example backend/.env   # OPENAI_API_KEY を設定
uv run --directory backend uvicorn main:app --port 8000
```

http://localhost:8000 を開く。起動ログに現在の置き場が出る。

```
INFO db: database ready: localhost:5433/crossbar
INFO main: 呼の記録: postgres / 録音: s3
```

コンテナを使う場合は先に立てておく。

```bash
docker compose up -d db minio      # MinIOコンソール: http://localhost:9001
docker compose up --build          # アプリごとコンテナで動かす場合
```

`docker compose down` で停止(データはボリュームに残る)。`down -v` でデータごと削除。

## 3. 設定

**設定はすべて `.env`**。`config.py` は「どんな設定があるか」の一覧と既定値を持つだけで、
値の置き場ではない。項目を足したら `.env.example` にも必ず追記する。

主なもの(全項目は `backend/.env.example`):

| 変数 | 意味 |
|---|---|
| `OPENAI_API_KEY` | **秘密**。本番ではSSM SecureStringから注入する |
| `WATCH_CALLS` | シグナリング(SQS)を監視して実通話を拾うか。0ならリプレイ専用 |
| `DATABASE_URL` | 空なら呼の記録はJSONファイルへ |
| `S3_ENDPOINT_URL` / `S3_BUCKET` | MinIO利用時のみ設定。空なら本物のS3(IAMロール) |
| `ANGER_*` / `VOICE_JUDGE_MODE` | PH3の感情判定。音声判定は課金が重いので既定は `off` |

`RECORDINGS_DIR` だけは既定値のままにしておくこと。ホストの絶対パスを書くと
コンテナ内で壊れる(既定値がホスト・コンテナ双方で正しい場所を指す)。

**設定にしていないもの**: `SOURCE_RATE=8000` / `SAMPLE_WIDTH=2` / `SPEAKER_BY_TRACK_NAME` は
Amazon Connectの仕様で決まる値であって設定ではない。外に出すと「変えられるが変えたら壊れる」
項目が増えるだけなので、定数のまま根拠をコメントに残してある。

## 4. 架電せずに試す

左ペインの「録音ファイル」をクリックするか、APIから。

```bash
curl -X POST 'http://localhost:8000/api/replay?file=call.mkv&speed=1.0'
```

過去の呼を録音から再処理する場合(同じCallIDのまま記録を上書きする):

```bash
curl -X POST 'http://localhost:8000/api/reprocess/<contact_id>?speed=2.0'
```

リプレイは同時1本まで(連打でセッションが積み上がらないようにするため)。実通話は無制限。

## 5. 台本から通話を合成する(架電せずに検証)

怒り判定の検証には怒った通話が要るが、一人で本気の怒りは作れないし、実架電は
国際通話料もかかる。**TTSで音声を作り、KVSがよこすのと同じ形式のMKVに詰める**ことで、
リプレイ経路に流すだけで実架電と同じパイプラインを通せる。

```bash
OPENAI_API_KEY=... uv run --with httpx --with numpy \
    python ../tools/make_test_call.py --out ../recordings/angry_call.mkv
```

台本は `tools/make_test_call.py` の `SCRIPT` にある(話者・台詞・TTSへの口調指示)。
出力は `recordings/` に置かれ、UIの「録音ファイル」からクリックで再生できる。

合成にあたっては**実機と同じ条件に寄せている**。8kHz / 16bit / mono の生L16、
話者別2トラック、CodecIDは実機と同じく `A_AAC` を詐称。TTSの24kHzは電話帯域に
落としてから使う(綺麗すぎる音では実際の聞き取り困難が再現できないため)。

これにより、判定ロジックを何度直しても**同じ素材で比較**できる。

## 6. AWS環境を建てる / 壊す

```bash
cd infra
terraform apply     # 7リソース。電話番号は在庫の取り合いで初回が落ちることがある(再実行で別番号)
terraform output phone_number
```

**番号は日額課金**なので、検証しない期間は落とすこと。

```bash
terraform destroy
# Connectが動的に作るKVSストリームはTerraform管理外なので個別に削除する
aws kinesisvideo list-streams --output json | \
  python3 -c "import json,sys;[print(s['StreamARN']) for s in json.load(sys.stdin)['StreamInfoList']]"
aws kinesisvideo delete-stream --stream-arn <ARN>
```

再applyすると**電話番号は変わる**(解放済みのため)。

## 7. 実架電での確認

```bash
WATCH_CALLS=1 uv run --directory backend uvicorn main:app --port 8000
```

取得した番号へ架電し、アナウンスの後に話す。画面で確認するのは4点。

1. 呼カードが自動で現れ、**発信者番号**が表示される(シグナリングが効いている証拠)
2. 「解析を開始しました」が**こちら側(緑)**のバブルに出る
3. 発話が**相手側(赤)**のバブルに逐次流れる
4. 約30秒ごとに相槌が緑側に出る(1人架電でも両話者を検証できるようにフローへ入れてある)

うまくいかないときの切り分けは、CloudWatch Logs の Lambda ログ(呼イベントが出ているか)→
SQSにメッセージが残っていないか → アプリのログ(`GetMedia connected` が出ているか)の順。
`GET /api/streams` でKVS側のストリーム一覧も見られる。

## 8. 取り逃した呼の救出

**保持期限(24時間)内なら、記録し損ねた呼も復元できる。**

音声はKVSのアーカイブに、ContactIdはConnectの通話検索に残っている。

```bash
# 1. ContactIdと時刻を得る
aws connect search-contacts --instance-id <ID> \
  --time-range "Type=INITIATION_TIMESTAMP,StartTime=<epoch>,EndTime=<epoch>"

# 2. フラグメントを列挙し、20秒以上の空白を呼の境界として分割
#    3. get-media-for-fragment-list で区間ごとにMKVを取得し recordings/calls/ へ
```

音声さえ戻せば、文字起こしはUIの「再文字起こし」で生成できる(原本と派生の原則)。

なお通常運転では、SQSの保持をKVSと同じ24時間に揃えてあるため、**消費サービスが止まって
いる間に来た呼は起動時に自動で処理される**。手動救出が要るのは「イベントは消費したが
保存に失敗した」場合だけ。

## 9. コスト

| 項目 | 目安 |
|---|---|
| Connect電話番号(US DID) | 日額課金。**使わない日は destroy** |
| Connect通話・KVS | 検証レベルなら誤差 |
| 携帯から米国番号への国際発信 | 30〜40円/分(コストの支配項) |
| 文字起こし(Realtime) | 1通話5分で数円 |
| 感情判定(テキスト) | 1通話1円未満 |
| 感情判定(音声) | **通話時間ぶん課金**。既定で `off`、閾値超過時だけ起動する設計 |

実験コストの支配項は国際発信料なので、長時間の試行はリプレイで代替する。
1本録っておけば恒久的なテストデータになる。

## 10. 踏んだ罠

### 怒り判定のデバウンスで発話を「捨てて」はいけない

判定中や間隔内に来た発話をスキップする実装にしていたところ、合成した怒り通話で
台本の一番きつい部分(「謝れば済むと思ってんのか」以降)が丸ごと無判定になった。

**発話が立て込む場面=怒りが高まっている場面**であり、素朴なデバウンスは
検知したい瞬間を狙い撃ちで落とす。捨てるのではなく**最新の1件に畳み込む**
(`AngerWatcher._pending`)。間隔は守るが、直近の状態は必ず判定に載る。

合成通話を流さなければ、これは実架電で怒鳴られたときに初めて分かる類のバグだった。

### 電話番号のクォータは「解約後も180日間」消費され続ける

Connectの番号クォータ(Phone numbers per instance、既定5)は、**releaseした番号も
180日間カウントし続ける**。apply→検証→destroyを繰り返す本プロジェクトの工法では、
サイクルごとに枠を1つ(取得失敗のリトライでさらに)恒久消費し、2026-08-04に
番号ゼロなのに「allowed limit exceeded」で取得不能になった。

対処: Service Quotas で L-8F812903 の引き上げを申請する(5→15を申請済み)。
また、**取得失敗のリトライも枠を食う**ので、`Phone number not available` の競合時に
無闇に連打しない。長期的には「番号を保持し続ける(日額を払う)」か
「クォータを厚くして使い捨てる」かの選択になる。

### MinIOの資格情報を `AWS_ACCESS_KEY_ID` に置いてはいけない

boto3の `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` は**全クライアントに効く**。
MinIO用のつもりで環境変数に置くと、SQSやKVSまでその鍵で実AWSに認証しようとして
`InvalidClientTokenId` で落ちる。

MinIOの資格情報は **`S3_ACCESS_KEY` / `S3_SECRET_KEY`** に置き、S3クライアントにだけ
明示的に渡すこと(`storage.py` がそうしている)。

2026-08-01にこれで実架電が丸ごと拾えない事故が起きた。症状は「画面が反応しない」だが、
Connectにも Lambda にも SQS にも呼は届いており、**消費サービスだけが認証に失敗して
黙って死んでいた**。

### 監視タスクが死んでいないか確かめる

`GET /api/health` の `watching` は**実際に監視タスクが生きているか**を返す
(設定値は `watch_configured`)。呼が拾えないときはまずここを見る。

```bash
curl -s localhost:8000/api/health
# {"watching": true, "watch_configured": true, ...}  ← 両方trueなら正常
```

`watching: false, watch_configured: true` なら監視タスクが死んでいる。
サーバーのログに「シグナリング監視が停止した」が出ているはず。

### 切り分けの順序

呼が画面に出ないときは、上流から順に見る。

```mermaid
flowchart LR
    A["Connectに呼が届いたか<br/>search-contacts"] --> B["Lambdaが発火したか<br/>CloudWatch Logs"]
    B --> C["SQSに滞留していないか<br/>get-queue-attributes"]
    C --> D["監視タスクが生きているか<br/>/api/health"]
```

SQSに滞留があるのに画面に出ない場合、**呼は失われていない**。原因を直して
サーバーを起動し直せば、キューに残った呼はそのまま処理される(保持24時間)。

## 11. 開発時の注意

- **ユーザーのサーバーはポート8000、Claudeの検証は8001**(終わったら止める)
- 静的ファイルは `Cache-Control: no-cache` を返している。更新後のHTMLと古い `app.js` の
  組み合わせでスクリプトが例外死し「画面が反応しない」事故を防ぐため
  (前作 realtime_voice で踏んだ罠の再発防止)
- `WATCH_CALLS=1` のサーバーを同時に2つ立てないこと。SQSのメッセージは
  片方しか受け取れず、呼イベントの取り合いになる
