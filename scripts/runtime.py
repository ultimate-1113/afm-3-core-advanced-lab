"""Controlled runtime experiments using isolated lab-owned processes."""
import argparse, json, time, subprocess, statistics, threading, hashlib, socket, http.client, queue, sys, random
from pathlib import Path
from lab import Runner, append, ROOT, load, request, grade

OUT=ROOT/'results/runtime.jsonl'
def record(kind,req,res,**kw):
    append(OUT,dict(kind=kind,request=req,result=res,time=time.time(),**kw));print(json.dumps({'kind':kind,'id':req.get('id'),'status':res.get('status'),'seconds':round(res.get('host_e2e_s',res.get('elapsed_s',0)),3)},ensure_ascii=False),flush=True)
def system():
    out={}
    for name,cmd in [('pressure',['memory_pressure','-Q']),('vm',['vm_stat']),('swap',['sysctl','vm.swapusage']),('load',['sysctl','vm.loadavg'])]:
        p=subprocess.run(cmd,text=True,capture_output=True,timeout=10);out[name]={'text':p.stdout.strip(),'error':p.stderr.strip(),'returncode':p.returncode}
    return out

def caches(r):
    prefix='固定資料:'+''.join(f'項目{i}: 操作には明示された対象だけを使います。\n' for i in range(35))
    instruction='指示に従い、JSONのanswerへ短く回答。'+prefix
    for repeat in range(3):
        for mode in ['fresh','prewarm','continue','restore']:
            key=f'history-{repeat}'
            if mode in ['continue','restore']:
                if mode=='continue':
                    req={'id':f'cache-seed-{repeat}','prompt':'東京について一文だけ。','instructions':instruction,'session':key,'max_tokens':128}
                    record('cache-seed',req,r.request(req))
                req={'id':f'cache-{mode}-{repeat}','prompt':'日本の首都をanswerに。','max_tokens':128, 'session':key} if mode=='continue' else {'id':f'cache-{mode}-{repeat}','prompt':'日本の首都をanswerに。','max_tokens':128,'restore':key}
            else:
                req={'id':f'cache-{mode}-{repeat}','prompt':'日本の首都をanswerに。','instructions':instruction,'max_tokens':128}
                if mode=='prewarm':req.update(prewarm_ms=1200,prefix='日本の首都を')
            record('cache-'+mode,req,r.request(req))
    # Identical repeated requests: stability across fresh sessions.
    c=load('extraction-heldout')[0]
    for i in range(5):
        req=request(c,'guided');req['id']=f'stability-{i}';res=r.request(req);record('stability',req,res,grade=grade(c,res,'guided'))

def processing(r):
    source='現在の会議: 2026-10-03 15:30 東京駅 田中と佐藤 予約AB-39281。'
    distractors='\n'.join(f'別件{i}: 2025-02-03 09:00 大阪駅。担当鈴木。予約X-{i:03}。現在の会議ではない。' for i in range(80))
    for repeat in range(3):
        for mode in ['full','pruned','split-date','split-people']:
            req={'id':f'processing-{mode}-{repeat}','max_tokens':256,'instructions':'資料に基づき現在の会議だけJSONで回答。別件は除く。'}
            req['prompt']='現在の会議のdate,time,location,participants,reservation_idを抽出。\n'+source+(('\n'+distractors) if mode=='full' else '')
            if mode=='split-date':req['prompt']='現在の会議のdate,time,locationを抽出。'+source
            if mode=='split-people':req['prompt']='現在の会議のparticipants,reservation_idを抽出。'+source
            res=r.request(req);record('processing-'+mode,req,res)
    req={'id':'result-cache-origin','prompt':'予約AB-39281の番号をJSONのreferenceに。','max_tokens':128}
    res=r.request(req); key=hashlib.sha256(json.dumps({'request':{k:v for k,v in req.items() if k!='id'},'model':r.ready['model'],'os':subprocess.check_output(['sw_vers','-buildVersion'],text=True).strip()},sort_keys=True).encode()).hexdigest()
    cache=ROOT/'results'/f'cache-{key}.json';cache.write_text(json.dumps(res,ensure_ascii=False));record('result-cache-miss',req,res,cache_key=key)
    t=time.perf_counter();hit=json.loads(cache.read_text());elapsed=time.perf_counter()-t;record('result-cache-hit',req,{'status':'ok','elapsed_s':elapsed,'text':hit['text'],'afm_invoked':False},cache_key=key)
    req={'id':'context-overflow-guard','prompt':'資料: '+('これは検証用の長文です。'*1400),'max_tokens':512}
    record('context-guard',req,r.request(req))

class Probe:
    """Foreground proxy: periodic small CPU task and scheduling-delay samples."""
    def __init__(self):self.values=[];self.stop=threading.Event();self.thread=threading.Thread(target=self.loop,daemon=True)
    def loop(self):
        while not self.stop.is_set():
            t=time.perf_counter();data=b'foreground probe'*100
            for _ in range(120):data=hashlib.sha256(data).digest()
            work=time.perf_counter()-t
            deadline=time.perf_counter()+.02;self.stop.wait(.02)
            self.values.append({'work_s':work,'late_s':max(0,time.perf_counter()-deadline)})
    def start(self):self.thread.start()
    def finish(self):
        self.stop.set();self.thread.join();values=self.values
        def pct(a,q):return sorted(a)[min(len(a)-1,int(len(a)*q))] if a else None
        return {'count':len(values),'work_median_s':statistics.median([v['work_s'] for v in values]) if values else None,'work_p95_s':pct([v['work_s'] for v in values],.95),'scheduling_p95_s':pct([v['late_s'] for v in values],.95),'scheduling_max_s':max([v['late_s'] for v in values],default=None),'samples':values}

class Monitor:
    def __init__(self,pid):self.pid=pid;self.samples=[];self.stop=threading.Event();self.thread=threading.Thread(target=self.loop,daemon=True)
    def loop(self):
        while not self.stop.is_set():
            raw=subprocess.check_output(['ps','-axo','pid,ucomm,%cpu,rss'],text=True)
            lines=[l for l in raw.splitlines() if 'TGOnDevice' in l or 'TokenGeneration' in l or 'afm-runner' in l]
            self.samples.append({'time':time.time(),'processes':lines,'swap':subprocess.check_output(['sysctl','vm.swapusage'],text=True).strip(),'vm':subprocess.check_output(['vm_stat'],text=True)})
            self.stop.wait(.3)
    def start(self):self.thread.start()
    def finish(self):self.stop.set();self.thread.join();return self.samples

def loads(r):
    before=system();probe=Probe();probe.start();time.sleep(3);record('load-idle',{'id':'idle'}, {'status':'ok','elapsed_s':3},probe=probe.finish(),system_before=before,system_after=system())
    configs=[(p,n,gap) for p in ['normal','background'] for n in [1,2] for gap in [0,300]]
    random.Random(61).shuffle(configs)
    for priority,n,gap in configs:
        before=system();probe=Probe();probe.start();monitor=Monitor(r.p.pid);monitor.start();start=time.perf_counter();responses=[]
        for repeat in range(3):
            reqs=[{'id':f'load-{priority}-{n}-{gap}-{repeat}-{i}','prompt':'ローカルで文章を処理する利点を日本語300文字程度で説明。JSONのtextへ。','max_tokens':300,'priority':priority} for i in range(n)]
            t=time.perf_counter()
            for req in reqs:r.send(req)
            results,events=r.receive([x['id'] for x in reqs],90)
            for req in reqs:
                res=dict(results[req['id']]);res['batch_e2e_s']=time.perf_counter()-t;responses.append({'request':req,'result':res})
            if gap:time.sleep(gap/1000)
        duration=time.perf_counter()-start;record('load',{'id':f'{priority}-{n}-{gap}','priority':priority,'concurrency':n,'gap_ms':gap},{'status':'ok','elapsed_s':duration},responses=responses,probe=probe.finish(),process_samples=monitor.finish(),system_before=before,system_after=system())

def recovery(r):
    for repeat in range(3):
        req={'id':f'cancel-{repeat}','prompt':'日本語で長い架空の旅行記を1000文字以上書いてください。','max_tokens':1400,'cancel_after_ms':250}
        record('cancel',req,r.request(req,timeout=20))
        req={'id':f'after-cancel-{repeat}','prompt':'日本の首都を都市名だけ。','max_tokens':32}
        record('after-cancel',req,r.request(req))
    # App-owned queue, one request at a time; waiting time is recorded independently.
    submitted=time.perf_counter()
    for i in range(5):
        req={'id':f'queue-{i}','prompt':f'{i+3}と{7+i}の和だけを答えてください。','max_tokens':32}
        wait=time.perf_counter()-submitted;res=r.request(req);record('queue',req,res,queue_wait_s=wait,expected=str(10+2*i))

def tool_modes(r):
    for c in [c for c in load('wide') if c['domain']=='tools']:
        for mode in ['allowed','required']:
            req=request(c,'guided');req['id']=c['id']+'-mode-'+mode;req['tool_mode']=mode
            res=r.request(req,timeout=30);record('tool-mode-'+mode,req,res,case=c,grade=grade(c,res,'guided'))
    # Token-conversion/initialization overhead is recorded around public calls only.
    for i,c in enumerate([c for c in load('wide') if c['domain']=='classification']):
        for use_case in ['general','content-tagging']:
            req=request(c,'guided');req.update(id=f'usecase-{i}-{use_case}',use_case=use_case);res=r.request(req);record('usecase-'+use_case,req,res,case=c,grade=grade(c,res,'guided'))

def resources(r):
    for priority in ['normal','background']:
        for n in [1,2]:
            monitor=Monitor(r.p.pid);monitor.start();start=time.perf_counter();before=system()
            reqs=[{'id':f'resource-{priority}-{n}-{i}','prompt':'ローカルで文章を処理する利点を日本語300文字程度で説明。JSONのtextへ。','priority':priority,'max_tokens':300} for i in range(n)]
            for req in reqs:r.send(req)
            result,events=r.receive([req['id'] for req in reqs],60)
            samples=monitor.finish();record('resource-profile',{'id':f'{priority}-{n}','priority':priority,'concurrency':n},{'status':'ok','elapsed_s':time.perf_counter()-start},responses=result,process_samples=samples,system_before=before,system_after=system())

class UnixHTTP(http.client.HTTPConnection):
    def __init__(self,path):super().__init__('localhost',timeout=30);self.path=path
    def connect(self):self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.sock.settimeout(self.timeout);self.sock.connect(self.path)

def routes(r):
    record('swift-start',{'id':'swift-ready'},{'status':'ok','elapsed_s':r.startup},metadata=r.ready)
    sdk_start=time.perf_counter()
    sdk=subprocess.Popen([str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/sdk_route.py')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=open(ROOT/'results/sdk.stderr.log','a'),text=True,bufsize=1)
    sdk_ready=json.loads(sdk.stdout.readline());record('sdk-start',{'id':'sdk-ready'},{'status':'ok','elapsed_s':time.perf_counter()-sdk_start},metadata=sdk_ready)
    for transport in ['tcp','unix']:
        port=19876;path=str(ROOT/'results/fm-lab.sock')
        if transport=='tcp':
            check=socket.socket();check.bind(('127.0.0.1',port));check.close();cmd=['fm','serve','--host','127.0.0.1','--port',str(port)]
        else:cmd=['fm','serve','--socket',path]
        server=subprocess.Popen(cmd,stdout=open(ROOT/f'results/fm-{transport}.stdout.log','a'),stderr=open(ROOT/f'results/fm-{transport}.stderr.log','a'));start=time.perf_counter()
        def conn():return http.client.HTTPConnection('127.0.0.1',port,timeout=30) if transport=='tcp' else UnixHTTP(path)
        try:
            for _ in range(100):
                try:
                    client=conn();client.request('GET','/health');health=client.getresponse();body=health.read().decode();client.close()
                    if health.status==200:break
                except (OSError,http.client.HTTPException):time.sleep(.05)
            else:raise RuntimeError('isolated fm serve not ready')
            record('serve-start',{'id':transport},{'status':'ok','elapsed_s':time.perf_counter()-start},health=body)
            for repeat in range(5):
                prompt='予約番号AB-39281。予約番号だけJSONのreservation_idへ。'
                instr='指示に従い、指定キーのJSONオブジェクトだけ出力してください。不明な情報を創作しないでください。'
                req={'id':f'route-{transport}-{repeat}','prompt':prompt,'instructions':instr,'max_tokens':256}
                if transport=='tcp':
                    record('route-swift',req,r.request(req))
                    t=time.perf_counter();sdk.stdin.write(json.dumps(req,ensure_ascii=False)+'\n');sdk.stdin.flush();res=json.loads(sdk.stdout.readline());res['host_e2e_s']=time.perf_counter()-t;record('route-sdk',req,res)
                    t=time.perf_counter();cli=subprocess.run(['fm','respond','--text',prompt,'--instructions',instr,'--greedy','--no-stream'],text=True,capture_output=True,timeout=40);record('route-fm',req,{'status':'ok' if cli.returncode==0 else 'error','elapsed_s':time.perf_counter()-t,'text':cli.stdout,'stderr':cli.stderr,'ttft_s':None,'token_cap':'CLI has no maximum-response-token flag'})
                body=json.dumps({'model':'system','messages':[{'role':'system','content':instr},{'role':'user','content':prompt}],'stream':True,'temperature':0,'max_tokens':256},ensure_ascii=False)
                t=time.perf_counter();client=conn();client.request('POST','/v1/chat/completions',body=body.encode(),headers={'Content-Type':'application/json'});response=client.getresponse();first=None;text='';chunks=[];usage=None
                while True:
                    line=response.readline()
                    if not line:break
                    raw=line.decode().strip()
                    if not raw.startswith('data:'):continue
                    data=raw[5:].strip()
                    if data=='[DONE]':break
                    try:
                        obj=json.loads(data);chunks.append(obj);piece=obj.get('choices',[{}])[0].get('delta',{}).get('content','')
                        if piece and first is None:first=time.perf_counter()-t
                        text+=piece
                        if obj.get('usage'):usage=obj['usage']
                    except (ValueError,IndexError):pass
                client.close();record('route-serve-'+transport,req,{'status':'ok' if response.status==200 else 'error','http_status':response.status,'elapsed_s':time.perf_counter()-t,'ttft_s':first,'text':text,'usage':usage,'chunks':chunks,'sampling_equivalence':'temperature=0; fm server greedy equivalence not exposed'})
        finally:
            server.terminate()
            try:server.wait(timeout=5)
            except subprocess.TimeoutExpired:server.kill();server.wait()
    sdk.stdin.close()
    try:sdk.wait(timeout=5)
    except subprocess.TimeoutExpired:sdk.terminate();sdk.wait(timeout=5)

def main():
    global OUT
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['cache','processing','load','recovery','routes','tools','resources','all']);p.add_argument('--output',default='runtime.jsonl');a=p.parse_args()
    if Path(a.output).name!=a.output:raise ValueError('output must be a basename within results')
    OUT=ROOT/'results'/a.output;r=Runner()
    append(ROOT/'results/model-checks.jsonl',{'time':time.time(),'ready':r.ready,'phase':'runtime-'+a.phase})
    try:
        for name,fn in [('cache',caches),('processing',processing),('load',loads),('recovery',recovery),('routes',routes),('tools',tool_modes),('resources',resources)]:
            if a.phase in [name,'all']:fn(r)
    finally:r.close()
if __name__=='__main__':main()
