"""Read-only, conservative PNG metadata gate. Never print metadata values.

Text, ICC, timestamps, unknown chunks and EXIF other than dimension tags
require review. This checks metadata and structure, not pixel steganography.
PNG structure reference: https://www.w3.org/TR/png-3/
"""
import argparse
import hashlib
import json
import re
import struct
import zlib
from pathlib import Path
from urllib.parse import unquote

MAX_FILE = 64 * 1024 * 1024
MAX_METADATA = 8 * 1024 * 1024
MAX_CHUNKS = 4096
BASE_CHUNKS = {b'IHDR', b'PLTE', b'IDAT', b'IEND', b'sRGB', b'gAMA', b'cHRM', b'tRNS', b'pHYs'}
TEXT_CHUNKS = {b'tEXt', b'iTXt', b'zTXt'}
FIXED_LENGTHS = {b'IHDR': 13, b'IEND': 0, b'sRGB': 1, b'gAMA': 4, b'cHRM': 32, b'pHYs': 9}
SENSITIVE = {
    'local-path': r'(?:/(?:Users|Volumes|home)/|/(?:private/)?(?:tmp|var/folders)/|[A-Za-z]:[\\/]Users[\\/])',
    'email': r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',
    'token': r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,})',
    'private-key': r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
}

class InvalidPNG(ValueError):
    pass

def sensitive_kinds(payload):
    texts=[]
    for encoding in ('utf-8', 'latin1', 'utf-16-le', 'utf-16-be'):
        text=payload.decode(encoding, errors='ignore').replace('\0', '')
        texts.extend((text, unquote(text)))
    return sorted(label for label,pattern in SENSITIVE.items() if any(re.search(pattern,text,re.I) for text in texts))

def inflate(payload):
    decoder=zlib.decompressobj()
    text=decoder.decompress(payload,MAX_METADATA+1)
    if len(text)>MAX_METADATA or not decoder.eof or decoder.unused_data:
        raise InvalidPNG('compressed metadata invalid or over limit')
    return text

def text_payload(kind,payload):
    keyword,rest=payload.split(b'\0',1)
    if not 1<=len(keyword)<=79:
        raise InvalidPNG('invalid text keyword')
    if kind==b'tEXt':return payload
    if kind==b'zTXt':
        if not rest or rest[0]!=0:raise InvalidPNG('invalid zTXt compression method')
        return keyword+b'\0'+inflate(rest[1:])
    if len(rest)<2 or rest[0] not in (0,1) or rest[1]!=0:
        raise InvalidPNG('invalid iTXt compression header')
    language,translated,text=rest[2:].split(b'\0',2)
    text=inflate(text) if rest[0] else text
    # Language, translated keyword and keyword can also carry identifying text.
    return b'\0'.join((keyword,language,translated,text))

def exif_dimensions(data,width,height):
    """Whitelist only the observed ExifIFD pointer and numeric pixel dimensions.

    All directory bytes must be covered; nonzero padding or unreferenced data
    requires review even if the recognized tags themselves are harmless.
    """
    if len(data)<8 or data[:2] not in (b'II',b'MM'):
        raise InvalidPNG('invalid EXIF header')
    order='<' if data[:2]==b'II' else '>'
    covered=bytearray(len(data));visited=set();tags=[];findings=[]
    def mark(at,size):
        if at<0 or at+size>len(data):raise InvalidPNG('EXIF offset out of range')
        if any(covered[at:at+size]):raise InvalidPNG('overlapping EXIF data')
        covered[at:at+size]=b'\1'*size
    def u16(at):return struct.unpack_from(order+'H',data,at)[0]
    def u32(at):return struct.unpack_from(order+'I',data,at)[0]
    mark(0,8)
    if u16(2)!=42:raise InvalidPNG('invalid EXIF marker')
    def directory(at,depth=0):
        if not at:return
        if depth>8 or at in visited:raise InvalidPNG('cyclic or deep EXIF directory')
        visited.add(at)
        if at+2>len(data):raise InvalidPNG('EXIF directory out of range')
        entry_count=u16(at)
        if entry_count>256:raise InvalidPNG('too many EXIF entries')
        mark(at,2+12*entry_count+4)
        for i in range(entry_count):
            n=at+2+12*i;tag=u16(n);typ=u16(n+2);count=u32(n+4)
            if tag not in (0x8769,0xa002,0xa003):
                findings.append({'kind':'exif-tag-requires-review','tag':f'0x{tag:04x}'})
                continue
            if count!=1 or typ not in ((4,) if tag==0x8769 else (3,4)):
                raise InvalidPNG('unexpected EXIF dimension or pointer type')
            value=u16(n+8) if typ==3 else u32(n+8)
            if typ==3 and any(data[n+10:n+12]):
                findings.append({'kind':'nonzero-exif-padding','tag':f'0x{tag:04x}'})
            if tag==0x8769:
                if not value:raise InvalidPNG('empty EXIF subdirectory pointer')
                directory(value,depth+1)
            else:
                if value!=(width if tag==0xa002 else height):
                    findings.append({'kind':'exif-dimension-mismatch','tag':f'0x{tag:04x}'})
                tags.append({'tag':f'0x{tag:04x}','value':value})
        directory(u32(at+2+12*entry_count),depth+1)
    directory(u32(4))
    if any(value and not covered[i] for i,value in enumerate(data)):
        findings.append({'kind':'unparsed-exif-data'})
    return tags,findings

def audit_bytes(raw):
    result={'sha256':hashlib.sha256(raw).hexdigest(),'chunks':[],'exif_dimensions':[],'findings':[]}
    try:
        if len(raw)>MAX_FILE or raw[:8]!=b'\x89PNG\r\n\x1a\n':
            raise InvalidPNG('invalid signature or file over limit')
        offset=8;width=height=None;seen_idat=False;ended_idat=False;seen_exif=False;ended=False
        while offset<len(raw):
            if len(result['chunks'])>=MAX_CHUNKS or offset+12>len(raw):
                raise InvalidPNG('truncated PNG or too many chunks')
            size=struct.unpack_from('>I',raw,offset)[0];kind=raw[offset+4:offset+8];end=offset+12+size
            if end>len(raw) or not re.fullmatch(b'[A-Za-z]{4}',kind):
                raise InvalidPNG('invalid chunk header')
            payload=raw[offset+8:offset+8+size];crc=struct.unpack_from('>I',raw,offset+8+size)[0]
            if (zlib.crc32(kind+payload)&0xffffffff)!=crc:raise InvalidPNG('CRC mismatch')
            if kind in FIXED_LENGTHS and size!=FIXED_LENGTHS[kind]:raise InvalidPNG('invalid fixed-size chunk')
            if kind!=b'IDAT' and size>MAX_METADATA:raise InvalidPNG('metadata over limit')
            if width is None and kind!=b'IHDR':raise InvalidPNG('IHDR must be first')
            if kind==b'IHDR':
                if width is not None:raise InvalidPNG('duplicate IHDR')
                width,height=struct.unpack_from('>II',payload)
                if not (0<width<2**31 and 0<height<2**31):raise InvalidPNG('invalid image dimensions')
                result['dimensions']=[width,height]
            if kind==b'IDAT':
                if ended_idat:raise InvalidPNG('nonconsecutive IDAT')
                seen_idat=True
            elif seen_idat:ended_idat=True
            name=kind.decode('ascii');result['chunks'].append({'type':name,'length':size})
            if kind!=b'IDAT':
                if kind in TEXT_CHUNKS:
                    result['findings'].append({'kind':'text-metadata-requires-review','chunk':name})
                    decoded=text_payload(kind,payload)
                else:decoded=payload
                for label in sensitive_kinds(decoded):result['findings'].append({'kind':label,'chunk':name})
            if kind==b'eXIf':
                if seen_exif:raise InvalidPNG('duplicate EXIF')
                seen_exif=True;tags,findings=exif_dimensions(payload,width,height)
                result['exif_dimensions'].extend(tags);result['findings'].extend(findings)
            elif kind not in BASE_CHUNKS and kind not in TEXT_CHUNKS:
                # Includes ICC profiles, timestamps and private application chunks.
                result['findings'].append({'kind':'chunk-requires-review','chunk':name})
            offset=end
            if kind==b'IEND':
                if not seen_idat:raise InvalidPNG('missing image data')
                ended=True
                if offset!=len(raw):raise InvalidPNG('trailing data after IEND')
                break
        if not ended:raise InvalidPNG('missing IEND')
    except (InvalidPNG,ValueError,struct.error,zlib.error,IndexError):
        result['findings'].append({'kind':'invalid-png-or-metadata'})
    result['passed']=not result['findings']
    return result

def audit_file(path):
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size>MAX_FILE:
            return {'passed':False,'findings':[{'kind':'invalid-file-or-over-limit'}]}
        with path.open('rb') as stream:raw=stream.read(MAX_FILE+1)
        return audit_bytes(raw)
    except OSError:
        return {'passed':False,'findings':[{'kind':'invalid-file-or-over-limit'}]}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('path',nargs='?',default='data/images');args=parser.parse_args()
    path=Path(args.path);paths=sorted(p for p in path.rglob('*') if p.suffix.lower()=='.png') if path.is_dir() else [path]
    rows=[dict(file=str(p.relative_to(path)) if path.is_dir() else p.name,**audit_file(p)) for p in paths]
    print(json.dumps({'png_count':len(rows),'images':rows,'passed':bool(rows) and all(r['passed'] for r in rows)},indent=2))
    if not rows or any(not r['passed'] for r in rows):raise SystemExit(1)

if __name__=='__main__':main()
