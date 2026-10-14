"""AES-256-CBC 解密模块。

API 响应解密：
  Base64 → AES-256-CBC(SHA256(api_key), IV=0x00*16) → plaintext

章节内容解密（双层）：
  Layer 1: 全局 API key 解密响应 → 提取 command + txt_content
  Layer 2: command 解密 txt_content → 最终明文
"""

import base64
import hashlib
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

from . import config


# 默认使用当前 App 2.9.362 的响应 key；旧协议可显式传 legacy key。
DEFAULT_API_KEY = config.CURRENT_API_KEY


def aes_decrypt(ciphertext_bytes: bytes, key_str: str) -> bytes:
    """AES-256-CBC 解密，key=SHA256(key_str)，IV=16 字节零。"""
    key = hashlib.sha256(key_str.encode("utf-8")).digest()
    iv = bytes([0] * 16)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    plaintext = unpad(cipher.decrypt(ciphertext_bytes), AES.block_size)
    return plaintext


def decrypt_response(response_b64: str, key_str: str = DEFAULT_API_KEY) -> bytes:
    """解密 API 响应：Base64 解码 → AES-256-CBC 解密。"""
    ciphertext = base64.b64decode(response_b64)
    return aes_decrypt(ciphertext, key_str)


def decrypt_response_for_version(response_b64: str,
                                 app_version: str) -> bytes:
    """按 App 版本选择响应 AES key。"""
    return decrypt_response(
        response_b64,
        key_str=config.response_key_for_version(app_version),
    )


def decrypt_chapter(content_b64: str, command_key: str) -> bytes:
    """解密章节内容（第二层加密）：Base64 → AES-256-CBC(command_key)。"""
    ciphertext = base64.b64decode(content_b64)
    return aes_decrypt(ciphertext, command_key)
