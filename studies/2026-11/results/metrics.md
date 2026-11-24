# ケース別集計

実験用時刻は秒。完全一致の分母は実際に完了したケース数。全回答は cases.jsonl、各モデル呼び出しは calls.jsonl に収録した。

## 10月の固定入力の再測定

| 条件 | 完全一致 | 件数 |
|---|---|---|
| diff-heldout/baseline | 6 | 30 |
| diff-heldout/fewshot | 29 | 30 |
| extraction-heldout/baseline | 21 | 30 |
| extraction-heldout/guided | 20 | 30 |
| regressions/baseline | 0 | 6 |
| regressions/guided | 0 | 6 |
| table-heldout/baseline | 14 | 30 |
| table-heldout/delegated_examples | 18 | 30 |


## 共通30問

| 方式 | 比較済み | Core正解 | PCC正解 | Coreのみ正解 | PCCのみ正解 |
|---|---|---|---|---|---|
| baseline | 30 | 8 | 17 | 0 | 9 |
| dev_selected | 30 | 12 | 16 | 0 | 4 |


## 調整用

| 用途 | 経路 | 方式 | 完全一致 | モデル呼出し | 初回表示中央値 | 完了中央値 |
|---|---|---|---|---|---|---|
| delivery | code | code | 3/10 | 0 | — | 0.186 |
| delivery | system | flat | 0/10 | 10 | 0.453 | 0.979 |
| delivery | system | image | 0/10 | 10 | 0.775 | 1.216 |
| delivery | system | table | 1/10 | 10 | 0.435 | 1.01 |
| notice | system | direct | 4/10 | 10 | 0.425 | 0.526 |
| notice | system | evidence | 9/10 | 10 | 0.507 | 1.357 |
| update | system | batch | 4/10 | 10 | 0.403 | 0.522 |
| update | system | step | 2/10 | 20 | 0.356 | 0.809 |


## 初見評価

| 用途 | 経路 | 方式 | 完全一致 | モデル呼出し | 初回表示中央値 | 完了中央値 |
|---|---|---|---|---|---|---|
| delivery | code | code | 11/30 | 0 | — | 0.184 |
| delivery | pcc | flat | 3/8 | 8 | 0.733 | 1.223 |
| delivery | pcc | image | 2/8 | 8 | 1.047 | 1.383 |
| delivery | pcc | table | 1/8 | 8 | 0.742 | 1.318 |
| delivery | system | flat | 0/30 | 30 | 0.454 | 1.016 |
| delivery | system | image | 0/30 | 30 | 0.812 | 1.229 |
| delivery | system | table | 1/30 | 30 | 0.446 | 1.018 |
| notice | pcc | direct | 8/8 | 8 | 0.666 | 0.775 |
| notice | pcc | evidence | 8/8 | 8 | 0.828 | 1.49 |
| notice | system | direct | 12/30 | 30 | 0.438 | 0.533 |
| notice | system | evidence | 30/30 | 30 | 0.525 | 1.381 |
| update | pcc | batch | 7/8 | 8 | 0.678 | 0.96 |
| update | pcc | step | 8/8 | 16 | 0.666 | 1.635 |
| update | system | batch | 11/30 | 30 | 0.411 | 0.54 |
| update | system | step | 6/30 | 60 | 0.36 | 0.887 |


## 旧失敗6問・共通CLI

| 用途 | 経路 | 方式 | 完全一致 | モデル呼出し | 初回表示中央値 | 完了中央値 |
|---|---|---|---|---|---|---|
| regression | pcc | baseline | 0/6 | 6 | 0.593 | 0.776 |
| regression | system | baseline | 0/6 | 6 | 0.387 | 0.471 |


## 長文

| 全文の目標トークン | 経路 | 入力 | 完全一致 | 初回表示中央値 | 完了中央値 |
|---|---|---|---|---|---|
| 4000 | system | full | 0/3 | 2.522 | 2.724 |
| 4000 | pcc | full | 3/3 | 2.012 | 2.108 |
| 12000 | system | select | 2/3 | 0.592 | 0.673 |
| 12000 | pcc | full | 3/3 | 5.118 | 5.243 |
| 24000 | system | select | 2/3 | 0.575 | 0.634 |
| 24000 | pcc | full | 3/3 | 10.218 | 10.37 |
