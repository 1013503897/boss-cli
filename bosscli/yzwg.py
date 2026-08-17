"""
Pure-Python reproduction of BOSS直聘 libyzwg.so (com.twl.signer.YZWG) native crypto.

Reverse-engineered from libyzwg-arm64-v8a.so (BOSS直聘 v14.050) with IDA + a unidbg
differential oracle. Every primitive below is byte-exact against the native library
(nativeSignature is bit-for-bit; nativeEncodeRequest matches the cipher/header/base64
exactly and round-trips — the only non-determinism is the bundled liblz4 encoder's
choices, which the server tolerates because it only decompresses).

Layout of the native functions (RegisterNatives table in JNI_OnLoad):
    nativeSignature([B,String)          -> 0x23b6c   sig  "V3.0"+md5(input|SALT|key)
    nativeEncodeRequest([B,String)      -> 0x1f6ac   sp   base64url(RC4(LZ4-framed))
    nativeEncodeRequestBody([B,String)  -> 0x206b8   raw bytes of the above (no base64)
    nativeDecodeContent(...)            -> 0x24980   RC4-decrypt + LZ4-decompress
    nativeCalculateCRC32([B)            -> 0x28388   "%u" of IEEE CRC32

Strings inside the .so are XOR-obfuscated (per-string key = trailing byte); the class
name and the "V3.0" prefix were recovered that way.
"""
from __future__ import annotations
import struct, base64, hashlib, zlib
import lz4.block

# SALT is bound to BOSS's official APK signing certificate. JNI_OnLoad derives it as
# RC4(key=fmt(sig_hashCode>>1,>>2,>>3), data=const32) and caches it (qword_444470);
# for the official signature it is this fixed 32-char value. Re-signing the APK changes it.
SALT = "a308f3628b3f39f7d35cdebeb6920e21"

MAGIC = b"BZPBlock"   # 24-byte compression frame magic written by sub_1D338


def rc4(key: bytes, data: bytes) -> bytes:
    """Standard RC4. The native PRGA wraps each byte in TWIST(x)=(~x&0xCF|x&0x30) on
    both keystream and plaintext; TWIST cancels under XOR, so this is plain RC4."""
    S = list(range(256)); j = 0
    for i in range(256):
        j = (j + S[i] + key[i % len(key)]) & 0xff
        S[i], S[j] = S[j], S[i]
    i = j = 0; out = bytearray()
    for b in data:
        i = (i + 1) & 0xff; j = (j + S[i]) & 0xff
        S[i], S[j] = S[j], S[i]
        out.append(b ^ S[(S[i] + S[j]) & 0xff])
    return bytes(out)


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode().replace('+', '-').replace('/', '_').replace('=', '~')


def _unb64(s: str) -> bytes:
    return base64.b64decode(s.replace('-', '+').replace('_', '/').replace('~', '='))


def _rc4_key(key: str | None) -> bytes:
    # effective RC4 key = SALT concatenated with the (optional) secret key string
    return (SALT + (key or "")).encode()


def _frame(data: bytes) -> bytes:
    """sub_1D338: 24-byte header + LZ4 block. header = magic|u32(0)|complen|origlen|(origlen^complen)."""
    comp = lz4.block.compress(data, mode='default', store_size=False)
    origlen, complen = len(data), len(comp)
    header = MAGIC + struct.pack('<IIII', 0, complen, origlen, origlen ^ complen)
    return header + comp


def _deframe(framed: bytes) -> bytes:
    assert framed[:8] == MAGIC, f"bad frame magic {framed[:8]!r}"
    _zero, complen, origlen, chk = struct.unpack('<IIII', framed[8:24])
    assert chk == (origlen ^ complen), "frame checksum mismatch"
    return lz4.block.decompress(framed[24:24 + complen], uncompressed_size=origlen)


def native_signature(input_bytes: bytes, key: str | None = None) -> str:
    """sig = "V3.0" + md5(input || SALT || key). Byte-exact vs native."""
    buf = input_bytes + SALT.encode() + (key.encode() if key else b"")
    return "V3.0" + hashlib.md5(buf).hexdigest()


def native_encode_request(input_bytes: bytes, key: str | None = None) -> str:
    """sp: base64url(RC4(SALT||key, frame(input))). Valid + round-trips vs native."""
    return _b64(rc4(_rc4_key(key), _frame(input_bytes)))


def native_encode_request_body(input_bytes: bytes, key: str | None = None) -> bytes:
    """Same pipeline as nativeEncodeRequest but returns the raw encrypted bytes (no base64)."""
    return rc4(_rc4_key(key), _frame(input_bytes))


def native_decode_content(blob: bytes | str, key: str | None = None) -> bytes:
    """Inverse of encodeRequestBody/encodeRequest: RC4-decrypt then LZ4-decompress.
    Accepts raw bytes or a base64url string (server responses are base64url)."""
    raw = _unb64(blob) if isinstance(blob, str) else blob
    return _deframe(rc4(_rc4_key(key), raw))


def native_calculate_crc32(input_bytes: bytes) -> str:
    """CRC32 (IEEE) as an unsigned decimal string ("%u"). Empty input -> ""."""
    if not input_bytes:
        return ""
    return str(zlib.crc32(input_bytes) & 0xffffffff)
