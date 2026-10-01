"""Privacy regression tests: compressed metadata, EXIF, padding and malformed data."""
import json
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from png_audit import audit_bytes,MAX_METADATA
LOCAL='/'.join(('', 'Users', 'example', 'file'))

def chunk(kind,data):
    return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)

def png(*metadata):
    header=struct.pack('>IIBBBBB',1,1,8,6,0,0,0)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',header)+b''.join(metadata)+chunk(b'IDAT',zlib.compress(b'\0\0\0\0\xff'))+chunk(b'IEND',b'')

def dimensions(order='<'):
    head=(b'II' if order=='<' else b'MM')+struct.pack(order+'HI',42,8)
    root=struct.pack(order+'H',1)+struct.pack(order+'HHII',0x8769,4,1,26)+struct.pack(order+'I',0)
    sub=struct.pack(order+'H',2)+b''.join(struct.pack(order+'HHII',tag,4,1,1) for tag in [0xa002,0xa003])+struct.pack(order+'I',0)
    return head+root+sub

class MetadataTests(unittest.TestCase):
    def kinds(self,result):return {r['kind'] for r in result['findings']}

    def test_plain_png_and_dimension_only_exif(self):
        for data in [png(),png(chunk(b'eXIf',dimensions())),png(chunk(b'eXIf',dimensions('>')))]:
            self.assertTrue(audit_bytes(data)['passed'])

    def test_all_text_formats_and_fields(self):
        local=LOCAL.encode()
        entries=[chunk(b'tEXt',b'Software\0'+local),chunk(b'zTXt',b'Comment\0\0'+zlib.compress(local)),
                 chunk(b'iTXt',b'Comment\0\0\0\0\0'+local),chunk(b'iTXt',b'Comment\0\1\0\0\0'+zlib.compress(local)),
                 chunk(b'iTXt',b'Comment\0\0\0\0'+local+b'\0harmless')]
        for entry in entries:
            result=audit_bytes(png(entry));self.assertFalse(result['passed']);self.assertIn('local-path',self.kinds(result))
            self.assertNotIn(LOCAL,json.dumps(result))

    def test_harmless_text_still_requires_review(self):
        self.assertIn('text-metadata-requires-review',self.kinds(audit_bytes(png(chunk(b'tEXt',b'Title\0hello')))))

    def test_unknown_icc_timestamp_chunks_require_review(self):
        for kind,payload in [(b'vpAg',b'opaque'),(b'iCCP',b'profile\0\0'+zlib.compress(b'unknown')),(b'tIME',b'\0'*7)]:
            self.assertIn('chunk-requires-review',self.kinds(audit_bytes(png(chunk(kind,payload)))))

    def test_utf16_and_percent_encoded_paths(self):
        for value in [LOCAL.encode('utf-16-le'),b'%2FUsers%2Fexample%2Ffile',b'C:\\Users\\example\\file']:
            self.assertIn('local-path',self.kinds(audit_bytes(png(chunk(b'tEXt',b'Comment\0'+value)))))

    def test_software_and_gps_exif_tags_require_review(self):
        for tag in [0x0131,0x8825]:
            data=b'II'+struct.pack('<HI',42,8)+struct.pack('<H',1)+struct.pack('<HHII',tag,4,1,0)+struct.pack('<I',0)
            self.assertIn('exif-tag-requires-review',self.kinds(audit_bytes(png(chunk(b'eXIf',data)))))

    def test_unreferenced_exif_data(self):
        self.assertIn('unparsed-exif-data',self.kinds(audit_bytes(png(chunk(b'eXIf',dimensions()+b'hidden note')))))

    def test_exif_dimension_mismatch(self):
        data=bytearray(dimensions());struct.pack_into('<I',data,36,2)
        self.assertIn('exif-dimension-mismatch',self.kinds(audit_bytes(png(chunk(b'eXIf',bytes(data))))))

    def test_malformed_crc_truncation_offset_cycle_and_tail(self):
        corrupt=bytearray(png());corrupt[29]^=1
        cycle=bytearray(dimensions());struct.pack_into('<I',cycle,18,8)
        bad_offset=bytearray(dimensions());struct.pack_into('<I',bad_offset,18,99999)
        for data in [bytes(corrupt),png()[:-2],png()+b'private tail',png(chunk(b'eXIf',bytes(cycle))),png(chunk(b'eXIf',bytes(bad_offset)))]:
            self.assertIn('invalid-png-or-metadata',self.kinds(audit_bytes(data)))

    def test_compression_limit(self):
        payload=b'Comment\0\0'+zlib.compress(b'x'*(MAX_METADATA+1))
        self.assertIn('invalid-png-or-metadata',self.kinds(audit_bytes(png(chunk(b'zTXt',payload)))))

    def test_cli_failure_has_no_metadata_value(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'sample.png';path.write_bytes(png(chunk(b'zTXt',b'Comment\0\0'+zlib.compress(LOCAL.encode()))))
            result=subprocess.run([sys.executable,str(Path(__file__).with_name('png_audit.py')),str(path)],capture_output=True,text=True)
            self.assertEqual(result.returncode,1);self.assertNotIn(LOCAL,result.stdout)

    def test_repository_fixtures(self):
        paths=list((Path(__file__).resolve().parents[1]/'data/images').glob('*.png'))
        self.assertEqual(len(paths),6)
        for path in paths:self.assertTrue(audit_bytes(path.read_bytes())['passed'])

if __name__=='__main__':unittest.main()
