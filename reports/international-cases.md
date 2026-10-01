# 海外事例・公開実装・失敗報告（2026-10-01調査）

Core Advancedの実測と、利用方法のヒントを分けた。下記15件のうちCore Advancedを明示した失敗報告は1件。世代不明・2025年の事例から現行モデルの速度や正答率は推定しない。公開READMEの機能説明は第三者による動作保証ではない。コードは調査のみで、導入・転載していない。

| # | 事例・一次資料 | 世代／証拠 | 検証へ取り込んだ視点 |
|---|---|---|---|
| 1 | [App Review関連の構造化スキャン失敗](https://developer.apple.com/forums/thread/843310) | 投稿者がM4 Pro、Core Advanced、8192を確認。macOS 27 beta〜RC 26A428での報告 | 大きい構造を分割。形式が合っても証拠の対応が誤る。JSON指定の回避策も投稿者には改善なし。現行26A434への再現性は別問題 |
| 2 | [Swift Image Understanding](https://github.com/arraypress/swift-image-understanding) | OS27画像API、variant不明。公開実装 | 画像Q&A／レシート抽出とVision OCRの役割分担 |
| 3 | [FoundationModelsKit](https://github.com/rryam/FoundationModelsKit) | OS27対応を含む公開ユーティリティ、variant不明 | 型・使用量・履歴・ツール回数・重複呼び出しの検証をアプリが持つ |
| 4 | [CricHeroes iOS27](https://blog.cricheroes.com/ios-27-and-iphone-duo-are-here-so-are-we/) | 開発元の現行OS向け紹介、Core Advanced明記なし | Visionと試合データを使うフィードバック／実況。正確性は開発元の主張で、独立ベンチではない |
| 5 | [afm-server](https://github.com/Techopolis/afm-Server) | ローカルHTTP実装、variant不明 | 永続セッション、キュー、キャンセル。READMEとGitHub表示にライセンスの食い違いがあり、コード利用を推薦しない |
| 6 | [Perspective Intelligence Web](https://github.com/Techopolis/perspective-intelligence-web-community) | Web UI＋ローカルAFM、variant不明 | ネイティブUI以外からのローカル呼び出し。今回は公式fm serveだけ測定 |
| 7 | [OpenIntelligence](https://github.com/Gunnarguy/OpenIntelligence) | 資料検索／OCRアプリの公開コード、variant不明 | 根拠を持つ抽出、資料単位の検索、引用の検証。READMEの品質表現を実測と混同しない |
| 8 | [apfel](https://github.com/presswizards/apfel-Apple-Native-LLM) | CLI実装、variant不明 | Unixパイプで短い変換や抽出を行う。外部CLIは導入せず公式fmを使用 |
| 9 | [Foundation Models Playgrounds](https://github.com/IvanCampos/Foundation-Models-Playgrounds) | WWDC25を含む学習例、世代混在／不明 | NPC、色・素材の指定、語彙整理、短い創作、ツール選択のアイデア集。性能根拠には使わない |
| 10 | [SmartGym](https://www.apple.com/in/newsroom/2025/09/apples-foundation-models-framework-unlocks-new-intelligent-app-experiences/) | 2025年の公式利用紹介 | 自然言語を小さな運動仕様に変換し、既存データを説明 |
| 11 | [Stoic](https://www.apple.com/in/newsroom/2025/09/apples-foundation-models-framework-unlocks-new-intelligent-app-experiences/) | 2025年の公式利用紹介 | 日記の書き出し、短い通知、分類の候補生成 |
| 12 | [CellWalk](https://www.apple.com/in/newsroom/2025/09/apples-foundation-models-framework-unlocks-new-intelligent-app-experiences/) | 2025年の公式利用紹介 | アプリ内の科学情報をツールで取得し、説明の難度を調整 |
| 13 | [SwingVision](https://www.apple.com/in/newsroom/2025/09/apples-foundation-models-framework-unlocks-new-intelligent-app-experiences/) | 2025年の公式利用紹介 | 既存の計測データから短いフィードバックを作る |
| 14 | [VLLO](https://www.apple.com/in/newsroom/2025/09/apples-foundation-models-framework-unlocks-new-intelligent-app-experiences/) | 2025年の公式利用紹介 | Visionの結果を使い、素材候補の選択を補助 |
| 15 | [Essayist](https://www.apple.com/in/newsroom/2025/09/apples-foundation-models-framework-unlocks-new-intelligent-app-experiences/) | 2025年の公式利用紹介 | PDFをVisionで読み、引用用メタデータを構造化 |

今回の実験への示唆は「自由に任せる範囲を小さくする」「データ取得・計算・実行はアプリが担う」「画像と文字の経路を分けて実測する」。用途の可能性を示す事例であり、Core Advancedが実用精度を満たす証拠にはしていない。

現行の公式API案内は[WWDC26](https://developer.apple.com/videos/play/wwdc2026/241/)を確認した。画像、Visionツール、Spotlight検索、Python SDK、fm CLI、使用量計測が紹介されている。今回は許可されたローカルCore Advancedだけを使い、Cloudや外部モデルには接続しない。
