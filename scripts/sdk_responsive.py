"""Keep an asyncio app responsive using only the SDK's public API.

SDK 0.2.1's stream iterator synchronously waits on queue.Queue. Run its
session in a dedicated thread/event loop, then forward snapshots safely.
No installed SDK code is changed. Cancellation stops displaying results,
then drains the bounded worker before releasing native resources.
"""
import asyncio, json, threading, time, statistics, sys
from pathlib import Path
import apple_fm_sdk as fm
ROOT=Path(__file__).resolve().parents[1]
PROMPT='ローカルで文章を処理する利点を、日本語300文字程度で説明してください。'

async def consume(prompt,sink):
    model=fm.SystemLanguageModel()
    if not model.is_available()[0] or model.context_size!=8192:raise RuntimeError('SDK model gate failed')
    session=fm.LanguageModelSession(model=model,instructions='与えられた文章生成の指示に従ってください。')
    options=fm.GenerationOptions(sampling=fm.SamplingMode.greedy(),maximum_response_tokens=300)
    async for snapshot in session.stream_response(prompt,options=options):sink(str(snapshot))

async def responsive_stream(prompt):
    loop=asyncio.get_running_loop();channel=asyncio.Queue()
    def push(value):loop.call_soon_threadsafe(channel.put_nowait,value)
    def worker():
        try:asyncio.run(consume(prompt,lambda s:push(('text',s))))
        except Exception as e:push(('error',repr(e)))
        finally:push(('done',None))
    worker_task=asyncio.create_task(asyncio.to_thread(worker))
    try:
        while True:
            kind,value=await channel.get()
            if kind=='done':break
            if kind=='error':raise RuntimeError(value)
            yield value
    finally:
        # Bounded request continues to finish; this does not claim instant native cancellation.
        await asyncio.shield(worker_task)

async def trial(method,i):
    gaps=[];stop=asyncio.Event()
    async def heartbeat():
        last=time.perf_counter()
        while not stop.is_set():
            await asyncio.sleep(.01);current=time.perf_counter();gaps.append(current-last);last=current
    ticker=asyncio.create_task(heartbeat());await asyncio.sleep(.03)
    t=time.perf_counter();snapshots=[];first=None;error=None
    def sink(text):
        nonlocal first
        if first is None and text:first=time.perf_counter()-t
        snapshots.append(text)
    try:
        if method=='direct':await consume(PROMPT,sink)
        else:
            async for text in responsive_stream(PROMPT):sink(text)
    except Exception as e:error=repr(e)
    duration=time.perf_counter()-t;await asyncio.sleep(.03);stop.set();await ticker
    result={'method':method,'repeat':i,'status':'error' if error else 'ok','error':error,'elapsed_s':duration,'ttft_s':first,'text':snapshots[-1] if snapshots else '', 'snapshot_count':len(snapshots),'heartbeat_count':len(gaps),'heartbeat_max_gap_s':max(gaps,default=0),'heartbeat_p95_gap_s':sorted(gaps)[int(.95*(len(gaps)-1))] if gaps else None,'heartbeat_gaps_s':gaps,'maximum_response_tokens':300,'time':time.time()}
    with (ROOT/'results/sdk-responsiveness.jsonl').open('a') as f:f.write(json.dumps(result,ensure_ascii=False)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ['text','heartbeat_gaps_s']},ensure_ascii=False),flush=True)

async def main():
    # SDK 0.2.1 does not expose variant: record an adjacent public Swift gate.
    from lab import Runner, append
    gate=Runner()
    try:append(ROOT/'results/model-checks.jsonl',{'time':time.time(),'purpose':'sdk-responsiveness','ready':gate.ready,'startup_s':gate.startup})
    finally:gate.close()
    # Alternating order; serial requests only.
    for i in range(3):
        for method in (['direct','thread-wrapper'] if i%2==0 else ['thread-wrapper','direct']):await trial(method,i)

if __name__=='__main__':asyncio.run(main())
