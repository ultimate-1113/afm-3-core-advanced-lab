# AFM 3 の日本語用途評価（2026年11月）

AFM 3 Core Advancedと、Private Cloud Compute（PCC）上のAFM 3 Cloudを、同じMacの日本語課題で評価した。用途は予定の抽出、納品照合、表の更新、長い議事録の確認である。[実測結果](findings.md)・[全方式の集計](results/metrics.md)・[先行研究と公開実装](sources.md)

## 測定環境

| 項目 | 条件 |
|---|---|
| Mac | Mac mini、Apple M6、メモリ32 GiB、内蔵SSD 256 GB（デバイス容量251,000,193,024 bytes） |
| 配置 | オンデバイスモデルはOS管理の内蔵ストレージ。検証コードとログは外付けSSD。PCCはネットワーク経由 |
| OS | macOS 27.2.1（26B131）、Command Line Tools SDK 27.2 |
| 端末モデル | AFM 3 Core Advanced、Swiftの実測コンテキスト8,192。端末のvariantはOSが決定 |
| サーバーモデル | Apple純正CLIの pcc が表示する AFM 3 Cloud。Appleの公称コンテキスト32K |
| 新規試験 | Appleのターミナルで同梱テストアプリから fm respond を起動。各回でモデルを明示し、greedy、stream、新規セッション、同時要求1件。推論強度はCLI標準 |
| 10月の追試 | 公開版の入力・プロンプト・採点器のSHA-256を照合。既存のSwift runner v3を使用。現環境のCLT単独では以前の @Generable マクロを再ビルドできなかった |

このMacでは、ターミナルで起動したPythonから fm models を子プロセスとして呼んでも、PCCにターミナルでの実行を求めるメッセージが出た。テストアプリのPCC経路ではターミナルのシェルが純正 fm を直接実行し、Pythonは合成入力の準備、出力の取得、採点を担当する。各応答で公式トランスクリプトのモデル名を照合する。

CLIのモデル指定は以下の通り。PCCの実際の利用可否と利用枠はAppleのターミナルから確認できる。SwiftアプリからPCCを利用する際はAppleの管理対象エンタイトルメントが必要である。[AppleのCLI実演](https://developer.apple.com/videos/play/wwdc2026/334/)・[Appleのモデル検出仕様](https://developer.apple.com/documentation/foundationmodels/detecting-available-apple-foundation-models)・[PCCの開発条件](https://developer.apple.com/private-cloud-compute/)

~~~sh
fm models
fm quota-usage --model pcc
fm respond --model system '東京都の都庁所在地を短く答えてください。'
fm respond --model pcc '東京都の都庁所在地を短く答えてください。'
~~~

## 再実行

このディレクトリの「Run Evaluation.command」をAppleのターミナルで開く。配付済みの固定資料を検証し、Visionの実行ファイルと比較用OCRキャッシュをbuild内に作る。初回にAppleのCLI利用条件の確認を求められる場合は本人が確認する。PCCに送る入力はこのリポジトリの合成データである。

~~~sh
cd studies/2026-11
zsh './Run Evaluation.command'
~~~

PCC段階のみを現在の対話シェルで再開する場合は、このディレクトリに移動し、Appleのターミナルで次の行を実行する。

~~~sh
source './Run PCC.zsh'
~~~

Coreだけの実行は末尾に --only system、PCCだけなら --only pcc を付ける。初回のCore＋PCC比較には同じターミナルから両方を実行する。出力先は build/session、別の独立試行には --work build/another-session を指定する。macOS付属PythonとSwiftコンパイラで動作する。

PCCはモデル呼び出しの前後で利用枠を調べ、上限間近または到達が表示された日には以降の送信を止める。翌日以降は同じコマンドで続きから再開できる。途中まで完了した複数段の処理も呼び出し単位で復元する。枠の状態と通信途絶は正答率の分母から区別し、未実施件数を記録する。Appleが27.3以降の対象機能に示したプラン別倍率から、この27.2.1の具体的な利用回数は算出できない。[料金プランと利用枠](https://support.apple.com/en-us/127901)・[PCCの利用枠とコンテキスト](https://developer.apple.com/documentation/foundationmodels/adding-server-side-intelligence-with-private-cloud-compute)

10月試験の再現と集計は次の順で行う。--runner には10月の検証用実行ファイル、または同じソースと対応するXcodeでビルドした実行ファイルを指定する。再ビルドした場合は保存されるバイナリハッシュで区別する。

~~~sh
python3 -B legacy.py --runner ../../bin/afm-runner --work build/october
python3 -B report.py --work build/session --legacy-results build/october/results --ocr build/vision-cache --out build/report
python3 -B verify.py build/report
python3 -B test_study.py
~~~

新しいモデル呼び出しが不要な確認には python3 -B verify.py results を使う。試験用画像・資料の再生成には python3 -B fixtures.py --vision build/vision-tool --out build/regenerated を使用する。フォント、Vision、トークナイザーはOS版に依存する。

## 対象と採点

- **旧試験**　6問×2設定、3用途×30問×2設定。元の採点器と入力を使い、11月の生の回答・使用量・採点を保存した。
- **新用途**　各領域で調整10件、初見評価30件。調整で完全一致が最も多い方式を選び、同率ならモデル呼び出し回数、完了時間の中央値、方式名の順で決める。通常コードだけの方式は独立した比較条件とする。初見資料は調整資料と文書・IDを分けた。通知の初見30件は8つの会議に対する条件違いを含む。独立した30種類の文体としては扱えない。
- **共通30問**　旧失敗6問と、[事前に固定した各8問](fixtures/shared.json)。同じ基本方式と同じ調整採用方式で両モデルを比べる。PCCにも初見8問の各モデル方式を適用する。多段方式では、2回目以降の入力にそのモデルの前段回答が入る。
- **変更通知**　文書には会議IDと「確定」「案」「失効」等の発行状態がある。直接抽出のほか、各値に文書IDと原文引用を付ける方式を試す。後者は会議ID・発行状態・引用の実在・値の裏付けを通常コードで照合する。日付・時刻・会場・参加班を採点し、誤った値、答えられるのに保留した項目、正当な保留を別々に集計する。
- **納品照合**　合成PNGと発注表を入力とする。画像入力、平文OCR、Visionの表認識、表認識からの通常コード突合を比較。品番ごとの受入数と発注差異の両方が合えば完全一致。省略品番、別名、未納、見本除外、分納を含む。OCRは各条件で実行し、事前に保存した[認識結果](results/vision.jsonl)との差を記録する。
- **表の更新**　依頼を一括で解釈する方式と、一つずつ処理して現在の表・操作履歴を次へ渡す方式を比較する。許可操作は追加、数量設定、削除。操作列をメモリ上で再生し、最終状態・順序・余計な操作・欠落・引数の有効性を検査する。実システムを変更するツールの発火率はこの試験では測定していない。
- **長文**　3つの合成議事録を約4K・12K・24Kトークンに展開。会場、締切、上限、保留事項の4項目がすべて一致すれば正解。同じ長さにつき3件であり、長さをまたいで同じ決定を共有する。4Kでは同じ全文を送る。12K以上のCoreでは事業名と質問語の重なりで上位12段落を選び、文書順で渡す。検索は原文と質問だけを読む。対象名が明示された資料に限った結果である。

[フィクスチャのSHA-256](fixtures/lock.json)・[個々の回答と利用枠](results/calls.jsonl)・[個々の採点と計時](results/cases.jsonl)・[10月追試のケース別回答](results/legacy-cases.jsonl)

## 時間と使用量

初回表示は子プロセス起動からCLI標準出力に最初の表示可能な応答が届くまで。構造化出力では完成したオブジェクトがまとめて届く場合がある。完了時間 active_e2e_s は実測した画像読み取り・段落検索などの入力準備と各CLI呼び出しを含む。Coreではローカル採点もこの時間に含み、PCCのローカル採点は計時後に行った。PCCにはネットワーク往復が含まれる。利用枠確認とチェックポイント書き込みを含む各呼び出しのホスト経過は host_run_s に別途記録する。Coreはプロセスのパイプ、PCCはシェルの標準出力から初回表示を測った。PCCの採点後の整合性再検査は完了時間に含めない。

CLIが実使用量を返した場合だけ usage に載せる。retokenized_output_text_tokens は保存した出力文字列を端末の fm count-tokens で後から数えた値で、サーバー内の推論・画像・課金トークンを含まない。長文の document_tokens は全文の実測で、指示と出力用の余白を含まない。

独自コードと手書きの合成資料には[リポジトリのMITライセンス](../../LICENSE)が適用される。モデル出力と第三者の資料は[既存の取り扱い](../../THIRD_PARTY_NOTICES.md)に従う。公開版には合成資料、その測定値、出典へのリンクを収録した。
