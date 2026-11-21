"""Protect local API credentials with the current Windows user's DPAPI key."""
from __future__ import annotations

import base64
import binascii
import ctypes
import os
import sys
import tempfile
from ctypes import wintypes
from pathlib import Path
from typing import Callable

_PROTECTED_PREFIX = b"VELTRIX-DPAPI-1:"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class CredentialFileError(RuntimeError):
    """The local credential file could not be protected or read safely."""


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _crypt_windows_data(data: bytes, *, protect: bool) -> bytes:
    if sys.platform != "win32":
        raise CredentialFileError("Windows DPAPI is available only on Windows.")

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    input_buffer = ctypes.create_string_buffer(data)
    input_blob = _DataBlob(
        len(data),
        ctypes.cast(input_buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    output_blob = _DataBlob()

    if protect:
        function = crypt32.CryptProtectData
        function.argtypes = [
            ctypes.POINTER(_DataBlob), wintypes.LPCWSTR, ctypes.POINTER(_DataBlob),
            wintypes.LPVOID, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(_DataBlob),
        ]
        function.restype = wintypes.BOOL
        succeeded = function(
            ctypes.byref(input_blob),
            "Veltrix API credentials",
            None,
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output_blob),
        )
    else:
        function = crypt32.CryptUnprotectData
        function.argtypes = [
            ctypes.POINTER(_DataBlob), ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(_DataBlob), wintypes.LPVOID, wintypes.LPVOID,
            wintypes.DWORD, ctypes.POINTER(_DataBlob),
        ]
        function.restype = wintypes.BOOL
        succeeded = function(
            ctypes.byref(input_blob),
            None,
            None,
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output_blob),
        )

    if not succeeded:
        raise ctypes.WinError(ctypes.get_last_error())

    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        kernel32.LocalFree(ctypes.cast(output_blob.pbData, ctypes.c_void_p))


def _protect_windows_data(data: bytes) -> bytes:
    return _crypt_windows_data(data, protect=True)


def _unprotect_windows_data(data: bytes) -> bytes:
    return _crypt_windows_data(data, protect=False)


def _replace_atomically(path: Path, contents: bytes) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(contents)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def load_env_file(
    path: str | Path,
    *,
    platform: str | None = None,
    protect: Callable[[bytes], bytes] | None = None,
    unprotect: Callable[[bytes], bytes] | None = None,
) -> str | None:
    """Read dotenv text, sealing plaintext files on Windows before returning."""
    env_path = Path(path)
    if not env_path.is_file():
        return None

    current_platform = sys.platform if platform is None else platform
    contents = env_path.read_bytes()
    if contents.startswith(_PROTECTED_PREFIX):
        if current_platform != "win32":
            raise CredentialFileError(
                "This API credential file is protected for its original Windows user."
            )
        try:
            protected_contents = base64.b64decode(
                contents[len(_PROTECTED_PREFIX):].strip(),
                validate=True,
            )
        except (binascii.Error, ValueError) as exc:
            raise CredentialFileError(
                "The protected API credential file is invalid. Recreate the .env file."
            ) from exc
        try:
            plaintext = (unprotect or _unprotect_windows_data)(protected_contents)
        except OSError as exc:
            raise CredentialFileError(
                "Veltrix could not decrypt the saved API keys for this Windows user. "
                "Delete the protected .env file and recreate it, or set the keys in "
                "Windows environment variables."
            ) from exc
    else:
        plaintext = contents
        if current_platform == "win32" and contents:
            try:
                protected_contents = (protect or _protect_windows_data)(contents)
                _replace_atomically(
                    env_path,
                    _PROTECTED_PREFIX + base64.b64encode(protected_contents) + b"\n",
                )
            except OSError as exc:
                raise CredentialFileError(
                    "Veltrix could not protect the .env file for this Windows user. "
                    "Check the file and folder permissions; no keys were loaded."
                ) from exc

    try:
        return plaintext.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CredentialFileError("The .env file must contain valid UTF-8 text.") from exc
