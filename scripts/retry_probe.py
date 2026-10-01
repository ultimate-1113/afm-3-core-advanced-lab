"""Bounded app-level retries; injected transport faults are explicitly labelled.

Only ConnectionResetError is retried here. Model errors, context violations,
and user cancellation are returned without automatic retries.
"""
import json, time
from lab import ROOT, Runner, append

def bounded_request(runner, request, inject_resets=0, max_attempts=2):
    attempts=[]
    for i in range(max_attempts):
        start=time.perf_counter()
        try:
            if i<inject_resets:raise ConnectionResetError('lab-injected transport reset BEFORE model invocation')
            result=runner.request(dict(request,id=request['id']+f'-attempt-{i+1}'))
            attempts.append({'attempt':i+1,'result':result,'runner_request_sent':True,'elapsed_s':time.perf_counter()-start})
            return {'status':result['status'],'attempts':attempts}
        except ConnectionResetError as e:
            attempts.append({'attempt':i+1,'status':'transport-error','error':str(e),'runner_request_sent':False,'elapsed_s':time.perf_counter()-start})
            if i+1<max_attempts:time.sleep(.1)
    return {'status':'retry-exhausted','attempts':attempts}

def main():
    runner=Runner()
    append(ROOT/'results/model-checks.jsonl',{'time':time.time(),'purpose':'retry','ready':runner.ready,'startup_s':runner.startup})
    out=ROOT/'results/retry.jsonl'
    def record(kind,request,result,**extra):
        row={'kind':kind,'request':request,'result':result,'time':time.time(),**extra}
        append(out,row)
        print(json.dumps({'kind':kind,'status':result['status'],'attempts':len(result.get('attempts',[]))},ensure_ascii=False),flush=True)
    try:
        req={'id':'retry-after-test-cancel','prompt':'ローカルで文章を処理する利点を、日本語300文字程度で説明してください。','max_tokens':300,'sampling':'greedy'}
        cancelled=runner.request(dict(req,id=req['id']+'-cancelled',cancel_after_ms=250))
        # Explicit new request for this test; this is never an automatic user-cancel retry.
        result=bounded_request(runner,req)
        record('explicit-retry-after-test-cancel',req,result,cancelled=cancelled)
        short={'id':'injected-transport-retry','prompt':'日本の首都を都市名だけで答えてください。','max_tokens':32,'sampling':'greedy'}
        record('injected-transport-retry',short,bounded_request(runner,short,inject_resets=1),fault_injected=True)
        excessive={'id':'context-error-no-retry','prompt':'abc '*10000,'max_tokens':32,'sampling':'greedy'}
        record('context-error-no-retry',excessive,bounded_request(runner,excessive))
        record('injected-transport-exhaustion',short,bounded_request(runner,short,inject_resets=2),fault_injected=True)
    finally:runner.close()

if __name__=='__main__':main()
