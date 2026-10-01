# 利用経路と改善できる範囲（2026-10-01確認）

今回の判断は公開文書と実機SDKに基づく実施範囲の整理。SDKのソースの許諾と、OSが管理するモデル・推論サービスの許諾は別に扱う。

| 対象 | 確認結果・今回の扱い | 根拠 |
|---|---|---|
| Swiftからシステムモデル | 公開FoundationModels APIを使用。セッション、構造化生成、ツール、tokenCount、使用量、prewarm、キャンセルを検証 | [公式案内](https://developer.apple.com/documentation/foundationmodels/generating-content-and-performing-tasks-with-foundation-models)、実機Xcode27公開interface |
| Pythonから同じモデル | Apple公式SDK 0.2.1を独立venvへ導入。公開APIのみ使用 | [SDK](https://github.com/apple/python-apple-fm-sdk)、[WWDC26](https://developer.apple.com/videos/play/wwdc2026/241/) |
| Python SDKの改変 | Apache-2.0。著作権・ライセンス等の必要表示、改変表示、該当するNOTICEを維持すればSDKコードの改善は可能。今回は測定用ラッパーを作成し、SDK本体は未改変 | [LICENSE](https://github.com/apple/python-apple-fm-sdk/blob/main/LICENSE.md)、導入物のライセンスをlicenses/へ保存 |
| fm respond／fm serve | 実機の公式CLIでローカルHTTPとUnixソケットを測定。一時的なローカルサーバーだけ使用する | 実機 `fm --help`／`fm serve --help`、[公式紹介](https://developer.apple.com/videos/play/wwdc2026/241/) |
| アプリ側の改善 | 指示・例示・スキーマ、入力削減、結果キャッシュ、有限の操作仕様、通常コードによる計算、直列キュー、QoS、再試行条件を改善対象とする | 公開APIで実装できる範囲 |
| 重み・量子化・内部カーネル・専門家選択 | Core Advanced向けに改変・抽出・再配布の許諾と対応APIを確認できていないため実施しない。SDKがApacheであることはモデル資産の許諾にならない | 実機macOS SLA 2N、公開APIの範囲。許諾のないリバースエンジニアリングを行わない |
| AFMアダプタ学習 | 旧公式ツールキット26.0.0はOS27以降に非対応。Core Advanced向けの対応手段として扱わない | [公式の互換性表示](https://developer.apple.com/apple-intelligence/foundation-models-adapter/) |

適用される利用条件の参照先は[Apple Developer Program License Agreement 3.3.11(A)](https://developer.apple.com/support/terms/apple-developer-program-license-agreement/)と[FoundationModels Acceptable Use Requirements](https://developer.apple.com/support/terms/acceptable-use-requirements-for-the-foundation-models-framework/)。macOSに含まれるfmとモデルには実機のmacOSライセンスも適用される。ライセンス表示を読み取るだけで、別の契約の代理承諾は行っていない。

Core Advancedの[公式アーキテクチャ説明](https://machinelearning.apple.com/research/introducing-third-generation-of-apple-foundation-models)では、全体20B、同時に1〜4Bを有効化し、重みをflashへ保持する。IFPによりプロンプト単位で専門家を選び、生成中にも定期的に選び直す。通常のtoken単位MoEと同じ前提で最適化はできない。ユーザー提供のMLX高速化値は別の推論実装の結果であり、AFMへの効果の根拠には使わない。

検証コードを外付けSSDへ置いても、OS管理のAFM資産をそこへ移動したことにはならない。flash利用から「バックグラウンド処理は他を邪魔しない」とは推定せず、負荷を別途測定する。[AppleのmacOS/iOSの説明](https://developer.apple.com/videos/play/wwdc2026/8016/?time=1138)では、iOS背景処理のrate limitingとmacOSのQoSは区別されている。

実施した基盤改善は、Python SDKの公開stream_responseを専用スレッド／専用イベントループに隔離するラッパー（scripts/sdk_responsive.py）。SDK0.2.1の同期queue待ちによる呼び出し元イベントループの停止を、実機3反復で改善した。インストール済みSDKは変更していない。SDK本体の将来の改善候補は、asyncの通知経路、公開variant／使用量／toolCallingModeのPython側への橋渡し。これらもOSの公開APIを呼ぶ範囲で行い、カーネルやモデルの変更には結び付けない。
