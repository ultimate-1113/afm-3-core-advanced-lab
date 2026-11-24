# AFM 3 日本語ハーネス追試

Core AdvancedとCloudに同じ問題を出し、モデル単体、構造化生成、機械検査、外部実行器を比較した。追加の12問では他者の編集が入る表を扱い、全文更新・文脈付き差分・読み直しを比較した。[結果と事例](findings.md)・[先行研究と公開実装](sources.md)

表編集で残った誤適用を調べるため、Core Advancedで対象行の限定と書き込み直前の条件検査を試した。前回の12件と追加32件について、完了・誤適用・保留を記録した。[追試の結果と表編集CLI](edit-guard/README.md)

## 結果を再採点する

macOSやモデルを使わず、Python 3.9以上で同梱の回答を検証できる。リポジトリのルートから実行する。

```sh
cd studies/2026-11-harness
python3 -B report.py verify
python3 -B partial.py verify
python3 -B edits/report.py verify
python3 -B edit-guard/study.py verify
python3 -B test_harness.py
python3 -B edits/test_edits.py
python3 -B edit-guard/test_guard.py
```

## Apple Terminalで再実行する

今回の実機はMac mini M6、32 GB、内蔵のモデルストレージ256 GB、macOS 27.2.1（26B131）。検証用データは外部SSD上に置いた。OS付属のfmが該当モデルを表示する環境で、次のいずれかを実行する。PCCへの入力は同梱の合成資料だけである。

```sh
zsh './Run Harness.command' system
zsh './edits/Run Edits.command' system
zsh './Run Harness.command' pcc
zsh './edits/Run Edits.command' pcc
```

進捗と生の回答は各試験の `build/session` に保存する。同じコマンドの再実行は完了済みの入力ハッシュを照合し、未完分を処理する。PCCは生成前後の枠表示と生成自身の上限エラーを確認し、同日中の再開を抑止する。生成中にプロセスが中断された場合、`inflight.json` と保存された出力を調べ、応答取得の有無を確認してから再送を判断する。

位置付きOCRの再測定は以下で行う。公開結果は固定済みの文字・座標から再生するので、再測定値は別ファイルに保存する。

```sh
mkdir -p build
xcrun swiftc -O -parse-as-library Boxes.swift -o build/boxes
python3 -B geometry.py build/boxes build/vision-new.jsonl
```

[事前登録](protocol.md)・[入力・画像・採点器のハッシュ](lock.json)・[追加試験の事前登録](edits/design.md)・[追加試験のハッシュ](edits/lock.json)。最初の利用枠エラー後に輸送処理を更新した。生成側の上限認識と追加試験の起動経路を修正し、初版のコードとハッシュも保存した。課題、採点、生成した入力の同一性は両版で照合できる。[輸送処理の履歴](provenance/transport.json)
