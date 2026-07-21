"""网易云 weapi 加密（日推、搜索等接口需要）。

公开的经典实现：AES-CBC 双重加密 + RSA 加密密钥。
参考自公开的 NeteaseCloudMusicApi 等项目。
"""

import base64
import json
import random

from Crypto.Cipher import AES

_MODULUS = (
    "00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7b725"
    "152b3ab17a876aea8a5aa76d2e417629ec4ee341f56135fccf695280104e0312"
    "ecbda92557c93870114af6c9d05c4f7f0c3685b7a46bee255932575cce10b424"
    "d813cfe4875d3e82047b97ddef52741d546b8e289dc6935b3ece0462db0a22b8e7"
)
_NONCE = "0CoJUm6Qyw8W8jud"
_IV = b"0102030405060708"
_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def _aes_encrypt(data: str, key: str) -> str:
    raw = data.encode("utf-8")
    pad = 16 - len(raw) % 16
    raw += bytes([pad]) * pad
    cipher = AES.new(key.encode("utf-8"), AES.MODE_CBC, _IV)
    return base64.b64encode(cipher.encrypt(raw)).decode("utf-8")


def _rsa_encrypt(secret: str) -> str:
    num = int(secret[::-1].encode("utf-8").hex(), 16)
    enc = pow(num, 0x10001, int(_MODULUS, 16))
    return format(enc, "x").zfill(256)


def encrypt(payload: dict) -> dict:
    """payload -> {"params": ..., "encSecKey": ...}"""
    text = json.dumps(payload)
    secret = "".join(random.choice(_CHARS) for _ in range(16))
    return {
        "params": _aes_encrypt(_aes_encrypt(text, _NONCE), secret),
        "encSecKey": _rsa_encrypt(secret),
    }
