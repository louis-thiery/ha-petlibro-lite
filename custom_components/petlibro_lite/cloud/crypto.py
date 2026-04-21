"""Crypto primitives for the Tuya-whitelabel PetLibro cloud API.

Fully reversed 2026-04-20 via Frida hooks on FUN_001093b4 (the underlying
HMAC-SHA256 primitive) inside libthing_security.so. The "algo 6" selector
dispatches to HMAC-SHA256, and every higher-level crypto op is a thin
wrapper around it:

    MAC(key, msg) = HMAC-SHA256(key, msg)  # returns 32 bytes

    sign(sign_input)           = MAC(SECRET,    sign_input)          # 32 bytes hex
    get_ch_key(client_id)      = MAC(client_id, APP_ID)[4:8] hex     # 8 hex chars
    get_encrypto_key(req, salt)= MAC(req, APP_ID + "_" + salt)[:8] hex # 16 hex chars (AES key in ASCII)

Where APP_ID = "{pkg}_{cert_fp}_{state1}_{state2}" with:
  pkg       = "com.dl.petlibro"
  cert_fp   = colon-sep uppercase hex of the app's signing cert SHA-256
  state1/2  = two 32-char ASCII constants loaded from t_cdc.tcfg (encrypted
              asset shipped in the APK; decrypted at app start). Extracted
              once via Frida on 2026-04-20. Fixed per-tenant, per-app-version.

SECRET is APP_ID (without trailing salt) — i.e. APP_ID is reused as the HMAC
key for signing and as part of the HMAC message for key derivation. The
choice of what goes where is the only tenant-specific detail beyond the
constants.

Validation:
  - sign: 544/544 oracle pairs match
  - get_encrypto_key: 456/487 match (all 31 mismatches are salt=None which
    triggers a separate C fallback path we don't currently invoke)
  - get_ch_key: synthesized + validated against the clientId -> 9fbad9d4 constant
  - decrypt_response (AES-128-GCM): validated via synthetic roundtrip
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json

from Crypto.Cipher import AES

# --- PetLibro-whitelabel-tenant-specific constants (extracted 2026-04-20) ---
PACKAGE_NAME = "com.dl.petlibro"
# App-cert SHA-256 fingerprint, colon-separated uppercase hex, as the native
# code concatenates it. From Frida dump of FUN_001093b4 inputs.
CERT_FP = (
    "1D:AE:14:11:EC:89:5A:CE:2F:63:A5:B4:C4:C0:54:C9"
    ":B7:67:2A:F2:BD:22:EC:DA:43:58:7F:F0:8F:C8:26:55"
)
# Two 32-char ASCII constants from t_cdc.tcfg (decrypted app config).
STATE_1 = "qknk7ns9r98tuumwgy9ydjxvedgm9jvd"
STATE_2 = "utdnvvf395hxtna5c983hs4u53hthecq"

# MQTT-specific tenant salt used for mqtt_username + mqtt_password
# derivation. This is a FIXED per-tenant constant, NOT the per-session
# ecode that the API crypto uses. Keeping these separate:
#   - CH_KEY_SALT (this constant): MQTT username/password only
#   - per-session ecode from login: API request/response AES-GCM key
#
# Originally confused with the API ecode on 2026-04-20 when one specific
# login happened to return ecode == CH_KEY_SALT. Subsequent logins showed
# ecode rotates per session while the MQTT salt stays fixed (verified via
# live captures: different ecodes in different sessions, but a single
# MQTT password `6dc400ed5776c39d` confirmed by mqtt_password() against
# the broker accepting the connection).
CH_KEY_SALT = "z2z7az772917a1z7"

# Composed APP_ID used as both the sign-MAC key and the getEncryptoKey-MAC msg prefix.
APP_ID = f"{PACKAGE_NAME}_{CERT_FP}_{STATE_1}_{STATE_2}"
# For get_ch_key the native code uses only the first two segments.
APP_ID_SHORT = f"{PACKAGE_NAME}_{CERT_FP}"


def md5_hex(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode()
    return hashlib.md5(data).hexdigest()


def _mac(key: bytes | str, msg: bytes | str) -> bytes:
    """The one primitive everything wraps: HMAC-SHA256 returning 32 bytes."""
    if isinstance(key, str):
        key = key.encode()
    if isinstance(msg, str):
        msg = msg.encode()
    return hmac.new(key, msg, hashlib.sha256).digest()


def get_ch_key(client_id: str) -> str:
    """Derive the `chKey` request field from the clientId.

    Returns 8 hex chars (4 bytes at offset 4 of the HMAC output). Same value
    for the lifetime of a (clientId, app-version) pair.
    """
    return _mac(client_id, APP_ID_SHORT)[4:8].hex()


def request_key(request_id: str) -> bytes:
    """Derive the AES-128 key for BOTH postData encrypt and response decrypt.

    Native name: `encryptPostData`. The name is misleading — the JNI method
    doesn't actually encrypt; it returns the *key* Java uses for both the
    request-postData AES-128-ECB encrypt and the response AES-128-GCM
    decrypt (symmetric).

    Key = HMAC-SHA256(request_id, APP_ID)[:8].hex() rendered as 16 ASCII
    bytes from [0-9a-f].
    """
    return _mac(request_id, APP_ID)[:8].hex().encode("ascii")


def get_encrypto_key(request_id: str, salt: str = CH_KEY_SALT) -> bytes:
    """Derive a salted 16-char AES-128 key.

    Native name: `getEncryptoKey`. Same algorithm as `request_key` but with
    the salt appended to APP_ID in the HMAC message. Used by a smaller set
    of code paths (MQTT signaling? specific endpoints?) — not the main
    api.json request/response flow.

    Most code should call `request_key()` instead.
    """
    if salt is None:
        raise NotImplementedError(
            "salt=None falls back to DAT_001154a0 which we don't model."
        )
    mac = _mac(request_id, f"{APP_ID}_{salt}")
    return mac[:8].hex().encode("ascii")


def sign_request(sign_input: str) -> str:
    """Compute the `sign` form field for an api.json request.

    `sign_input` is the canonical pipe-joined KV string the native code
    builds internally, e.g. `a=smartlife.p.time.get||appVersion=1.0.6||...`

    Returns 64 hex chars (HMAC-SHA256 output).
    """
    return _mac(APP_ID, sign_input).hex()


def encrypt_postdata(
    request_id: str,
    plaintext: str | bytes,
    *,
    iv: bytes | None = None,
    key: bytes | None = None,
) -> str:
    """AES-128-GCM encrypt the postData body.

    Wire format (same as the response side): base64([12-byte IV][ct][16-byte tag]).

    `key` defaults to the unsalted `request_key(request_id)` — correct for
    pre-login / sid-less calls. For authenticated calls, pass
    `get_encrypto_key(request_id)` explicitly. The caller knows which; the
    server mirrors the choice.

    `iv` is 12 random bytes unless a fixed one is supplied (tests).
    """
    import os
    if isinstance(plaintext, str):
        plaintext = plaintext.encode()
    if iv is None:
        iv = os.urandom(12)
    assert len(iv) == 12
    if key is None:
        key = request_key(request_id)
    ct, tag = AES.new(key, AES.MODE_GCM, nonce=iv).encrypt_and_digest(plaintext)
    return base64.b64encode(iv + ct + tag).decode("ascii")


def decrypt_response(result_b64: str, request_id: str) -> dict:
    """Decrypt the `result` field of an api.json response.

    Wire format: base64([12-byte IV][ciphertext][16-byte GCM tag]).
    Uses `request_key(request_id)` — same key that encrypted the request.
    """
    return decrypt_response_with_key(result_b64, request_key(request_id))


def decrypt_response_with_key(result_b64: str, key: bytes) -> dict:
    raw = base64.b64decode(result_b64)
    iv, ct, tag = raw[:12], raw[12:-16], raw[-16:]
    cipher = AES.new(key, AES.MODE_GCM, nonce=iv)
    pt = cipher.decrypt_and_verify(ct, tag)
    return json.loads(pt.decode("utf-8"))
