"""Record publication hashes; omit host paths, build outputs and this manifest."""
import hashlib, importlib.metadata, json
from datetime import datetime, timezone
from lab import ROOT

paths=[ROOT/'README.md',ROOT/'LICENSE',ROOT/'THIRD_PARTY_NOTICES.md',ROOT/'.gitignore',ROOT/'src/Runner.swift']
for folder,pattern in [('scripts','*.py'),('scripts','*.sh'),('data','*.json*'),('data/images','*.png'),('results','*.json*'),('results','*.log'),('results','*.md'),('reports','*'),('licenses','*')]:
    paths.extend(p for p in (ROOT/folder).glob(pattern) if p.is_file())
out=ROOT/'results/final-artifact-manifest.json'
paths=sorted(set(paths)-{out})
try:sdk=importlib.metadata.version('apple-fm-sdk')
except importlib.metadata.PackageNotFoundError:sdk=None
manifest={
    'captured_utc':datetime.now(timezone.utc).isoformat(),
    'root':'.',
    'installed_sdk_version':sdk,
    'required_sdk_version':'0.2.1',
    'runner_version':3,
    'notes':[
        'Published logs normalize repository paths to <LAB_ROOT>. Numeric measurements, prompts, and outputs are unchanged.',
        'environment.json and measurement-artifact-manifest.json describe original measurement snapshots, not current publication source hashes.',
        'Build binaries, environments, Git metadata, and this manifest are not included in the file hashes.',
        'Earlier quality runners used the same ordinary prompts and sampling; version 3 adds cancellation timing/status, history guards and required-tool control.',
        'retry-initial.jsonl labelled runner dispatch as model_invoked; final retry.jsonl uses runner_request_sent.',
    ],
    'files':{str(p.relative_to(ROOT)):{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths},
}
out.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
print(f'Publication manifest: {len(paths)} artifacts')
