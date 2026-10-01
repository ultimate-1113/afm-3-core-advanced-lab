import asyncio, json, time
from pathlib import Path
import apple_fm_sdk as fm
ROOT=Path(__file__).resolve().parents[1]
INSTRUCTION='指示に従い、指定キーのJSONオブジェクトだけ出力してください。不明な情報を創作しないでください。'
async def main():
    model=fm.SystemLanguageModel()
    if not model.is_available()[0] or model.context_size!=8192:raise RuntimeError('SDK availability/context gate failed; Swift gate also required')
    print(json.dumps({'event':'ready','available':True,'context':model.context_size,'variant':'not exposed by SDK 0.2.1; adjacent Swift gate records identity'}),flush=True)
    for line in __import__('sys').stdin:
        r=json.loads(line);t=time.perf_counter();first=None;text=''
        try:
            count_start=time.perf_counter();count=await model.token_count(INSTRUCTION)+await model.token_count(r['prompt']);preflight=time.perf_counter()-count_start
            session_start=time.perf_counter();session=fm.LanguageModelSession(model=model,instructions=INSTRUCTION);session_s=time.perf_counter()-session_start
            generation_start=time.perf_counter()
            async for snapshot in session.stream_response(r['prompt'],options=fm.GenerationOptions(sampling=fm.SamplingMode.greedy(),maximum_response_tokens=256)):
                # SDK text stream yields strings (not token-usage objects).
                text=str(snapshot)
                if first is None and text:first=time.perf_counter()-generation_start
            print(json.dumps({'event':'result','id':r['id'],'route':'python-sdk','text':text,'elapsed_s':time.perf_counter()-t,'generation_s':time.perf_counter()-generation_start,'preflight_s':preflight,'preflight_tokens':count,'session_creation_s':session_s,'ttft_s':first,'status':'ok','input_tokens':None,'output_tokens':None},ensure_ascii=False),flush=True)
        except Exception as e:print(json.dumps({'event':'result','id':r['id'],'route':'python-sdk','error':repr(e),'status':'error'}),flush=True)
asyncio.run(main())
