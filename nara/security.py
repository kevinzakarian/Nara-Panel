"""Small, dependency-free account security primitives (RFC 6238 / RFC 4226)."""
import base64
import binascii
import hashlib
import hmac
import re
import secrets
import struct
import time
import zlib
from urllib.parse import quote, urlencode

AVATARS = ('ember', 'ocean', 'forest', 'violet', 'sunrise', 'slate', 'rose', 'mint')


def totp_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip('=')


def totp(secret, counter, digits=6, algorithm='sha1'):
    key=base64.b32decode(secret + '='*((-len(secret))%8), casefold=True)
    digest=hmac.new(key, struct.pack('!Q',counter), algorithm).digest()
    offset=digest[-1]&15
    return str((struct.unpack('!I',digest[offset:offset+4])[0]&0x7fffffff) % 10**digits).zfill(digits)


def totp_counter(secret, code, last=-1, now=None):
    code=str(code).strip()
    if not re.fullmatch(r'[0-9]{6}',code): return None
    counter=int((time.time() if now is None else now)//30)
    for candidate in (counter,counter-1,counter+1):
        if candidate>=0 and candidate>last and hmac.compare_digest(totp(secret,candidate),code):
            return candidate
    return None


def otp_uri(secret, username):
    return 'otpauth://totp/'+quote('NARA:'+username,safe='')+'?'+urlencode(
        {'secret':secret,'issuer':'NARA','algorithm':'SHA1','digits':6,'period':30})


def recovery_hash(code):
    value=re.sub(r'[\s-]','',str(code)).upper()
    return hashlib.sha256(value.encode()).hexdigest()


def recovery_codes():
    codes=[secrets.token_hex(10).upper() for _ in range(10)]
    codes=[code[:10]+'-'+code[10:] for code in codes]
    return codes,[recovery_hash(code) for code in codes]


def verify_factor(admin, code, now=None):
    """Mutate only on success; caller persists under its account security lock."""
    if not admin.get('totp_secret'): return True
    counter=totp_counter(admin['totp_secret'],code,admin.get('totp_last',-1),now)
    if counter is not None:
        admin['totp_last']=counter
        return True
    hashed=recovery_hash(code)
    for index,value in enumerate(admin.get('recovery_hashes',[])):
        if hmac.compare_digest(value,hashed):
            admin['recovery_hashes'].pop(index)
            return True
    return False


def public_admin(admin):
    return {'username':admin['username'],'avatar':admin.get('avatar','ember'),
            'two_factor':bool(admin.get('totp_secret')),'recovery_remaining':len(admin.get('recovery_hashes',[]))}


def validate_avatar(value):
    if value in AVATARS: return value
    if not isinstance(value,str) or not value.startswith('data:image/png;base64,') or len(value)>350000:
        raise ValueError('Choose a suggested avatar or upload a PNG image up to 256 KiB')
    try:
        raw=base64.b64decode(value.split(',',1)[1],validate=True)
        if len(raw)>262144 or not raw.startswith(b'\x89PNG\r\n\x1a\n'): raise ValueError()
        offset=8; parts=[]; width=height=0; data=[]; ended=False
        while offset<len(raw):
            length=struct.unpack('!I',raw[offset:offset+4])[0]
            kind=raw[offset+4:offset+8]; chunk=raw[offset+8:offset+8+length]
            if len(kind)!=4 or len(chunk)!=length or length>262144: raise ValueError()
            crc=struct.unpack('!I',raw[offset+8+length:offset+12+length])[0]
            if zlib.crc32(kind+chunk)&0xffffffff!=crc: raise ValueError()
            if not parts and kind!=b'IHDR': raise ValueError()
            if kind==b'IHDR':
                if parts or length!=13: raise ValueError()
                width,height,depth,color,compression,filtering,interlace=struct.unpack('!IIBBBBB',chunk)
                if not (1<=width<=512 and 1<=height<=512 and depth==8 and color in (2,6) and compression==filtering==interlace==0): raise ValueError()
            elif kind==b'IDAT': data.append(chunk)
            elif kind==b'IEND':
                if length or offset+12!=len(raw): raise ValueError()
                ended=True
            elif kind[0]&32==0: raise ValueError()  # Unknown critical chunks.
            if kind in (b'IHDR',b'IDAT',b'IEND'): parts.append(raw[offset:offset+12+length])
            offset+=12+length
        if not ended or not data: raise ValueError()
        expected=height*(1+width*(4 if color==6 else 3))
        decoder=zlib.decompressobj();pixels=decoder.decompress(b''.join(data),expected+1)
        if len(pixels)!=expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail: raise ValueError()
        stride=1+width*(4 if color==6 else 3)
        if any(pixels[i]>4 for i in range(0,len(pixels),stride)): raise ValueError()
        return 'data:image/png;base64,'+base64.b64encode(raw[:8]+b''.join(parts)).decode()
    except (ValueError,TypeError,IndexError,struct.error,zlib.error,binascii.Error):
        raise ValueError('Use a valid PNG avatar up to 512×512 pixels. The upload tool converts photos automatically.') from None
