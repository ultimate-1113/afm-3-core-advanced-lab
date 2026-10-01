"""Scan publishable files without printing potentially sensitive matched values."""
import argparse, json, re, subprocess
from pathlib import Path
from png_audit import audit_file

ROOT=Path(__file__).resolve().parents[1]
SKIP={'.git','.venv','build','bin','__pycache__'}
PATTERNS={
    'personal-home-path':r'/Users/[A-Za-z0-9_.-]+/',
    'mounted-volume-path':r'/Volumes/[A-Za-z0-9_.-]+/',
    'host-temporary-path':r'/(?:private/)?var/folders/[A-Za-z0-9_.-]+/',
    'github-token':r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})',
    'api-token':r'\bsk-[A-Za-z0-9_-]{20,}',
    'private-key':r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    'email-address':r'\b[A-Za-z0-9._%+-]+@(?!users\.noreply\.github\.com)[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b',
    'remote-webhook':r'https://(?:discord(?:app)?\.com/api/webhooks|hooks\.slack\.com/services)/',
}

def files(tracked):
    if tracked:
        names=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
        return [ROOT/name for name in names if name]
    return [p for p in ROOT.rglob('*') if p.is_file() and not set(p.relative_to(ROOT).parts)&SKIP and not str(p.relative_to(ROOT)).startswith('data/file-demo/')]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--tracked',action='store_true');args=parser.parse_args()
    findings=[];scanned=0
    for path in files(args.tracked):
        name=str(path.relative_to(ROOT));scanned+=1
        if path.is_symlink() or not path.is_file():
            findings.append({'file':name,'kind':'unexpected-symlink-or-directory'});continue
        if path.suffix.lower()=='.png':
            image=audit_file(path)
            findings.extend(dict(file=name,**finding) for finding in image['findings'])
            continue
        if path.suffix.lower() in ['.jpg','.jpeg']:
            findings.append({'file':name,'kind':'unsupported-image-metadata-requires-review'});continue
        try:text=path.read_text()
        except UnicodeDecodeError:
            findings.append({'file':name,'kind':'unexpected-binary'});continue
        for label,pattern in PATTERNS.items():
            count=len(re.findall(pattern,text))
            if count:findings.append({'file':name,'kind':label,'count':count})
    print(json.dumps({'scanned_files':scanned,'findings':findings},ensure_ascii=False,indent=2))
    if findings:raise SystemExit(1)

if __name__=='__main__':main()
