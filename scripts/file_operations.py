"""Six lab-owned file-operation previews; no generated code or user file writes."""
import json, shutil, time
from pathlib import Path
from lab import ROOT, Runner, request, grade, append, parse
from cases import case, field

def main():
    folder=ROOT/'data/file-demo'/f'run-{time.time_ns()}';folder.mkdir(parents=True)
    # Only this script's synthetic fixtures are present in the operation allowlist.
    names=['meeting.md','draft.txt','receipt.png','old-note.md','copy-note.md','missing-year.txt']
    for name in names:
        (folder/name).write_text('同じメモ' if name in ['old-note.md','copy-note.md'] else '合成テスト資料 '+name)
    schema={'fields':[field('operation',choices=['copy','rename','select','flag','none']),field('sources','strings'),field('target',optional=True)]}
    jobs=[('meeting.mdをarchiveにコピー。他は対象外。',dict(operation='copy',sources=['meeting.md'],target='archive')),
          ('draft.txtをproposal.txtへ改名。',dict(operation='rename',sources=['draft.txt'],target='proposal.txt')),
          ('画像ファイルだけを選ぶ。',dict(operation='select',sources=['receipt.png'],target=None)),
          ('old-note.mdとcopy-note.mdは同一内容だが削除指示はない。操作はnone、sourcesは空、targetはnull。',dict(operation='none',sources=[],target=None)),
          ('missing-year.txtに「10月3日会議」とある。年が足りない資料としてflag。targetはnull。',dict(operation='flag',sources=['missing-year.txt'],target=None)),
          ('拡張子mdの全ファイルを一覧順で選ぶ。',dict(operation='select',sources=['meeting.md','old-note.md','copy-note.md'],target=None))]
    runner=Runner()
    try:
        for i,(task,expected) in enumerate(jobs):
            c=case('files',i+1,'一覧:'+json.dumps(names)+'。'+task+' JSONのoperation,sources,targetへ。',expected,fields=schema['fields'])
            req=request(c,'guided');res=runner.request(req);g=grade(c,res,'guided');spec=parse(res.get('text',''));action={'executed':False,'preview':spec}
            # Demo executor also requires the independent known intent to match.
            # Real applications show this preview for user confirmation.
            if g['pass'] and isinstance(spec,dict) and set(spec['sources'])<=set(names):
                target=spec.get('target');safe=target is None or (Path(target).name==target and target not in ['.','..'] and '/' not in target)
                if safe and spec['operation']=='copy':
                    destination=folder/target;destination.mkdir(exist_ok=True)
                    for name in spec['sources']:shutil.copy2(folder/name,destination/name)
                    action['executed']=True;action['verification']=all((destination/name).read_bytes()==(folder/name).read_bytes() for name in spec['sources'])
                elif safe and spec['operation']=='rename' and len(spec['sources'])==1:
                    destination=folder/target
                    if not destination.exists():(folder/spec['sources'][0]).rename(destination);action['executed']=True;action['verification']=destination.exists()
                else:action['verification']='preview only'
            append(ROOT/'results/files.jsonl',{'dataset':'file-demo','case':c,'method':'guided','request':req,'result':res,'grade':g,'action':action})
            print(json.dumps({'id':c['id'],'pass':g['pass'],'executed':action['executed']},ensure_ascii=False),flush=True)
    finally:runner.close()

if __name__=='__main__':main()
