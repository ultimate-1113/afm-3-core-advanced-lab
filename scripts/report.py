import json, argparse, statistics, collections, csv, time, math
from pathlib import Path
from lab import ROOT, grade
LABELS={'japanese':'日本語変換','extraction':'情報抽出','classification':'分類','search':'検索補助','grounded':'資料に基づく説明','table':'表・操作仕様','image':'画像理解','diff':'差分・不足検出','creative':'短い創作','tools':'ツール利用'}
def read(name):
    p=ROOT/'results'/name
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []
def current(rows):
    for r in rows:r['grade']=grade(r['case'],r['result'],r['method'])
    return rows
def median(rows,key):
    a=[r['result'][key] for r in rows if isinstance(r['result'].get(key),(float,int))]
    return statistics.median(a) if a else None
def stats(rows):
    return dict(n=len(rows),passed=sum(r['grade']['pass'] for r in rows),semantic=sum(bool(r['grade']['semantic']) for r in rows),json=sum(r['grade']['format'] for r in rows),schema=sum(r['grade'].get('schema') is True for r in rows),complete=sum(r['grade']['complete'] for r in rows),median_e2e_s=median(rows,'host_e2e_s'),median_ttft_s=median(rows,'ttft_s'))
def select():
    rows=current(read('tuning.jsonl'));groups=collections.defaultdict(list)
    for r in rows:groups[(r['case']['domain'],r['method'])].append(r)
    choices={};details={}
    for domain in ['extraction','table','diff']:
        candidates={method:stats(rs) for (d,method),rs in groups.items() if d==domain and method!='baseline'}
        assert candidates and all(s['n']==10 for s in candidates.values())
        choices[domain]=max(candidates,key=lambda m:(candidates[m]['passed'],-candidates[m]['median_e2e_s']))
        details[domain]=dict(baseline=stats(groups[(domain,'baseline')]),candidates=candidates,chosen=choices[domain])
    (ROOT/'reports/selected-methods.json').write_text(json.dumps(choices,ensure_ascii=False,indent=2))
    (ROOT/'reports/tuning-selection.json').write_text(json.dumps({'rule':'10 dev cases only; greatest joint format/schema/semantic/completion pass count, then lower median E2E. Heldout not read.','time':time.time(),'selection':details},ensure_ascii=False,indent=2))
    print(json.dumps(details,ensure_ascii=False,indent=2))

def final():
    screen=current(read('screen.jsonl'));tune=current(read('tuning.jsonl'));held=current(read('heldout.jsonl'));reg=current(read('regressions.jsonl'));imgs=current(read('images.jsonl'));files=current(read('files.jsonl'))
    # Discard invalid timer/resource measurements from analysis, keep originals on disk.
    runtime=[r for r in read('runtime.jsonl') if r['kind'] not in ['cancel','after-cancel','queue']]+read('recovery-final.jsonl')+read('resources.jsonl')
    assert len(screen)==60 and len(reg)==12 and len(held)==180 and len(imgs)==12
    decisions=json.loads((ROOT/'reports/selected-methods.json').read_text());summary={'screen':{},'heldout':{},'runtime':{},'quality_case_runs':len(screen)+len(tune)+len(held)+len(reg)+len(imgs)+len(files)}
    lines=['# AFM 3 Core Advanced 検証結果','','測定期間: 2026-10-01〜02。macOS27.0.1（26A434）、Mac mini M6、32GB、内蔵SSD 256GB（公称）。モデル資産はOS管理の内蔵ストレージ、検証コード・入力・ログは外付けSSDに配置。全Swift実行開始時にCore Advanced・8192を確認。SSDのcold loadや読み取り速度を単独測定したものではない。','', '## 60ケースの用途探索','', '「内容」は正解データとの意味の一致、自然文・検索・創作では数値／重要語／長さ／一部の誇張語の簡易検査。「形式」はJSON構文と指定キー、「適合」は形式・スキーマ・内容・完了・要求されたツール使用をすべて満たしたケース。短い創作や文章は機械採点が表現の良さを保証しない。6例だけからモデル全体を点数化しない。','', '| 分野 | 内容一致／簡易検査 | 形式 | 全条件適合 | 完了中央値 |','|---|---:|---:|---:|---:|']
    for domain in LABELS:
        rs=[r for r in screen if r['case']['domain']==domain];s=stats(rs);summary['screen'][domain]=s
        lines.append(f"| {LABELS[domain]} | {s['semantic']}/6 | {s['json']}/6 | {s['passed']}/6 | {s['median_e2e_s']:.3f}秒 |")
    lines+=['','## 3分野の未使用30ケースによる評価','','用途探索で誤りと改善余地が見えた、抽出・表操作・差分検出を選んだ。各10ケースで指示／スキーマ／例示／処理分割／コード分担を調整。最大適合数、同数なら完了中央値の短い方法を評価前に固定。評価30ケースは各10種類のテンプレート×3変種で、実業務全体を代表する無作為標本ではない。','','| 分野・方法 | 意味一致 | スキーマ適合 | 全条件適合 | 完了中央値 |','|---|---:|---:|---:|---:|']
    for domain in ['extraction','table','diff']:
        summary['heldout'][domain]={}
        for method in ['baseline',decisions[domain]]:
            rs=[r for r in held if r['case']['domain']==domain and r['method']==method];assert len(rs)==30;s=stats(rs);summary['heldout'][domain][method]=s
            lines.append(f"| {LABELS[domain]}・{method} | {s['semantic']}/30 | {s['schema']}/30 | {s['passed']}/30 | {s['median_e2e_s']:.3f}秒 |")
    lines+=['','baselineはJSON指示だけ。guidedは公開スキーマ＋注意書き。fewshotはそれに例示と項目説明。delegated_examplesは操作仕様の抽出だけをAFMに任せ、許可した通常コードが集計／並べ替えを実行する。複数の変更を同時に加えた比較なので、改善を単独の要因へ帰属させない。','', '## 元レポートの主要失敗例','','元と同じ問題を短いJSON回答形式で再検証した。元の自由文／推論ログを完全再現した試験ではない。','', '| 問題 | JSON指示のみ | スキーマ＋注意書き |','|---|---:|---:|']
    names=['正直者・嘘つき','Python内部リスト参照','dictの例外と原因','組合せ最適化','CPUだけを過去設定へ戻す','年なし予定変更の抽出']
    for i,name in enumerate(names,1):
        vals=[]
        for method in ['baseline','guided']:
            row=next(r for r in reg if r['case']['id']==f'regression-{i:02}' and r['method']==method);vals.append('適合' if row['grade']['pass'] else '失敗')
        lines.append(f'| {name} | {vals[0]} | {vals[1]} |')
    lines+=['','## 画像とVision OCR','','英数字が明瞭な合成スクリーンショット6枚。写真、手書き、日本語の実帳票、複雑な表に一般化しない。','', '| 方法 | 意味一致 | 全条件適合 | 完了中央値 |','|---|---:|---:|---:|']
    for method,rs in [('native-baseline',[r for r in screen if r['case']['domain']=='image']),('native-guided',[r for r in imgs if r['method']=='guided']),('Vision OCR + guided',[r for r in imgs if r['method']=='ocr'])]:
        s=stats(rs);lines.append(f"| {method} | {s['semantic']}/6 | {s['passed']}/6 | {s['median_e2e_s']:.3f}秒 |")
    if files:
        s=stats(files);summary['files']=s;lines+=['',f"ファイル操作の補足6例: 仕様の適合{s['passed']}/6。合成ファイルのコピー・改名だけを独立した作業フォルダで確認。既知の正解に一致し、対象とパスの検査に合格した場合だけ実行した。残りはプレビュー。実製品では既知の正解がないので、この実行条件をそのまま自動化へ流用しない。"]
    groups=collections.defaultdict(list)
    for row in runtime:groups[row['kind']].append(row)
    lines+=['','## 呼び出し・キャッシュ・入力処理','','モデル資産のcold bootやキャッシュの強制削除はしていない。以下は既に利用可能な実機での比較。prewarmの待ち時間は別枠に含め、待機を隠して高速化と表現しない。','', '| 試験 | n | TTFT中央値 | 要求完了中央値 |','|---|---:|---:|---:|']
    for kind in ['cache-fresh','cache-prewarm','cache-continue','cache-restore','route-swift','route-sdk','route-fm','route-serve-tcp','route-serve-unix','processing-full','processing-pruned','processing-split-date','processing-split-people','result-cache-miss','result-cache-hit']:
        rs=groups[kind]
        if not rs:continue
        ttft=median(rs,'ttft_s');et=median(rs,'host_e2e_s') or median(rs,'elapsed_s');summary['runtime'][kind]={'n':len(rs),'median_ttft_s':ttft,'median_e2e_s':et}
        lines.append(f"| {kind} | {len(rs)} | {ttft:.3f}秒 | {et:.3f}秒 |" if ttft is not None else f"| {kind} | {len(rs)} | 未取得／生成なし | {et:.3f}秒 |")
    lines+=['','TTFTはAPIまたは経路で最初の可視応答を観測した時刻。Python0.2.1の文字列ストリームでは実使用量・variantの公開プロパティがないため、隣接するSwift gateを記録し、使用量はnull。fm CLIには同じ最大出力設定がなく、serveはtemperature=0でgreedyと同一の内部設定か確認できない。短い同一入力で通信・起動を含む体感差を測ったが、生成エンジンの純粋な速度差とは断定しない。Swiftの前処理時間・生成時間は生ログに分離している。']
    lines+=['','入力処理試験では、既知の関連部分をコードで選び、入力3315→125トークン、完了中央値3.178→0.857秒へ短縮した。内容は双方3/3一致。全文の3例ではJSONフェンスを付けたため、厳密なJSONのみという形式には違反した。関連部分を事前に判断できる試験であり、任意の資料を削っても情報を保てるという結果ではない。']
    for kind in ['cache-fresh','cache-prewarm','cache-continue','cache-restore']:
        rs=groups[kind];values=[(r['result'].get('cached_tokens',0),r['result'].get('input_tokens',0)) for r in rs]
        lines.append(f"\n{kind}のcached/input（各回）: {values}。")
    lines+=['','prewarmは584/592入力トークンのキャッシュを確認したが、今回はTTFTの明確な短縮を確認できず、1200msの待機込みでは遅くなった。会話継続のcached=0も観測したので、セッションを保持すれば常にキャッシュが効くとは仮定しない。復元は会話継続より速い回があったが、キャッシュヒットは0であり、サイズ差と3反復のばらつきから最速方式とは判断しない。','', '## 背景負荷','','周期的な小CPU処理を前景作業の代理として測定。実際の前景アプリやGPU負荷、消費電力は未測定。priority=normalはuserInitiated、backgroundはTaskPriority.background。共有推論サービスが受け取った優先度そのものは公開APIで確認できない。','', '| 優先度 | 同時要求 | 間隔 | 要求数 | 合計時間 | 前景処理p95 | スケジュール遅延p95 |','|---|---:|---:|---:|---:|---:|---:|']
    for row in groups['load']:
        q=row['request'];probe=row['probe'];lines.append(f"| {q['priority']} | {q['concurrency']} | {q['gap_ms']}ms | {len(row['responses'])} | {row['result']['elapsed_s']:.3f}秒 | {probe['work_p95_s']*1000:.3f}ms | {probe['scheduling_p95_s']*1000:.3f}ms |")
    idle=groups['load-idle'][0]['probe'] if groups['load-idle'] else {};lines+=['',f"無負荷3秒の前景代理処理p95: {idle.get('work_p95_s',0)*1000:.3f}ms。短い測定であるためQoS効果の因果推定はできない。メモリ圧迫・swap・CPU/RSSの時系列はruntime.jsonlへ保存。"]
    samples=[s for r in groups['resource-profile'] for s in r.get('process_samples',[])];rss=[];cpu=[]
    for sample in samples:
        for line in sample['processes']:
            parts=line.split()
            if len(parts)>=4:
                try:cpu.append(float(parts[-2]));rss.append(int(parts[-1]))
                except ValueError:pass
    summary['resources']={'samples':len(samples),'max_observed_process_rss_kib':max(rss,default=None),'max_observed_process_cpu_percent':max(cpu,default=None)}
    lines+=['',f"補足CPU/RSS採取: {len(samples)}時点、対象プロセスRSS最大{max(rss,default=0)/1024:.1f}MiB、CPU表示最大{max(cpu,default=0):.1f}%（プロセス単位）。GPU共有メモリや全モデル資産の総量ではない。初回はpsのcomm表示が短く空になったため、ucommで別測定した。測定した設定でswap使用0MB、memory_pressureのfree表示77〜78%だった。free表示は単純な空きRAM量とは異なる。QoS変更による前景代理指標の明確な改善は確認できず、同時要求2件でも処理速度の倍増は観測しなかった。"]
    sdk=read('sdk-responsiveness.jsonl');lines+=['','## Python SDKの背景処理改善','','公式SDK0.2.1はasyncのストリーム内で同期queue待ちを行っている。SDK本体を変更せず、公開APIを専用スレッド／専用イベントループで動かすラッパーを実装した。10msの別処理を交互順3反復で測定。','', '| 方法 | n | 補助処理の最大間隔（各回） | 生成完了中央値 |','|---|---:|---|---:|']
    for method in ['direct','thread-wrapper']:
        rs=[r for r in sdk if r['method']==method];assert len(rs)==3
        gaps=[round(r['heartbeat_max_gap_s']*1000,2) for r in rs];duration=statistics.median(r['elapsed_s'] for r in rs);lines.append(f'| {method} | 3 | {gaps}ms | {duration:.3f}秒 |')
    lines+=['','専用スレッド化はアプリのイベントループを止めないための改善で、AFMの生成速度は改善していない。ラッパーのキャンセル時も出力を捨てて有限の生成を完了まで待つ設計であり、即時のnative中断を保証しない。SwiftのTask.cancel検証とは区別する。','', '## ツール使用・use caseの設定','','| 設定 | ツール使用 | 全条件適合 |','|---|---:|---:|']
    for mode in ['allowed','required']:
        rs=groups['tool-mode-'+mode];lines.append(f"| {mode} | {sum(bool(r['result'].get('tool_calls')) for r in rs)}/6 | {sum(r['grade']['pass'] for r in rs)}/6 |")
    lines+=['','requiredは最初の1回だけ必須にし、呼び出し後にallowedへ戻す公開DynamicProfileを使った。回数上限6も設定。単一の掛け算／割り算4例では正しく実行したが、複数演算2例では引数や結合を誤った。道具を使うことと正しい操作を選ぶことは別。','','分類6例でuse caseも試した。generalは5/6、content-taggingは4/6適合。用途名を選ぶだけで品質が改善する結果ではなかった。','', '## 中断・回復・安定性','','| 試験 | 結果 |','|---|---|']
    for kind in ['cancel','after-cancel','queue','context-guard','stability']:
        rs=groups[kind];statuses=dict(collections.Counter(r['result'].get('status') for r in rs));lines.append(f'| {kind} | n={len(rs)}、{statuses} |')
    lines+=['','250msの中断指示は最終版の3回すべてで発火し、応答は約254〜270msで終了した。続く要求も3回すべて成功。初回は検証コードのタイマーがreadLine待ちに阻まれたため、その結果は中断性能の評価から除外。修正途中のログも残してある。キューはアプリが1件ずつ処理し、待ち時間を生成時間から分離。上限超過はモデル呼び出し前に拒否。結果キャッシュは入力・設定・モデル・OS buildをキーにし、ヒット時はAFMを呼ばない。','','安定性の5反復はすべて生成完了したが、年なし原文へ2023年を補った同じ誤りを5回繰り返した。JSONのキー順には変化があった。安定した出力でも正しさを保証しない。']
    retries=read('retry.jsonl')
    if retries:
        lines+=['','再試行はアプリ側で最大2回に限定。ユーザーのキャンセルは自動再送しない。以下の通信障害は呼び出し前にコードで挿入したもので、AFMサービスの実際の障害ではない。','','| 再試行試験 | 結果 | 回数 |','|---|---|---:|']
        for row in retries:lines.append(f"| {row['kind']} | {row['result']['status']} | {len(row['result']['attempts'])} |")
        lines+=['','中断後の再送はこの検証が明示した新規要求で、同じプロンプトを新しいセッションへ送った。入力上限エラーは変更しないまま再送せず終了。通信リセットのみ100msの間隔で1回再試行し、持続する障害は2回で打ち切った。']
        summary['retry']=[{'kind':r['kind'],'status':r['result']['status'],'attempts':len(r['result']['attempts'])} for r in retries]
    lines+=['', '## 結果の使い方と限界','','短い日本語の下書き、限定された分類、明瞭な画像からの入力候補、差分の候補抽出を試す価値がある。生成物はスキーマだけでなく出典・値・条件も検査する。年など欠けた属性を推測させる設計、長い状態管理、厳密な計算や最適化は今回の結果から自動実行へ進めない。','', '表・ファイル操作は「AFMが操作仕様を作る→コードが型と許可操作を検査→結果をプレビューする」構成が改善対象。ただし仕様の選択そのものが誤り得るため、コードに任せたことだけで意味の正しさは保証されない。','', '呼び出し制御と詳細計測はSwift直接APIが最も扱いやすい。Pythonはデータ・集計を含む反復検証向きで、他処理と同居するストリームは専用スレッドへ移す。fm serveは既存HTTPクライアントやUnixソケットから同じシステムモデルを使う用途に適する。今回の時間差だけでは経路の普遍的な順位は決められない。','', '品質の合格点を業務別に設定し、OS更新時に同じ固定データを再評価する。一般的なモデル能力の10点評価や、正答率100%の保証には使わない。','', '許諾と互換性は[改善可能範囲](permitted-improvements.md)、実例は[海外15事例](international-cases.md)、自然文等の補足は[内容所見](content-observations.md)。再実行は[README](../README.md)。実出力と失敗例は[測定ログ（パス正規化済み）](../results/)。']
    (ROOT/'reports/results.md').write_text('\n'.join(lines)+'\n')
    (ROOT/'reports/summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    evaluated=screen+tune+held+reg+imgs+files
    with (ROOT/'results/regraded.jsonl').open('w') as f:
        for row in evaluated:f.write(json.dumps({'id':row['case']['id'],'dataset':row['dataset'],'method':row['method'],'grade':row['grade']},ensure_ascii=False)+'\n')
    with (ROOT/'reports/capability.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=['domain','method']+list(stats([]).keys()),lineterminator='\n');w.writeheader()
        for d,s in summary['screen'].items():w.writerow(dict(domain=d,method='baseline',**s))
        for d,methods in summary['heldout'].items():
            for m,s in methods.items():w.writerow(dict(domain=d,method=m,**s))
    print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['select','final']);a=p.parse_args();select() if a.action=='select' else final()
