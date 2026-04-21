"""Login flow for the Tuya-whitelabel PetLibro cloud.

Two-step flow (captured 2026-04-20):

  1. `smartlife.m.user.username.token.get` with {countryCode, isUid, username}
     → returns RSA-1024 public key (base64 DER), exponent, and a one-shot
     login `token` (32-hex-char-like string).

  2. `smartlife.m.user.email.password.login` with
     {countryCode, email, ifencrypt:1, options, passwd, token}
     where `passwd` is hex(RSA_PKCS1_v1_5(password, pubkey)) — 256 hex chars
     for a 1024-bit key.
     → returns full User object including `sid` (~56-char session token).

The response's `ecode` field is the per-account salt (identical to the
legacy `CH_KEY_SALT` constant for the PetLibro tenant — not a coincidence;
it's literally that salt).
"""
from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from typing import Any

from Crypto.Cipher import PKCS1_v1_5
from Crypto.PublicKey import RSA


@dataclass
class LoginResult:
    sid: str
    uid: str
    ecode: str              # the per-session salt (matches CH_KEY_SALT constant)
    email: str
    user_alias: str
    raw: dict[str, Any]     # full response body for anything else


def _rsa_encrypt_password(password: str, pb_key_b64: str) -> str:
    """RSA-1024 PKCS#1 v1.5 encrypt the MD5-hex of the password.

    Decompiled from `com.thingclips.sdk.user.dqdbbqp.java` (2026-04-21 jadx
    dump of com.dl.petlibro v1.0.6):

        String s = MD5Util.md5AsBase64(password);
        RSAUtil.generateRSAPublicKey("", tokenBean.getPublicKey() + "\\n" + tokenBean.getExponent());
        strEncrypt = RSAUtil.encrypt(..., s);
        apiParams.putPostData("passwd", strEncrypt);

    Despite the name, `md5AsBase64` actually returns the **MD5 hex** (32
    lowercase hex chars) — see `MD5Util.java:504` which calls
    `HexUtil.bytesToHexString(computeMD5Hash(bArr))`. So the on-wire
    `passwd` = RSA(md5_hex(password)), NOT RSA(password) and NOT
    RSA(base64(md5(password))). Missing this pre-hashing step made Tuya
    return `USER_PASSWD_WRONG` for any real password because the
    server-side decrypt yielded `password` as plaintext instead of the
    32-char hex digest it expected.
    """
    md5_hex = hashlib.md5(password.encode("utf-8")).hexdigest()
    der = base64.b64decode(pb_key_b64)
    key = RSA.import_key(der)
    ct = PKCS1_v1_5.new(key).encrypt(md5_hex.encode("ascii"))
    return ct.hex()


def login(client, email: str, password: str, country_code: str = "1") -> LoginResult:
    """Run the two-step login against the live cloud; set client.sid.

    The two Tuya endpoints each have their own API version, distinct from the
    "1.0" default used by most other calls. Captured from the PetLibro Lite
    app 2026-04-20:

        smartlife.m.user.username.token.get      v=2.0
        smartlife.m.user.email.password.login    v=3.0

    Using v=1.0 for the second call returns `USER_PASSWD_WRONG` even with
    correct credentials — likely because v=1.0 expects a plaintext/legacy
    password encoding and our RSA-encrypted hex never matches.
    """
    # Step 1: fetch RSA pubkey + one-shot token
    step1 = client.call(
        "smartlife.m.user.username.token.get",
        version="2.0",
        body={"countryCode": country_code, "isUid": False, "username": email},
    )
    if not step1.get("success"):
        raise RuntimeError(f"token.get failed: {step1}")
    tok = step1["result"]
    pb_key = tok["pbKey"]
    token = tok["token"]

    # Step 2: send encrypted password + token
    encrypted_pw = _rsa_encrypt_password(password, pb_key)
    step2 = client.call(
        "smartlife.m.user.email.password.login",
        version="3.0",
        body={
            "countryCode": country_code,
            "email": email,
            "ifencrypt": 1,
            "options": '{"group": 1,"mfaCode": ""}',
            "passwd": encrypted_pw,
            "token": token,
        },
    )
    if not step2.get("success"):
        raise RuntimeError(f"login failed: {step2}")
    u = step2["result"]
    client.sid = u["sid"]
    return LoginResult(
        sid=u["sid"],
        uid=u["uid"],
        ecode=u["ecode"],
        email=u.get("email", ""),
        user_alias=u.get("userAlias", ""),
        raw=u,
    )
