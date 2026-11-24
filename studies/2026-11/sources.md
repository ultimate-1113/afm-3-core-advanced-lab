# AFM 3 再検証の先行研究と実機事例

調査日 2026年11月24日。Core AdvancedとAFM 3 Cloud（PCC）の実機報告では、モデル名・OS・課題・測定単位を確認した。他モデルを扱った論文からは試験方法を採用した。以下の外部測定値は各著者の環境で得られた値である。

## 同世代の実機事例

| 出典と条件 | 観測 | 今回の検証との関係 |
|---|---|---|
| Core Advanced、MacBook Pro M3 Max・48 GB、macOS 27.0.1（26A434）、10月24日 | 入力長6水準、事実の位置3水準、各組2件で、1件の合言葉を36件すべて正しく取得。最長入力は6,996トークン。各条件の各値は1回 | 1個の値を拾う試験の参考になる。訂正前の値と現在の値が同居する課題、答えが資料にない課題を追加する根拠にもなる。[実機報告 §28.3](https://github.com/juliensimon/apple-fm-mac/blob/main/REPORT.md#283-long-context-retrieval-m)・[入力生成コード](https://github.com/juliensimon/apple-fm-mac/blob/main/data/card_inputs/needle_test.py) |
| AFM 3 Cloud、macOS 27.2開発ベータ2、各入力長3回の中央値 | 最初のトークンまでの時間は入力1Kで1.2秒、8Kで3.5秒、26Kで11.2秒。生成速度は順に143、134、118 tok/s | 端末内の生成時間とPCCへの往復を含む待ち時間は別々に記録する。日本語の正確さはこの投稿からは分からない。[測定者の報告](https://www.linkedin.com/posts/benbuschmann_i-spent-an-afternoon-testing-apples-new-activity-7508673400467542016-lQiY) |
| macOS 27.0（26A428）、Swift 6.4、オンデバイスのvariantは未報告 | カスタムツールについて、Swift経由と当時の `fm serve` 経由とで、呼び出しをアプリが取得できるかが異なった | 返答の文章に加えて、実際に呼んだツール名・引数・回数を記録する。モデルがツール呼び出しを文章で提案しただけの場合も区別できる。[プロジェクトの計測記録](https://github.com/SpaceCorps/open-apple-models/blob/main/docs/RESEARCH.md) |

11月5日のmacOS 27.2実機例では、4枚の領収書から店舗・日付・合計額を抽出できた一方、日付の表記に揺れがあった。今回の納品書は、複数の品番と行ごとの数量を注文と照合する。表の入力にはApple Visionの行・セルAPIを使った。[Core Advanced実機報告](https://www.starryhope.com/mac/apple-fm-command-mac/)・[Appleの表認識サンプル](https://developer.apple.com/documentation/vision/recognize-tables-within-a-document)

## 日本語の用途に持ち込む試験方法

- **抽出と棄権**　GRAB-RAGは同じ質問の根拠を、十分・劣化・欠落・誤誘導の4条件に変えている。AACL-IJCNLP 2026での試験対象は英語QAと38億〜80億パラメータの3モデル。AFMには、値の正しさ、資料不足で保留できた割合、正解があるのに保留した割合を別々に測る設計を移せる。[GRAB-RAG論文](https://aclanthology.org/2026.aacl-long.153/)・[著者の実装](https://github.com/andre44s/grab-rag)
- **原文との照合**　LangExtractは抽出値と原文の文字位置を対応付ける。ACL-Verbatimは論文中の逐語的な一節を答えとして返す。たとえば日時の変更通知なら、引用された日時が実際に本文にあるかを通常のコードで確認し、そのうえで変更後の値かどうかを採点できる。[LangExtract](https://github.com/google/langextract)・[ACL-Verbatim論文](https://aclanthology.org/2026.wasp-1.4/)
- **構造化生成**　AACL-IJCNLP 2026の2論文は、キーの文言とフィールド順をそれぞれ扱う。AFMへの直接の性能予測はできない。抽出では「根拠→値」と「値→根拠」で宣言順だけを変え、構文の正しさ、値の正しさ、根拠との対応を分けて比べられる。[Schema-Key Wording](https://aclanthology.org/2026.aacl-long.116/)・[Structure Tax](https://aclanthology.org/2026.aacl-long.209/)
- **ツール利用**　CAREFUL-Bench（11月3日改訂のプレプリント）は、最終状態に加えて、重複した書き込みや不要な読み出しも記録する。ファイルや表を扱う日本語指示では、架空のファイル一覧で操作対象・引数・回数・最終状態を採点できる。[CAREFUL-Bench](https://arxiv.org/abs/2611.02978)・[参照元のBFCL](https://proceedings.mlr.press/v267/patil25a.html)

## モデル指定・改善範囲

- AppleはCore Advancedを総計200億、要求に応じて10億〜40億のパラメータが有効になる疎なモデルと説明している。専門部分を逐次読み込む設計は公表されている。これだけでは、個々の端末でストレージI/Oが何秒を占めたかは分からない。[Appleのアーキテクチャ解説](https://machinelearning.apple.com/research/introducing-third-generation-of-apple-foundation-models)
- WWDC26では `fm respond --model pcc`、チャットの `/model`、SwiftからのPCC呼び出しを実演している。古い27.0ベータには `system` のみを受理した実測もある。このためOSビルドと、その端末のCLIが受理した経路を併記する。オンデバイスの実体は公開APIのvariantとcontextSizeを確認する。[CLIの公式実演](https://developer.apple.com/videos/play/wwdc2026/334/)・[PCCのSwift APIと割当](https://developer.apple.com/videos/play/wwdc2026/319/)・[旧ビルドの引数記録](https://github.com/llostinthesauce/fm-guide/blob/main/docs/cli-reference.md)
- 公式Python SDKはオンデバイス向けで、SDKのコードにはApache-2.0が適用される。Appleソフトウェア・サービスのプログラム利用は明示許可の範囲に限られ、Appleモデルの出力で他のAIモデルを学習・改善することにも制限がある。アプリでのPCC利用にはApple所定の資格とエンタイトルメントがある。[Python SDK](https://github.com/apple/python-apple-fm-sdk)・[SDKライセンス](https://github.com/apple/python-apple-fm-sdk/blob/main/LICENSE.md)・[Xcode規約](https://www.apple.com/legal/sla/docs/xcode.pdf)・[利用要件](https://developer.apple.com/support/terms/acceptable-use-requirements-for-the-foundation-models-framework/)・[PCCの利用資格](https://developer.apple.com/private-cloud-compute/)
- 公開アダプタ訓練キットは26.0.0が最終版で、AppleはOS 27以降との非互換を明記している。この世代で試せる改善には、公式APIを通じた入力の絞り込み、スキーマ、ツール、セッションの使い方がある。[アダプタの対応表](https://developer.apple.com/apple-intelligence/foundation-models-adapter/)・[Foundation Modelsの公式案内](https://developer.apple.com/foundation-models-framework/)

今回調べた範囲では、これらの方法をCore AdvancedとPCCの双方で同一の日本語問題・同一の採点器にかけた独立研究は見つからなかった。
