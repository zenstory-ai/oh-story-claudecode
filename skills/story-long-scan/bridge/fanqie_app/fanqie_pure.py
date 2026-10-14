"""Deterministic, offline signer extracted from the Rust implementation.

This module makes no HTTP requests and persists no device data.  Callers own
the URL, device id, timestamp, and nonces used as signer inputs.
"""

from __future__ import annotations

import base64
import html
import hashlib
import re
from dataclasses import dataclass
from typing import Final

M32: Final = 0xFFFFFFFF
M64: Final = 0xFFFFFFFFFFFFFFFF
SIGN_KEY: Final = bytes.fromhex(
    "346b8093079e4282d0d0fc19e015226d29ed8e9dd62a0766830a823141224f42"
)


def _u32(value: int) -> int:
    return value & M32


def _u64(value: int) -> int:
    return value & M64


def _ror32(value: int, count: int) -> int:
    count &= 31
    return _u32((value >> count) | (value << (32 - count)))


def _ror64(value: int, count: int) -> int:
    count &= 63
    return _u64((value >> count) | (value << (64 - count)))


def raw_query(url: str) -> bytes:
    """Return exactly the bytes signed by the Rust ``raw_query`` helper."""
    query = url.split("?", 1)[1] if "?" in url else ""
    return query.split("#", 1)[0].encode()


def sm3_digest(data: bytes) -> bytes:
    """Pure Python GB/T 32905-2016 SM3."""
    state = [0x7380166F, 0x4914B2B9, 0x172442D7, 0xDA8A0600, 0xA96F30BC, 0x163138AA, 0xE38D_EE4D, 0xB0FB0E4E]
    message = bytearray(data)
    message.append(0x80)
    while len(message) % 64 != 56:
        message.append(0)
    message.extend((len(data) * 8).to_bytes(8, "big"))
    for offset in range(0, len(message), 64):
        words = [int.from_bytes(message[offset + index : offset + index + 4], "big") for index in range(0, 64, 4)]
        for index in range(16, 68):
            value = words[index - 16] ^ words[index - 9] ^ _ror32(words[index - 3], 17)
            p1 = value ^ _ror32(value, 17) ^ _ror32(value, 9)
            words.append(_u32(p1 ^ _ror32(words[index - 13], 25) ^ words[index - 6]))
        a, b, c, d, e, f, g, h = state
        for index in range(64):
            constant = 0x79CC4519 if index < 16 else 0x7A879D8A
            ss1 = _ror32(_u32(_ror32(a, 20) + e + _ror32(constant, 32 - (index & 31))), 25)
            ss2 = ss1 ^ _ror32(a, 20)
            ff = a ^ b ^ c if index < 16 else (a & b) | (a & c) | (b & c)
            gg = e ^ f ^ g if index < 16 else (e & f) | ((~e) & g)
            tt1 = _u32(ff + d + ss2 + (words[index] ^ words[index + 4]))
            tt2 = _u32(gg + h + ss1 + words[index])
            d, c, b, a = c, _ror32(b, 23), a, tt1
            h, g, f, e = g, _ror32(f, 13), e, _u32(tt2 ^ _ror32(tt2, 23) ^ _ror32(tt2, 15))
        state = [_u32(left ^ right) for left, right in zip(state, [a, b, c, d, e, f, g, h])]
    return b"".join(value.to_bytes(4, "big") for value in state)


def _gf_mul(left: int, right: int) -> int:
    output = 0
    for _ in range(8):
        if right & 1:
            output ^= left
        left = ((left << 1) ^ (0x11B if left & 0x80 else 0)) & 0xFF
        right >>= 1
    return output


def _gf_pow(value: int, exponent: int) -> int:
    output = 1
    while exponent:
        if exponent & 1:
            output = _gf_mul(output, value)
        value = _gf_mul(value, value)
        exponent >>= 1
    return output


def _aes_sbox(value: int) -> int:
    inverse = _gf_pow(value, 254) if value else 0
    return inverse ^ ((inverse << 1) | (inverse >> 7)) & 0xFF ^ ((inverse << 2) | (inverse >> 6)) & 0xFF ^ ((inverse << 3) | (inverse >> 5)) & 0xFF ^ ((inverse << 4) | (inverse >> 4)) & 0xFF ^ 0x63


def _aes_round_keys(key: bytes) -> list[bytes]:
    if len(key) != 16:
        raise ValueError("AES-128 requires a 16-byte key")
    expanded = list(key)
    rcon = 1
    while len(expanded) < 176:
        word = expanded[-4:]
        if len(expanded) % 16 == 0:
            word = [_aes_sbox(value) for value in word[1:] + word[:1]]
            word[0] ^= rcon
            rcon = _gf_mul(rcon, 2)
        for value in word:
            expanded.append(expanded[-16] ^ value)
    return [bytes(expanded[index : index + 16]) for index in range(0, 176, 16)]


def aes128_encrypt_block(block: bytes, key: bytes) -> bytes:
    """AES-128 ECB block encryption, used only as a pure primitive."""
    if len(block) != 16:
        raise ValueError("AES block must be 16 bytes")
    state = list(block)
    keys = _aes_round_keys(key)

    def add_round_key(round_key: bytes) -> None:
        for index, value in enumerate(round_key):
            state[index] ^= value

    def shift_rows() -> None:
        before = state[:]
        for row in range(4):
            for column in range(4):
                state[row + 4 * column] = before[row + 4 * ((column + row) & 3)]

    def mix_columns() -> None:
        for column in range(4):
            index = column * 4
            a, b, c, d = state[index : index + 4]
            state[index : index + 4] = [
                _gf_mul(a, 2) ^ _gf_mul(b, 3) ^ c ^ d,
                a ^ _gf_mul(b, 2) ^ _gf_mul(c, 3) ^ d,
                a ^ b ^ _gf_mul(c, 2) ^ _gf_mul(d, 3),
                _gf_mul(a, 3) ^ b ^ c ^ _gf_mul(d, 2),
            ]

    add_round_key(keys[0])
    for round_key in keys[1:10]:
        state[:] = [_aes_sbox(value) for value in state]
        shift_rows()
        mix_columns()
        add_round_key(round_key)
    state[:] = [_aes_sbox(value) for value in state]
    shift_rows()
    add_round_key(keys[10])
    return bytes(state)


def aes128_decrypt_block(block: bytes, key: bytes) -> bytes:
    if len(block) != 16:
        raise ValueError("AES block must be 16 bytes")
    inverse = [0] * 256
    for value in range(256):
        inverse[_aes_sbox(value)] = value
    state = list(block)
    keys = _aes_round_keys(key)

    def add(round_key: bytes) -> None:
        for index, value in enumerate(round_key):
            state[index] ^= value

    def inverse_shift() -> None:
        before = state[:]
        for row in range(4):
            for column in range(4):
                state[row + 4 * column] = before[row + 4 * ((column - row) & 3)]

    def inverse_mix() -> None:
        for column in range(4):
            index = column * 4
            a, b, c, d = state[index : index + 4]
            state[index : index + 4] = [
                _gf_mul(a, 14) ^ _gf_mul(b, 11) ^ _gf_mul(c, 13) ^ _gf_mul(d, 9),
                _gf_mul(a, 9) ^ _gf_mul(b, 14) ^ _gf_mul(c, 11) ^ _gf_mul(d, 13),
                _gf_mul(a, 13) ^ _gf_mul(b, 9) ^ _gf_mul(c, 14) ^ _gf_mul(d, 11),
                _gf_mul(a, 11) ^ _gf_mul(b, 13) ^ _gf_mul(c, 9) ^ _gf_mul(d, 14),
            ]

    add(keys[10])
    for key_round in reversed(keys[1:10]):
        inverse_shift()
        state[:] = [inverse[value] for value in state]
        add(key_round)
        inverse_mix()
    inverse_shift()
    state[:] = [inverse[value] for value in state]
    add(keys[0])
    return bytes(state)


def _pkcs7(data: bytes) -> bytes:
    padding = 16 - len(data) % 16
    return data + bytes([padding]) * padding


def aes128_cbc_encrypt(data: bytes, key: bytes, iv: bytes) -> bytes:
    previous = iv
    output = bytearray()
    for offset in range(0, len(_pkcs7(data)), 16):
        block = _pkcs7(data)[offset : offset + 16]
        previous = aes128_encrypt_block(bytes(a ^ b for a, b in zip(block, previous)), key)
        output.extend(previous)
    return bytes(output)


def aes128_cbc_decrypt(data: bytes, key: bytes, iv: bytes) -> bytes:
    if len(data) == 0 or len(data) % 16 or len(iv) != 16:
        raise ValueError("invalid AES-CBC input")
    output = bytearray()
    previous = iv
    for offset in range(0, len(data), 16):
        block = data[offset : offset + 16]
        output.extend(a ^ b for a, b in zip(aes128_decrypt_block(block, key), previous))
        previous = block
    padding = output[-1]
    if not 1 <= padding <= 16 or output[-padding:] != bytes([padding]) * padding:
        raise ValueError("invalid AES-CBC PKCS#7 padding")
    return bytes(output[:-padding])


APPLOG_MAGIC: Final = bytes.fromhex("746305100000")
APPLOG_KEY_MATERIAL: Final = bytes.fromhex("4dd4c2e6b83162090e52b3c7a6733ba41cb2462b829ab58a196b39db57177524f49baf7f08e8d68d26a72e37c1a95a2f1f05a51892aef2949732b62a38aadd58")


def _applog_key(seed: bytes) -> tuple[bytes, bytes]:
    digest = hashlib.sha512(hashlib.sha512(seed).digest() + APPLOG_KEY_MATERIAL).digest()
    return digest[:16], digest[16:32]


def applog_pack_decrypt(frame: bytes) -> bytes:
    if not frame.startswith(APPLOG_MAGIC) or len(frame) < 54:
        raise ValueError("invalid ApplogPack frame")
    key, iv = _applog_key(frame[6:38])
    plaintext = aes128_cbc_decrypt(frame[38:], key, iv)
    if len(plaintext) < 64:
        raise ValueError("short ApplogPack payload")
    import gzip
    return gzip.decompress(plaintext[64:])


def unwrap_server_key(keyblob_base64: str) -> bytes:
    try:
        raw = base64.b64decode(keyblob_base64.strip(), validate=True)
    except (ValueError, base64.binascii.Error) as error:
        raise ValueError("keyBlob is not valid Base64") from error
    if len(raw) < 32 or (len(raw) - 16) % 16:
        raise ValueError("invalid keyBlob length")
    for key in (b"UmlsZTU1WTgwMjM4", bytes.fromhex("ac25c67ddd8f38c1b37a2348828e222e")):
        try:
            result = aes128_cbc_decrypt(raw[16:], key, raw[:16])
            if len(result) == 16:
                return result
        except ValueError:
            continue
    raise ValueError("unable to unwrap keyBlob")


def decrypt_chapter_text(chapter_base64: str, aes_key: bytes) -> str:
    import gzip
    try:
        raw = base64.b64decode(chapter_base64.strip(), validate=True)
    except (ValueError, base64.binascii.Error) as error:
        raise ValueError("chapter ciphertext is not valid Base64") from error
    if len(raw) < 32 or (len(raw) - 16) % 16:
        raise ValueError("invalid chapter ciphertext length")
    plaintext = aes128_cbc_decrypt(raw[16:], aes_key, raw[:16])
    if not plaintext.startswith(b"\x1f\x8b"):
        raise ValueError("decrypted AES plaintext is not gzip")
    decoded = gzip.decompress(plaintext).decode("utf-8", "replace")
    return extract_text(decoded)


def extract_text(decoded: str) -> str:
    blocks = re.findall(r"(?s)<blk[^>]*>(.*?)</blk>", decoded)
    if blocks:
        return "\n".join(html.unescape(re.sub(r"(?s)<[^>]+>", "", value).strip()) for value in blocks if value.strip())
    decoded = re.sub(r"(?s)<script.*?</script>|(?s)<style.*?</style>", "", decoded)
    decoded = re.sub(r"(?s)<[^>]+>", "\n", decoded)
    return html.unescape(re.sub(r"\n{3,}", "\n\n", decoded).strip())


def _aes_ofb(data: bytes, key: bytes, iv: bytes) -> bytes:
    feedback = iv
    output = bytearray()
    for offset in range(0, len(data), 16):
        feedback = aes128_encrypt_block(feedback, key)
        output.extend(left ^ right for left, right in zip(data[offset : offset + 16], feedback))
    return bytes(output)


def gorgon(query: bytes, khronos: int, body: bytes | None = None, entropy: int = 0x1EB0, runtime_property: int = 0x0128) -> str:
    payload = bytearray(20)
    payload[:4] = hashlib.md5(query).digest()[:4]
    if body is not None:
        payload[4:8] = hashlib.md5(body).digest()[:4]
    payload[12:16] = (0x04090901).to_bytes(4, "little")
    payload[16:20] = _u32(khronos).to_bytes(4, "big")
    key = bytes([5, runtime_property & 0xFF, 0x50, entropy >> 8, 0x47, 0x1E, runtime_property >> 8, entropy & 0xFF])
    keybox = list(range(256))
    accumulator = 0
    for index in range(256):
        accumulator = (keybox[index] + accumulator + key[index & 7]) & 0xFF
        selected = keybox[accumulator]
        keybox[index] = selected
        keybox[accumulator] = selected
    index = accumulator = 0
    data = bytearray(payload)
    for offset, value in enumerate(data):
        index = (index + 1) & 0xFF
        accumulator = (keybox[index] + accumulator) & 0xFF
        selected = keybox[accumulator]
        keybox[index] = selected
        keybox[accumulator] = selected
        data[offset] = value ^ keybox[(keybox[index] + selected) & 0xFF]
    for offset in range(len(data)):
        value = ((data[offset] << 4) | (data[offset] >> 4)) & 0xFF
        value ^= data[offset + 1] if offset + 1 < len(data) else (data[0] if offset else 0)
        data[offset] = (~(int(f"{value:08b}"[::-1], 2) ^ len(data))) & 0xFF
    return (bytes([0x84, 0x04, entropy & 0xFF, entropy >> 8, runtime_property & 0xFF, runtime_property >> 8]) + data).hex()


def helios(khronos: int, device_profile_id: str, aid: str, nonce: int) -> str:
    material = _u32(nonce).to_bytes(4, "little") + aid.encode()
    text = hashlib.md5(material).hexdigest().encode()
    plaintext = f"{_u32(khronos)}-{device_profile_id}-{aid}".encode()
    packet = _u32(nonce).to_bytes(4, "little") + _aes_ofb(_pkcs7(plaintext), text[:16], text[16:])
    return base64.b64encode(packet).decode()


def _selector(context: bytes) -> int:
    state = 0x20230928
    for offset in range(0, 52, 2):
        state = _u32((state >> 4) ^ ((_u32(state << 6)) ^ context[offset]) ^ state)
        byte = context[offset + 1]
        bic = _u32(_u32(state << 12) & _u32(~byte))
        state = _u32(~(_u32(bic + byte) ^ (state >> 7) ^ state))
    return state & 0x0F


def _pack_context(query: bytes, body: bytes | None, khronos: int) -> bytes:
    return sm3_digest(query) + (hashlib.md5(body).digest() if body else b"\0" * 16) + _u32(khronos).to_bytes(4, "little")


def find_normalized_khronos(query: bytes, body: bytes | None, current: int, skew: int = 120) -> int:
    for distance in range(skew + 1):
        for candidate in (current + distance, current - distance):
            candidate = _u32(candidate)
            if candidate & 3 == 2 and _selector(_pack_context(query, body, candidate)) == 12:
                return candidate
    raise ValueError("no normalized Medusa branch within the requested clock skew")


def _branch_twelve(context: bytes) -> bytes:
    initial = [0x5D27E43D, 0x8B3283B3, 0x01FD0032, 0x07A8979A, 0x55A6881D, 0x8EB21D59, 0xA7D5F6D5, 0x259C2840]
    salt = bytes.fromhex("fa4561d7c275611a7fe36db35753be7b")
    constants = [int(value, 16) for value in (
        "ed93ebfa eab73081 cc61eff3 044e3ff8 42ff3fdb 8c28ef96 06b58e2d 0603ae0d "
        "8cfadbfc 6961332c 30c371f3 f476d451 5594f7b5 2a13e85c d1cf0495 dbc0a23d "
        "01dfc28b 8372b436 ee1bdb3e 7133c03f 2280835a 9db1a9b9 358ce2e3 8f234386 "
        "3a2c1af3 b43b42da 1489c5e8 1c6b20f7 a176dc48 6d3769b5 dbe1941c 580c1b19 "
        "5f38a998 08d05fb9 903850c2 13900c95 37fecaa2 5b06b81c 119ea213 6c8eecc1 "
        "742e19b8 a8f72e2e 8cdd34eb ce069430 c0bdd6c5 9b68da3f 2d33d23c 83feee13 "
        "aab4435c b14e8f49 af383dbc 155d606d 895ff752 0c60a8a3 c2cee1aa 577ec50f "
        "c40d8d13 ded4b5f4 13bfc591 c28cf47a 2a1bdb9b 0a12e9c0 0e1f3e82 ecdd6197"
    ).split()]
    schedule = [int.from_bytes(context[index : index + 4], "big") for index in range(0, 52, 4)] + [0] * 115
    khronos = int.from_bytes(context[48:], "little")
    salt_rotation = (khronos + 1) & 7
    word_rotation = (khronos - 1_785_465_602) & 31
    rotated_salt = bytes(((value >> salt_rotation) | (value << (8 - salt_rotation))) & 0xFF for value in salt)
    schedule[13] = int.from_bytes(rotated_salt[:4], "big")
    schedule[15] = 0x1A0
    for index in range(16, 128):
        s0 = _ror32(schedule[index - 15], 7) ^ _ror32(schedule[index - 15], 18) ^ (schedule[index - 15] >> 3)
        s1 = _ror32(schedule[index - 2], 17) ^ _ror32(schedule[index - 2], 19) ^ (schedule[index - 2] >> 10)
        schedule[index] = _u32(schedule[index - 16] + s0 + schedule[index - 7] + s1)
    a, b, c, d, e, f, g, h = [_ror32(value, word_rotation) for value in initial]
    initial_state = [a, b, c, d, e, f, g, h]
    for round_index in range(98):
        choose = (h & (d ^ f)) ^ f
        majority = (b & c) | (a & (b | c))
        sigma_h = _ror32(h, 6) ^ _ror32(h, 11) ^ _ror32(h, 25)
        first = _u32(sigma_h + e + _ror32(constants[(round_index + 55) & 63], word_rotation) + schedule[(round_index + 119) & 127] + choose)
        next_f = _u32(first + (_ror32(b, 2) ^ _ror32(b, 13) ^ _ror32(b, 22)) + majority)
        a, b, c, d, e, f, g, h = h, a, b, c, d, next_f, f, _u32(first + g)
    state = [_u32(left + right) for left, right in zip([a, b, c, d, e, f, g, h], initial_state)]
    folded = b"".join((state[index] ^ state[index + 4]).to_bytes(4, "big") for index in range(4))
    checksum = 0x20220420
    for index, byte in enumerate(folded[:12]):
        if index & 1:
            checksum = _u32(~((_u32(checksum << 11) | byte) ^ (checksum >> 5) ^ checksum))
        else:
            checksum = _u32(checksum ^ _u32(checksum << 7) ^ byte ^ (checksum >> 3))
    return folded + _u32((checksum ^ 0x01000000) | 4).to_bytes(4, "little")


class _Writer:
    def __init__(self) -> None:
        self.value = bytearray()

    def varint(self, number: int, value: int) -> None:
        self.raw((number << 3) | 0)
        self.raw(value)

    def raw(self, value: int) -> None:
        while value >= 0x80:
            self.value.append((value & 0x7F) | 0x80)
            value >>= 7
        self.value.append(value)

    def bytes(self, number: int, value: bytes) -> None:
        self.raw((number << 3) | 2)
        self.raw(len(value))
        self.value.extend(value)

    def string(self, number: int, value: str) -> None:
        self.bytes(number, value.encode())


def _zig32(value: int) -> int:
    value &= M32
    signed = value if value < 0x80000000 else value - (1 << 32)
    return ((value << 1) ^ (signed >> 31)) & M32


def _zig64(value: int) -> int:
    value &= M64
    signed = value if value < (1 << 63) else value - (1 << 64)
    return ((value << 1) ^ (signed >> 63)) & M64


def _message(query: bytes, khronos: int, wall_clock_ms: int, root_nonce: int, pack: bytes, device_id: str) -> bytes:
    def summary() -> bytes:
        out = _Writer()
        for number, value in ((1, 314), (2, 5), (3, 694367), (5, 884933294)):
            out.varint(number, _zig32(value))
        return bytes(out.value)

    def device() -> bytes:
        out = _Writer()
        out.varint(1, _zig32(1)); out.varint(2, _zig32(2))
        for number, value in ((3, "1967"), (4, device_id), (5, "AcPwBVngdSOFTah-ug5gK3JFX"), (6, "7.2.1")):
            out.string(number, value)
        out.varint(7, _zig32(100)); out.varint(8, _zig32(100)); out.varint(10, _zig32(1))
        for number, value in ((11, "wifi"), (12, "Asia/Shanghai,8"), (13, "zh-Hans-CN")):
            out.string(number, value)
        out.varint(14, _zig32(12)); out.string(15, "3840,2160"); out.string(22, "26.5"); out.varint(23, _zig32(100))
        for number, value in ((25, 1780280707782), (26, 1785411514385), (27, 1784082506552), (28, wall_clock_ms + 894), (29, -999999)):
            out.varint(number, _zig64(value))
        for number, value in ((30, "Mac16,11"), (31, "arm64"), (37, "25.5.0")):
            out.string(number, value)
        out.varint(40, _zig64(1785411514071))
        return bytes(out.value)

    def environment() -> bytes:
        out = _Writer()
        elapsed = 90 + (wall_clock_ms - 1_785_411_604_000) // 1000
        for number, value in ((1, elapsed), (2, 694367), (3, 694367), (5, 694367), (7, 46617)):
            out.varint(number, _zig32(value))
        out.string(8, "App Store"); out.string(11, "655351128"); out.bytes(12, device())
        process = _Writer(); process.varint(1, _zig64(1785411520)); process.varint(2, 3); process.varint(4, _zig32(200))
        out.bytes(13, bytes(process.value))
        out.varint(15, _zig32(47577)); out.varint(16, 46); out.varint(17, _zig32(494)); out.varint(22, _zig32(694367)); out.varint(23, _zig32(694367))
        return bytes(out.value)

    out = _Writer()
    out.bytes(1, bytes.fromhex("2d4b4fca49750d433fb5ae2c226dcc56")); out.varint(2, 10); out.varint(3, _zig32(root_nonce))
    for number, value in ((4, "1967"), (5, device_id), (6, "442130837"), (7, "7.2.1"), (8, "v04.09.09-ml-iOS")):
        out.string(number, value)
    timestamp = _zig32(khronos)
    out.varint(9, _zig32(67700993)); out.bytes(10, bytes.fromhex("2801000000000000")); out.varint(11, 1); out.varint(12, timestamp); out.bytes(13, pack); out.bytes(14, sm3_digest(query)[:6]); out.bytes(15, summary()); out.string(16, "AxDyxqn1mAqONJyY4CVna7kVs"); out.varint(17, timestamp); out.string(20, "none"); out.varint(21, _zig32(369)); out.bytes(23, environment()); out.string(24, '{"sts":32219,"kd":0,"fkd":514145325,"pd":-375617555,"lp":"2|520830913368|520830913368|2091399554238|53817867328","fl":"0|0|0|0|0|0|0|0|0|0","dyn":"","do":0,"tk":true}')
    return bytes(out.value)


_MEDUSA_SBOX: Final = bytes.fromhex(
    "9d7a1f957fb98b86d7f5ebead1b28cdabd7469cd733477e8b10911b6242b8965"
    "17229a6214d8411e2e780bc2a0a4553181640401f7ab8d85ee255a7d484f560c"
    "7be468076a26db1ddf9750423a4560b763b084d92d3dde75b52fbec3dce229fd"
    "b323c5a2e0c7209c2c6b924bba51f4385f911b6fef57791c825d30bf1ac46637"
    "465e6ead27b4cb39ff1803c902701698a1dd138393d25ce6f1a6cca8c66c28ed"
    "bc08f9a305445854a9530dcac8fc67a5e36dd388cf5ba7f232439b8e80b84976"
    "10f80af30072069eceaeecd6d5e9e1597c87c0d0949f96c14d61f0bbfe52993e"
    "fa4ee7af3f19acf6478a3b0f350e12403c8ffb7eaad471e5904a2133a215364c"
)
_MEDUSA_KEYS: Final = [
    bytes.fromhex("050a1d40ce6cae0df6bf9511ed9b03ad"),
    bytes.fromhex("209f13e8eef3bde5184c28f4f5d72b59"),
    bytes.fromhex("8b5dc72965ae7acc7de2523888357961"),
]


def _medusa_transform(input_bytes: bytes) -> bytes:
    if len(input_bytes) != 30:
        raise ValueError("Medusa transform requires 30 bytes")

    def xtime(value: int) -> int:
        return ((value << 1) ^ (0x1B if value & 0x80 else 0)) & 0xFF

    def add_vm(state: list[int], key: bytes) -> None:
        for group in range(4):
            for offset, key_offset in enumerate((1, 0, 2, 3)):
                state[group * 4 + offset] ^= key[group * 4 + key_offset]

    def add_final(state: list[int]) -> None:
        for group in range(4):
            for offset, key_offset in enumerate((0, 3, 1, 2)):
                state[group * 4 + offset] ^= _MEDUSA_KEYS[1][group * 4 + key_offset]

    def mix(state: list[int]) -> list[int]:
        arranged = state[:]
        for group in range(4):
            arranged[group * 4], arranged[group * 4 + 1] = arranged[group * 4 + 1], arranged[group * 4]
        mixed = [0] * 16
        for column in range(4):
            a, b, c, d = [arranged[column + row * 4] for row in range(4)]
            result = [xtime(a) ^ xtime(b) ^ b ^ c ^ d, a ^ xtime(b) ^ xtime(c) ^ c ^ d, a ^ b ^ xtime(c) ^ xtime(d) ^ d, xtime(a) ^ a ^ b ^ c ^ xtime(d)]
            for row in range(4):
                mixed[row * 4 + column] = result[row]
        return [mixed[group * 4 + index] for group in range(4) for index in (2, 1, 3, 0)]

    def encrypt(block: bytes, chain: bytes) -> bytes:
        state = [left ^ right for left, right in zip(block, chain)]
        add_vm(state, _MEDUSA_KEYS[0])
        state = [_MEDUSA_SBOX[state[index]] for index in (8, 9, 10, 11, 0, 1, 2, 3, 12, 13, 14, 15, 4, 5, 6, 7)]
        state = [state[index] for index in (0, 9, 14, 15, 4, 13, 2, 7, 8, 1, 6, 3, 12, 5, 10, 11)]
        state = mix(state)
        add_vm(state, _MEDUSA_KEYS[1])
        state = [_MEDUSA_SBOX[state[index]] for index in (8, 9, 10, 11, 0, 1, 2, 3, 12, 13, 14, 15, 4, 5, 6, 7)]
        state = [state[index] for index in (0, 9, 14, 15, 4, 13, 2, 7, 8, 1, 6, 3, 12, 5, 10, 11)]
        add_vm(state, _MEDUSA_KEYS[2]); add_final(state)
        return bytes(state)

    padded = input_bytes + b"\x02\x02"
    first = encrypt(padded[:16], bytes.fromhex("c73a20452c238a5cc51b8d0525f2a31a"))
    return first + encrypt(padded[16:], first)


def _medusa(query: bytes, device_id: str, khronos: int, root_nonce: int, payload_nonce: int, seed_nonce: int, runtime_property: int, body: bytes | None) -> str:
    context = _pack_context(query, body, khronos)
    if _selector(context) != 12:
        raise ValueError("khronos does not select the normalized Medusa branch")
    pack = _branch_twelve(context)
    seed_profile = 0x1000 | ((sm3_digest(query)[0] & 0x3F) << 6) | (pack[0] & 0x3F)
    message = _message(query, khronos, _u32(khronos) * 1000, root_nonce, pack, device_id)
    key = sm3_digest(SIGN_KEY + _u32(payload_nonce).to_bytes(4, "little") + SIGN_KEY)
    padded = _pkcs7(message)
    keys = [int.from_bytes(key[index : index + 8], "little") for index in range(24, -1, -8)]
    encoded = bytearray()
    for offset in range(0, len(padded), 16):
        left, right = int.from_bytes(padded[offset : offset + 8], "little"), int.from_bytes(padded[offset + 8 : offset + 16], "little")
        for round_key in keys:
            function = (_ror64(right, 60) & _ror64(right, 59)) ^ _ror64(right, 61)
            left, right = right, _u64(left ^ function ^ round_key)
        encoded.extend(left.to_bytes(8, "little") + right.to_bytes(8, "little"))
    source = _u64(runtime_property).to_bytes(8, "little") + encoded
    tail = _u32(payload_nonce).to_bytes(4, "little")[2:]
    state = 0
    for index, byte in enumerate(tail):
        if index & 1:
            mixed = _u32(_u32(state << 11) | byte) ^ (state >> 5) ^ state
            state = _u32(~mixed)
        else:
            mixed = _u32(state << 7) ^ byte
            state = _u32(state ^ mixed ^ (state >> 3))
    reverse_key = state.to_bytes(4, "big")
    intermediate = bytes(value ^ reverse_key[index & 3] for index, value in enumerate(reversed(source)))
    second = bytearray(b"\x4e" + _u32(seed_nonce).to_bytes(4, "little") + b"\x01" + seed_profile.to_bytes(2, "little") + b"\x18" + intermediate + tail)
    lanes = (1, 1 << 14, 1 << 21, 1 << 31, 1 << 33, 1 << 44, 1 << 50, 1 << 59)
    transform_input = bytearray()
    for index in range(30):
        word = int.from_bytes(second[index * 8 : index * 8 + 8], "little")
        compact = sum((1 << bit) for bit, lane in enumerate(lanes) if word & lane)
        transform_input.append((compact & 1) | (((compact >> 2) & 1) << 1) | (((compact >> 3) & 1) << 2) | (((compact >> 4) & 1) << 3) | (((compact >> 7) & 1) << 4) | (((compact >> 5) & 1) << 5) | (((compact >> 6) & 1) << 6) | (((compact >> 1) & 1) << 7))
    transformed = _medusa_transform(bytes(transform_input))
    lane_mask = sum(lanes)
    for index, value in enumerate(transformed[:30]):
        permuted = (value & 1) | (((value >> 7) & 1) << 1) | (((value >> 1) & 1) << 2) | (((value >> 2) & 1) << 3) | (((value >> 3) & 1) << 4) | (((value >> 5) & 1) << 5) | (((value >> 6) & 1) << 6) | (((value >> 4) & 1) << 7)
        word = int.from_bytes(second[index * 8 : index * 8 + 8], "little")
        word = (word & ~lane_mask) | sum(lane for bit, lane in enumerate(lanes) if permuted & (1 << bit))
        second[index * 8 : index * 8 + 8] = word.to_bytes(8, "little")
    prefixes = (5, 0xCA4F4B2D, 0x430D7549, 0x2CAEB53F, 0x56CC6D22)
    packet = b"".join(_u32(khronos ^ mask).to_bytes(4, "little") for mask in prefixes) + _u32(payload_nonce).to_bytes(4, "little")[:2] + b"\x01\x02" + transformed[30:] + second
    return base64.b64encode(packet).decode()


@dataclass(frozen=True)
class SignInput:
    url: str
    device_id: str
    khronos: int
    helios_nonce: int
    root_nonce: int
    payload_nonce: int
    seed_nonce: int
    body: bytes | None = None
    runtime_property: int = 0x0128
    gorgon_entropy: int = 0x1EB0
    helios_device_id: str = "442130837"
    aid: str = "1967"


def sign_headers(input: SignInput) -> dict[str, str]:
    """Return all six deterministic headers for a normalized Medusa timestamp."""
    query = raw_query(input.url)
    context = _pack_context(query, input.body, input.khronos)
    if _selector(context) != 12:
        raise ValueError("khronos does not select the normalized Medusa branch")
    headers = {
        "X-Argus": base64.b64encode(_u32(input.khronos).to_bytes(4, "little")).decode(),
        "X-Gorgon": gorgon(query, input.khronos, input.body, input.gorgon_entropy, input.runtime_property),
        "X-Helios": helios(input.khronos, input.helios_device_id, input.aid, input.helios_nonce),
        "X-Khronos": str(_u32(input.khronos)),
        "X-Ladon": base64.b64encode(b"\0\0\0\0").decode(),
        "X-Medusa": _medusa(query, input.device_id, input.khronos, input.root_nonce, input.payload_nonce, input.seed_nonce, input.runtime_property, input.body),
    }
    if input.body is not None:
        headers["x-ss-stub"] = hashlib.md5(input.body).hexdigest().upper()
    return headers
