# ライセンス再精査と公開範囲

確認日: 2026-10-02。公開対象は独自のCLIテストアプリ、検証スクリプト、合成入力／正解、先行調査、実測ログ。Apple製ソフトウェアやモデル資産を公開物へ含めない構成にした。以下は公開文書・実機の利用条件と実際の配布内容を照合した記録で、全利用形態の適法性を保証するものではない。

| 対象 | 確認・公開方法 |
|---|---|
| 独自Swift/Pythonコード・文書・手書きfixture | MIT。著作権・許諾表示をLICENSEへ保存 |
| Apple Python SDK 0.2.1 | Apache-2.0。導入物のLICENSEと公式v0.2.1がバイト単位で一致。ソースやバイナリはvendoringせず、別venvへインストールする依存関係 |
| 公開APIの呼び出し | FrameworkとSDKのinterfaceを利用する独立コード。Apache-2.0の定義は、分離可能なinterfaceへのリンクを派生物へ含めない。SDKをMITへ変更する意味ではない |
| OS管理のAFM、fm、Framework | リポジトリには含めない。公開API／公式CLIの通常の呼び出しを使い、実行時にはAppleの条件に従う |
| AFMの生成結果 | AI生成として表示し、失敗例を含む評価証拠として公開。MITの対象へ拡張せず、第三者の既存権利を消さない |
| 他AIモデルへの出力利用 | 実機macOS SLA 6.Eは、AI出力を別AIモデルの学習・fine-tuning・改善へ使うことを禁止している。この調査では行っておらず、ログにもその用途の許諾を付与しない |
| 重み・量子化・内部カーネル | 実機macOS SLA 2.Nの制限と公開APIの範囲を確認。抽出・改変・再配布は今回の公開対象に含めない |
| アダプタ学習 | 旧公式ツールキットはOS27以降非対応。現行Core Advancedの改善方法とは扱わない |
| 参照した海外コード・記事 | リンクと独自の短い要約のみ。コード・画像・長い引用を転載しない |

Apple SDKのApache-2.0第4条は、ライセンスの提供、変更ファイルの表示、既存の権利表示の保持、該当するNOTICEの維持を定める。公式v0.2.1のルートと導入物を確認し、SDKに別のNOTICEファイルは見つからなかった。今回はSDKを改変・同梱していないが、ライセンスと出典を記載した。[公式LICENSE](https://github.com/apple/python-apple-fm-sdk/blob/v0.2.1/LICENSE.md)。

Developer Program License Agreement 3.3.11(A)はFrameworkの利用にAcceptable Use Requirementsを適用する。安全策の回避、学習データの抽出、権利侵害等を許諾しない。この検証の分類対象は合成した投稿であり、人の属性の評価や重要な自動意思決定を行わない。資料中の「BANANA」等は入力データと命令の区別の試験で、安全ポリシーの解除はしない。[開発者契約](https://developer.apple.com/support/terms/apple-developer-program-license-agreement/)、[Acceptable Use Requirements](https://developer.apple.com/support/terms/acceptable-use-requirements-for-the-foundation-models-framework/)。

同契約9.1は公開済み情報を機密情報の例外としている。今回の記述は公開SDK・公式文書・利用可能な実機モデルへの自作要求から得た結果で、Appleの非公開ソース・重み・内部資料を含めない。今後の未公開OS／SDKや別契約下の情報を同じ扱いで公開できるという判断にはしない。[同契約9.1](https://developer.apple.com/support/terms/apple-developer-program-license-agreement/)。

生成出力について実機SLAは、既存権利を留保してAppleが所有権を主張しない一方、利用者自身による権利と用途の判断を求める。出力の評価ログ公開を一律に禁止する条項は今回の該当箇所では確認しなかった。公開範囲の判断として、短い合成タスクに対する出力と測定値に限定し、モデルやOSを再配布しない。[Appleソフトウェアライセンス](https://www.apple.com/legal/sla/)。

精査した証拠:

- SDKタグv0.2.1 commit: `84841bb71b22996c00bb67e3b4c7ae1f985315ea`
- LICENSE upstream blob: `7a4a3ea2424c09fbe48d455aed1eaa94d9124835`
- 同梱LICENSE SHA256: `58d1e17ffe5109a7ae296caafcadfdbe6a7d176f0bc4ab01e12a689b0499d8bd`
- 実機macOSの英語SLA HTML SHA256: `48badb0bb42e0bcd72d84ddc51c45c37896ec5ec753201b381262745ec10ae63`（全文は再配布せず、条項番号と確認結果のみ記載）

独自ラッパーのMIT、SDKのApache-2.0、AppleのOS／モデルの条件、生成結果の既存権利は別々に扱う。公開した独自コードの改良は可能でも、Appleのモデル自体への改変許諾を意味しない。
