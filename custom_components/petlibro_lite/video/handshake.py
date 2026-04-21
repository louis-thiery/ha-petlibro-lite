"""Tuya imm "cowboy" handshake — post-ICE, pre-media.

Reverse-engineered 2026-04-20 from libThingP2PSDK.so using r2ghidra on
`relay_session_handshake_encode_request`, `_encode_ack`, and
`_handle_msg`. Findings doc: `findings_handshake.md`.

## Wire format (over KCP)

```
[2B  u16 BE: tlv_id     ]
[2B  u16 BE: total_len  ]  # header + body
[attrs...]
```

Each attribute:

```
[2B  u16 BE: type]
[2B  u16 BE: length]
[length bytes: value]
[0..3 bytes: zero padding to 4-byte align]
```

Observed attribute types (tlv_id == 0xF400):

| type | meaning |
| ---: | ---     |
| 1    | state / pkt id (u16)           — 0=request (c→s), 1=response (s→c), 2=ack (c→s), 3=complete (s→c) |
| 2    | AES-CBC IV (16 bytes)          |
| 3    | devId (plaintext ASCII string) |
| 4    | uId (plaintext ASCII string)   |
| 7    | AES-CBC ciphertext of the inner JSON body (PKCS7-padded) |

## JSON body

**Client → server (state=0, "request"):**

```json
{
  "clientType": <int>,
  "method":     "connect" | "reconnect",
  "devId":      "<devId>",
  "uId":        "<uid>",
  "timestamp":  <double>,
  "authorization": "random=<hex>"
}
```

**Server → client (state=1, "response"):**
Server HMACs `session[1]:session[0]:session[3]:session[6]:session[7]`
with key `session[13]` and returns `signature=<hex>`.

**Client → server (state=2, "ack"):**

```json
{
  "clientType": <int>,
  "method":     "ack",
  "devId":      "<devId>",
  "uId":        "<uid>",
  "statuscode": 200,
  "authorization": "signature=<hex>"
}
```

**Server → client (state=3, "complete"):** cowboy handshake complete 200 OK.

## Crypto (confirmed 2026-04-20 via mbedtls_aes_crypt_cbc Frida hook)

- **AES-CBC key (both directions)**: first 16 ASCII bytes of the
  `tcp_token.credential` returned by Tuya's `rtc.session.offer` (it
  arrives as `tcpRelay.credential` in the HTTPS response and is
  echoed into the offer/answer SDPs as `tcp_token.credential`). The
  credential is a 28-char base64 string; only the **raw first 16
  chars** (not base64-decoded) are used as AES-128 key bytes.
- Both client and server encrypt-and-decrypt with the SAME key.
- **HMAC** key (for the ack's `"signature="` field): derivation
  still TBD. Observed signature length = 64 hex chars = HMAC-SHA256.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from typing import Awaitable, Callable


# ---------- TLV framing ----------


_TLV_ID_HANDSHAKE = 0xF400   # confirmed: root_tlv_create(0xf400, …) in the binary

ATTR_STATE = 1        # u16 pkt state
ATTR_IV = 2           # 16B AES IV
ATTR_SESSION_ID = 3   # plaintext sessionId (e.g. "<devId><ts><rand>")
ATTR_TCP_USERNAME = 4 # plaintext tcp_token.username (e.g. "<ts>:<devId>")
ATTR_CIPHER = 7       # AES-CBC ciphertext of the inner JSON body (PKCS7 padded)
ATTR_SIG = 0x0008     # HMAC-SHA256 over the frame bytes up to sig value

# Legacy aliases for older tests; the handshake itself uses the
# session / tcp-username variants above.
ATTR_DEV_ID = ATTR_SESSION_ID
ATTR_UID = ATTR_TCP_USERNAME

STATE_REQUEST = 0
STATE_RESPONSE = 1
STATE_ACK = 2
STATE_COMPLETE = 3


def _pad4(n: int) -> int:
    r = n % 4
    return 0 if r == 0 else 4 - r


def tlv_encode(tlv_id: int, attrs: list[tuple[int, bytes]]) -> bytes:
    """Encode unsigned TLV.

    Wire format (big-endian):
      `[u16 tlv_id][u16 body_len][body]`
    where each attribute in the body is
      `[u16 type][u16 length][value][0..3 pad]`.

    The `body_len` field carries the length of the BODY ONLY (not
    including the 4-byte TLV header). Confirmed 2026-04-20 by
    tcpdumping a live handshake: a 316-byte frame carries body_len=312.
    """
    body = bytearray()
    for attr_type, value in attrs:
        body += attr_type.to_bytes(2, "big")
        body += len(value).to_bytes(2, "big")
        body += value
        body += b"\x00" * _pad4(len(value))
    out = bytearray()
    out += tlv_id.to_bytes(2, "big")
    out += len(body).to_bytes(2, "big")
    out += body
    return bytes(out)


def tlv_encode_signed(
    tlv_id: int, attrs: list[tuple[int, bytes]],
    *, hmac_key: bytes, sig_len: int = 32,
) -> bytes:
    """Encode signed TLV (matches `root_tlv_encode` in the binary).

    Appends attr type 0x800 containing `HMAC-SHA256(hmac_key, all_previous_bytes)`
    truncated to `sig_len` bytes. Used by the cowboy handshake, where the
    feeder silently drops frames missing this signature attribute.
    """
    body = bytearray()
    for attr_type, value in attrs:
        body += attr_type.to_bytes(2, "big")
        body += len(value).to_bytes(2, "big")
        body += value
        body += b"\x00" * _pad4(len(value))

    # Reserve the signature attribute at the end:
    sig_attr_header = ATTR_SIG.to_bytes(2, "big") + sig_len.to_bytes(2, "big")
    sig_pad = _pad4(sig_len)
    body_len = len(body) + 4 + sig_len + sig_pad  # body only, excludes 4B TLV header

    pre_sig = bytearray()
    pre_sig += tlv_id.to_bytes(2, "big")
    pre_sig += body_len.to_bytes(2, "big")
    pre_sig += body
    pre_sig += sig_attr_header
    # HMAC covers the header + body + the sig-attr header (everything
    # before where the sig goes).
    signature = hmac.new(hmac_key, bytes(pre_sig), hashlib.sha256).digest()[:sig_len]
    return bytes(pre_sig) + signature + b"\x00" * sig_pad


def tlv_decode(data: bytes) -> tuple[int, dict[int, bytes]]:
    """Parse a Tuya TLV frame. Returns `(tlv_id, {attr_type: value})`.

    The `body_len` field at offset 2 is the body length only (excludes
    the 4-byte TLV header), so the full on-wire frame is `4 + body_len`
    bytes. Only the last value seen per attr type is kept."""
    if len(data) < 4:
        raise ValueError(f"tlv too short: {len(data)}")
    tlv_id = int.from_bytes(data[0:2], "big")
    body_len = int.from_bytes(data[2:4], "big")
    frame_end = 4 + body_len
    if frame_end > len(data):
        raise ValueError(f"tlv frame_end {frame_end} > buffer {len(data)}")
    attrs: dict[int, bytes] = {}
    i = 4
    while i + 4 <= frame_end:
        attr_type = int.from_bytes(data[i:i + 2], "big")
        attr_len = int.from_bytes(data[i + 2:i + 4], "big")
        if i + 4 + attr_len > frame_end:
            raise ValueError(
                f"attr type={attr_type} len={attr_len} overflows tlv"
            )
        attrs[attr_type] = bytes(data[i + 4:i + 4 + attr_len])
        i += 4 + attr_len + _pad4(attr_len)
    return tlv_id, attrs


# ---------- AES-CBC wrap ----------


def _pkcs7_pad(data: bytes, block: int = 16) -> bytes:
    pad = block - (len(data) % block)
    return data + bytes([pad]) * pad


def _pkcs7_unpad(data: bytes) -> bytes:
    pad = data[-1]
    if pad < 1 or pad > 16 or data[-pad:] != bytes([pad]) * pad:
        raise ValueError("bad PKCS7 padding")
    return data[:-pad]


def cbc_encrypt(key: bytes, iv: bytes, plaintext: bytes) -> bytes:
    from Crypto.Cipher import AES  # type: ignore[import-not-found]
    return AES.new(key, AES.MODE_CBC, iv).encrypt(_pkcs7_pad(plaintext))


def cbc_decrypt(key: bytes, iv: bytes, ciphertext: bytes) -> bytes:
    from Crypto.Cipher import AES  # type: ignore[import-not-found]
    return _pkcs7_unpad(AES.new(key, AES.MODE_CBC, iv).decrypt(ciphertext))


# ---------- handshake session ----------


@dataclass
class HandshakeConfig:
    """Everything needed to drive one handshake from client side.

    Enc and dec use the SAME 16-byte key (confirmed 2026-04-20). The
    two context pointers at session+0x78 / session+0x80 are simply the
    mbedtls encrypt and decrypt schedules derived from the same master
    key — `derive_handshake_aes_key(credential)` extracts it from the
    `tcp_token.credential` field of the signaling offer.
    """

    dev_id: str                 # short feeder devId (used inside the JSON body)
    uid: str                    # our uid  (used inside the JSON body)
    session_id: str             # attr 3: "<devId><ts><rand>" from rtcSessionId
    tcp_username: str           # attr 4: "<ts>:<devId>" from tcp_token.username
    aes_cbc_key: bytes          # 16B AES-128 key (symmetric enc/dec)
    tlv_hmac_key: bytes         # HMAC key for the outer TLV 0x0008 signature
    body_hmac_key: bytes        # HMAC key for the ack's "signature=" field
    client_type: int = 1        # observed; meaning TBD
    method: str = "request"     # confirmed: "request" not "connect"
    sig_len: int = 32           # HMAC-SHA256 full length


def derive_handshake_aes_key(credential: str) -> bytes:
    """Extract the handshake AES-128 key from a tcp_token.credential string.

    The credential is the 28-char base64 blob Tuya returns in the
    `rtc.session.offer` response (`tcpRelay.credential` in the HTTPS
    result; `tcp_token.credential` in the offer/answer SDP envelope).
    The native SDK uses its first 16 raw ASCII bytes as the AES-128 key
    for the cowboy handshake — no base64 decoding.
    """
    if len(credential) < 16:
        raise ValueError(f"credential too short for 16-byte key: {credential!r}")
    return credential[:16].encode("ascii")


def derive_handshake_hmac_key(credential: str) -> bytes:
    """HMAC key for the body-level signature (`authorization: signature=…`).

    Confirmed against the live relay 2026-04-20: the HMAC key is the
    ENTIRE credential string (28 ASCII chars), not just the first 16.
    The outer TLV 0x0008 signature uses the same key.
    """
    return credential.encode("ascii")


def response_signature(
    hmac_key: bytes, tcp_username: str, session_id: str,
    uid: str, client_random: str,
) -> str:
    """Compute the HMAC the server should return in state=1.

    Format (4-field, offset 0x15589e in libThingP2PSDK.so):
        HMAC-SHA256(hmac_key, "<user>:<sess>:<uid>:<cR>")
    """
    msg = f"{tcp_username}:{session_id}:{uid}:{client_random}"
    return hmac.new(hmac_key, msg.encode("utf-8"), hashlib.sha256).hexdigest()


def ack_signature(
    hmac_key: bytes, tcp_username: str, session_id: str,
    uid: str, server_signature: str, server_random: str,
) -> str:
    """Compute the HMAC the client sends in state=2.

    Format (5-field, `%s:%s:%s:%s:%s`):
        HMAC-SHA256(hmac_key, "<user>:<sess>:<uid>:<server_sig>:<server_random>")

    Note the NON-intuitive order: the auth parser in libThingP2PSDK.so
    stores the incoming `signature=` field into session[6] and
    `,random=` into session[7], so the ack HMAC reads them in that
    same order.
    """
    msg = (
        f"{tcp_username}:{session_id}:{uid}:"
        f"{server_signature}:{server_random}"
    )
    return hmac.new(hmac_key, msg.encode("utf-8"), hashlib.sha256).hexdigest()


class HandshakeClient:
    """State-machine driver for the cowboy handshake, one instance per
    logical RTC session.

    Owns a pair of send/recv callbacks supplied by the caller (typically
    backed by `KcpTransport`). Pumps:

      1. build REQUEST (state 0) → send
      2. await RESPONSE (state 1) → validate
      3. build ACK (state 2) → send
      4. await COMPLETE (state 3) → done
    """

    def __init__(
        self, cfg: HandshakeConfig,
        *, send: Callable[[bytes], Awaitable[None]],
        recv: Callable[[], Awaitable[bytes]],
    ) -> None:
        self.cfg = cfg
        self._send = send
        self._recv = recv
        self._random_hex: str | None = None
        self._server_signature: str | None = None

    # ---- message builders ----

    def _build_request_json(self) -> dict:
        # Confirmed format (2026-04-20 captures): no `timestamp` field.
        # Random is a 32-char alphanumeric string, not necessarily hex.
        self._random_hex = secrets.token_hex(16)  # 32 chars, hex-alphabet works
        return {
            "clientType": self.cfg.client_type,
            "method": self.cfg.method,
            "devId": self.cfg.dev_id,
            "uId": self.cfg.uid,
            "authorization": f"random={self._random_hex}",
        }

    def _build_ack_json(self, signature_hex: str) -> dict:
        return {
            "clientType": self.cfg.client_type,
            "method": "ack",
            "devId": self.cfg.dev_id,
            "uId": self.cfg.uid,
            "statuscode": 200,
            "authorization": f"signature={signature_hex}",
        }

    def _wrap(self, state: int, body_json: dict) -> bytes:
        body_bytes = json.dumps(body_json, separators=(",", ":")).encode("utf-8")
        iv = secrets.token_bytes(16)
        ciphertext = cbc_encrypt(self.cfg.aes_cbc_key, iv, body_bytes)
        return tlv_encode_signed(_TLV_ID_HANDSHAKE, [
            (ATTR_STATE, state.to_bytes(2, "big")),
            (ATTR_IV, iv),
            (ATTR_SESSION_ID, self.cfg.session_id.encode("utf-8")),
            (ATTR_TCP_USERNAME, self.cfg.tcp_username.encode("utf-8")),
            (ATTR_CIPHER, ciphertext),
        ], hmac_key=self.cfg.tlv_hmac_key, sig_len=self.cfg.sig_len)

    def _unwrap(self, frame: bytes) -> tuple[int, dict]:
        _tlv_id, attrs = tlv_decode(frame)
        if ATTR_STATE not in attrs or ATTR_IV not in attrs or ATTR_CIPHER not in attrs:
            raise ValueError(f"incomplete handshake frame: attrs={list(attrs)}")
        state = int.from_bytes(attrs[ATTR_STATE], "big")
        plain = cbc_decrypt(self.cfg.aes_cbc_key, attrs[ATTR_IV], attrs[ATTR_CIPHER])
        body = json.loads(plain)
        return state, body

    # ---- run-to-completion ----

    async def run(self, timeout: float = 10.0) -> dict:
        """Drive states 0→1→2→3. Returns the COMPLETE body on success.

        The HMAC formulas (confirmed 2026-04-20 via live relay + r2ghidra
        on the response/ack encoders):

        - Response (server→client, state=1) sig =
              HMAC-SHA256(hkey, f"{tcp_user}:{session_id}:{uid}:{cR}")
          where hkey is the FULL credential string (28 ASCII chars).
          We verify this on receipt.
        - Ack (client→server, state=2) sig =
              HMAC-SHA256(hkey, f"{tcp_user}:{session_id}:{uid}:{server_sig}:{sR}")
          where session[6]=server_sig and session[7]=server_random (the
          auth parser in the binary stores them in that order).
        """
        # state 0: request
        req = self._wrap(STATE_REQUEST, self._build_request_json())
        await self._send(req)

        # state 1: response
        frame = await asyncio.wait_for(self._recv(), timeout)
        state, body = self._unwrap(frame)
        if state != STATE_RESPONSE:
            raise RuntimeError(f"expected state=1 (response), got {state}: {body}")
        auth = body.get("authorization", "")
        try:
            fields = dict(kv.split("=", 1) for kv in auth.split(","))
        except ValueError:
            raise RuntimeError(f"unparseable authorization in response: {auth!r}")
        server_sig = fields.get("signature", "")
        server_random = fields.get("random", "")
        if not server_sig or not server_random:
            raise RuntimeError(f"missing sig/random in response: {body}")
        self._server_signature = server_sig
        self._server_random = server_random

        # Verify server signature
        cR = self._random_hex or ""
        expected = response_signature(
            self.cfg.body_hmac_key, self.cfg.tcp_username,
            self.cfg.session_id, self.cfg.uid, cR,
        )
        if expected != server_sig:
            raise RuntimeError(
                f"server sig mismatch: expected {expected}, got {server_sig}"
            )

        # state 2: ack
        ack_sig = ack_signature(
            self.cfg.body_hmac_key, self.cfg.tcp_username,
            self.cfg.session_id, self.cfg.uid, server_sig, server_random,
        )
        ack = self._wrap(STATE_ACK, self._build_ack_json(ack_sig))
        await self._send(ack)

        # state 3: complete
        frame = await asyncio.wait_for(self._recv(), timeout)
        state, body = self._unwrap(frame)
        if state != STATE_COMPLETE:
            raise RuntimeError(f"expected state=3 (complete), got {state}: {body}")
        if body.get("statuscode") not in (200, 200.0):
            raise RuntimeError(f"complete says not OK: {body}")
        return body
