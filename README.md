# AFM 3 Core Advanced lab

Preliminary findings and a reproducible command-line test app for **AFM 3 Core Advanced**. An independent project using Apple's public FoundationModels APIs, official Python SDK, and `fm` CLI. Apple does not sponsor or endorse this project.

AFM 3 Core Advancedの用途探索・品質調整・呼び出し経路・背景負荷を調べた先行調査です。SwiftのJSONLテストアプリとPythonの検証スクリプトを含みます。別モデルの比較・利用は行っていません。

## Preliminary findings

| 未使用の評価ケース | 基本設定 | 調整後の全条件適合 |
|---|---:|---:|
| 差分・不足情報の検出 | 6/30 | 29/30 |
| 情報抽出 | 21/30 | 20/30 |
| 表の操作仕様 | 14/30 | 18/30 |

限定した項目と具体例を使う差分レビュー補助が最も有望でした。合成データでの結果であり、実業務の精度保証ではありません。10分野60ケースの探索と調整・方式比較を合わせ、品質試験380件を記録しました。

関連入力をコードで選ぶ試験は完了中央値3.18→0.86秒。Python SDKの専用スレッド化はイベントループの最大停止を約2.5〜3.5秒→11〜13msへ抑えました。後者は生成速度の改善ではありません。詳細と限界は[検証結果](reports/results.md)と[推奨する使い方](reports/recommendations.md)を参照してください。

## Measured environment

| 項目 | 条件 |
|---|---|
| Mac | Mac mini M6 |
| メモリ | 32GB |
| 内蔵ストレージ | SSD 256GB（公称。diskutilのデバイス容量表示は251,000,193,024 bytes） |
| モデル資産 | OS管理の内蔵ストレージに配置。外付けSSDへ移動していない |
| 検証コード・入力・ログ | 外付けSSDに配置 |
| OS | macOS 27.0.1 / build 26A434 |
| モデル・context | AFM 3 Core Advanced / 8192 tokens |
| ツール | Xcode 27 / Swift 6.4、Python 3.12.14、apple-fm-sdk 0.2.1 |
| 期間 | 2026-10-01〜02 |

flashを利用するモデル構成ではストレージ配置も比較条件です。SSDのcold load／キャッシュ消去／ストレージ速度ベンチマークは実施していません。容量と配置から実際のSSD読み取り時間を推定しないでください。

## Requirements and quick start

実機生成にはApple Silicon、対応するmacOS 27とXcode、利用可能なApple Intelligenceモデル、Python 3.10以上が必要です。実行時にCore Advancedと8192のgateを確認し、不一致なら停止します。SDK単独ではvariantを取得できないため、隣接するSwift gateを記録します。

```sh
git clone https://github.com/ultimate-1113/afm-3-core-advanced-lab.git
cd afm-3-core-advanced-lab
zsh scripts/setup.sh
.venv/bin/python scripts/audit.py
.venv/bin/python scripts/privacy_audit.py
printf '%s\n' '{"id":"demo","prompt":"日本の首都を都市名だけで答えてください。","max_tokens":32}' | bin/afm-runner
```

任意のPython実行ファイルは`AFM_LAB_PYTHON`、Xcodeの場所は`DEVELOPER_DIR`で指定できます。システムのXcode選択は変更しません。モデル実行を制限するコンテナではgateが不正確になることがあるため、通常のホスト環境で使います。

## Reproduce the evaluation

公開済みの`results/`はパスを正規化した測定ログです。同じ結果ファイルでは品質評価が保存済みケースをスキップし、runtime等は追記します。**完全再実行する場合は、最初に`results`を別名で保存し、空の`results`ディレクトリを作ってください。** `reports/tuning-selection.json`も別名で保存すれば、元の調整方法選択を保持できます。

```sh
.venv/bin/python scripts/lab.py screen
.venv/bin/python scripts/lab.py tune
.venv/bin/python scripts/lab.py extra-tune
.venv/bin/python scripts/lab.py split-tune
.venv/bin/python scripts/report.py select
.venv/bin/python scripts/lab.py heldout
.venv/bin/python scripts/lab.py images
.venv/bin/python scripts/runtime.py all
.venv/bin/python scripts/runtime.py recovery --output recovery-final.jsonl
.venv/bin/python scripts/runtime.py resources --output resources.jsonl
.venv/bin/python scripts/retry_probe.py
.venv/bin/python scripts/sdk_responsive.py
.venv/bin/python scripts/file_operations.py
.venv/bin/python scripts/report.py final
.venv/bin/python scripts/snapshot.py
```

通常は同時要求1件。runtimeのload／resourcesだけ独立セッション2件を明示して使用します。`fm serve`は一時的な127.0.0.1:19876／リポジトリ内Unixソケットを使い、今回起動したプロセスだけ終了します。

`data/`は手書きの正解付き合成データです。heldoutは評価前にSHA256を固定し、devと別の人名・数値・文章で構成しました。同じ10種類のテンプレートを含むため、実データへ正答率を外挿しません。自然文・創作の機械採点には簡易検査が含まれます。

途中の不成立な測定も保持しています。中断の最終集計には`recovery-final.jsonl`、CPU/RSSには`resources.jsonl`を使います。最終Runnerはversion 3。通常の品質試験からの変更は、中断タイマーと状態表示、履歴上限検査、必須ツール設定です。`environment.json`と`measurement-artifact-manifest.json`の初期ハッシュ、公開版の`final-artifact-manifest.json`は別のスナップショットです。

TTFTは最初の可視テキスト／構造スナップショットまでで、経路や出力形式により表示単位が異なります。前処理・prewarm待機・起動・通信時間は別に記録します。SDK／CLIで取得できない使用量はnullです。背景負荷は小CPU処理の代理指標・プロセスCPU/RSS・メモリ圧迫・swapであり、ゲームや動画編集、GPU負荷、消費電力の保証ではありません。

## Scope, licenses and records

独自コード・文書・手書きの入力／正解データは[MIT](LICENSE)。Apple SDKは[Apache-2.0](licenses/apple-fm-sdk-0.2.1-LICENSE.md)で別扱いです。AFM生成結果へMITを拡張しません。OS／モデルの実行にはAppleの条件が適用されます。モデル、framework、SDKのバイナリは配布せず、インストール済みSDKも変更していません。

- [ライセンス再精査と公開範囲](reports/license-review.md)
- [第三者の権利・生成結果](THIRD_PARTY_NOTICES.md) / [結果ログの扱い](results/README.md)
- [海外15事例](reports/international-cases.md) / [改善可能範囲](reports/permitted-improvements.md)
- [公開前確認と正規化](reports/publication-audit.md)

モデル資産の抽出・改変、private API、ガードレールの回避、別AIモデルの学習・改善への出力利用は検証対象に含みません。表・ファイル操作は許可した通常コードと合成ファイルだけを使用し、生成コードは実行しません。
