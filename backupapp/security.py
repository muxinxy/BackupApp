"""凭据加密：plain / dpapi（Windows，ctypes 零依赖）/ keyring（跨平台 OS 凭据库）。

存储语义：
- plain：JSON 明文
- dpapi：JSON 存 base64(DPAPI(明文))，绑定当前 Windows 用户账户——
  数据目录拷到别的机器后无法解密（迁移前请改回 plain 或重输密码）
- keyring：存 OS 凭据库（Windows 凭据管理器 / macOS Keychain / Linux Secret Service），
  JSON 字段清空
"""

import base64
import ctypes
import ctypes.wintypes as wt
import dataclasses
import sys

from .model import SelfBackup

SERVICE = "backupapp"
_KEY_REMOTE = "selfbackup_remote"
_KEY_ARCHIVE = "selfbackup_archive"


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi(data: bytes, encrypt: bool) -> bytes:
    if sys.platform != "win32":
        raise RuntimeError("DPAPI 仅支持 Windows")
    crypt = ctypes.windll.crypt32
    fn = crypt.CryptProtectData if encrypt else crypt.CryptUnprotectData
    buf = ctypes.create_string_buffer(data, len(data))
    in_blob = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    out_blob = _Blob()
    if not fn(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)):
        raise RuntimeError("DPAPI 调用失败")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def encrypt_secret(secret: str, kind: str) -> str:
    """加密明文 -> 可存 JSON 的字符串。kind 为 keyring 时原样返回（不入 JSON）。"""
    if kind == "plain" or not secret:
        return secret
    if kind == "dpapi":
        return base64.b64encode(_dpapi(secret.encode("utf-8"), True)).decode()
    if kind == "keyring":
        return secret
    raise ValueError(f"未知凭据存储: {kind}")


def decrypt_secret(stored: str, kind: str = "dpapi") -> str:
    """解密 JSON 中的存储值。空值/plain 原样返回。"""
    if not stored or kind == "plain":
        return stored
    if kind == "dpapi":
        return _dpapi(base64.b64decode(stored), False).decode("utf-8")
    if kind == "keyring":
        return stored
    raise ValueError(f"未知凭据存储: {kind}")


def keyring_set(username: str, value: str) -> None:
    import keyring
    keyring.set_password(SERVICE, username, value or "")


def keyring_get(username: str) -> str:
    import keyring
    return keyring.get_password(SERVICE, username) or ""


def secrets(sb: SelfBackup) -> tuple[str, str]:
    """返回 (远程密码, 压缩包密码) 明文，供上传/测试/打包使用。"""
    if sb.credential_store == "dpapi":
        return (decrypt_secret(sb.password), decrypt_secret(sb.archive_password))
    if sb.credential_store == "keyring":
        return (keyring_get(_KEY_REMOTE), keyring_get(_KEY_ARCHIVE))
    return sb.password, sb.archive_password


def plain_sb(sb: SelfBackup) -> SelfBackup:
    """返回密码已解密的副本，供 make_uploader 等使用。"""
    pw, apw = secrets(sb)
    return dataclasses.replace(sb, password=pw, archive_password=apw)
