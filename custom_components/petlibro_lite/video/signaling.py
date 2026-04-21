"""MQTT signaling between us and the feeder (via Tuya's cloud broker).

STATUS: envelope decoded, topic scheme confirmed. Captured via Frida
on 2026-04-20 — see captures/mqtt_capture.log. The only gap remaining
is the **pre-login** credential derivation: the MQTT username and
password come out of native code we haven't finished RE'ing
(`doCommandNative(cmd=2, ecode)` for the password). For now the
simplest path is to capture them via `hooks/mqtt_capture.js` once per
session and pass them in verbatim, which is what
`MqttSignalingConfig.from_capture()` is for.

What we know:

1. The Tuya MQTT broker reuses the app-level connection used for DP
   control — P2P signaling is just messages with `protocol = 302`.
2. Broker: `{host}:8883` TLS, where `host` comes from login's
   `mobileMqttsUrl`.
3. Topic scheme:
   - Publish: `smart/mb/out/{devId}`
   - Subscribe: `smart/mb/in/{devId}` (one per device we care about)
4. On-wire payload envelope (confirmed 2026-04-20):

       [3B "2.2" ASCII][4B CRC32 BE][4B seq BE][4B src_id BE]
       [AES-128-ECB(localKey, PKCS7({"data":<inner>,
                                    "protocol":<code>,
                                    "t":<unix_seconds>}))]

   where `localKey` is the device's 16-byte AES local key (from the
   Tuya `devices.list` API — we already have it in `feeder_creds.json`)
   and `<inner>` is `{"header":{…},"msg":{…}}` for protocol 302.
5. Credential shape (static RE + capture):
   - clientId = `{packageName}_mb_{deviceID}_{md5Base64(uid+'sdkfasodifca')}`
   - username = `{partnerIdentity}_v1_{mAppId}_{chKey}_mb_{token}{md5Tail}`
   - password = `doCommandNative(cmd=2, ecode)` middle 16 hex chars

The `mAppId` is NOT our composed Phase-1 `APP_ID` — it's a short
(~20-char) per-tenant appKey that the native code exposes. Captured
value for PetLibro US: `vmwyfs95mmaqg5awvcjt`.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from ..cloud.crypto import APP_ID, get_ch_key


# ---- credential derivation (all pure — no live broker needed) ----


def _md5_hex(data: str | bytes) -> str:
    """MD5 rendered as lowercase hex.

    Tuya calls this method `md5AsBase64` in MD5Util but it actually
    returns hex, not base64 (naming artefact from an internal rename).
    Verified against captured MQTT credentials 2026-04-20.
    """
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.md5(data).hexdigest()


# Kept for back-compat / call sites that really wanted real base64
def _md5_base64(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return base64.b64encode(hashlib.md5(data).digest()).decode("ascii")


# PetLibro-US per-tenant constants captured via Frida 2026-04-20.
# Not secret — every PetLibro app install sees the same mAppId.
M_APP_ID = "vmwyfs95mmaqg5awvcjt"


def mqtt_client_id(package_name: str, device_id: str, uid: str) -> str:
    """Build the MQTT `clientId`.

    `device_id` here is the Android device ID (from `PhoneUtil.getDeviceID`) —
    NOT the Tuya feeder id. For a headless python client we can pick any
    stable 16-char hex; the server only needs it unique per session.
    """
    uid_md5 = _md5_base64(uid + "sdkfasodifca")
    user_part = f"{device_id}_{uid_md5}"
    return f"{package_name}_mb_{user_part}"


def mqtt_username(
    partner_identity: str, token: str, ecode: str, m_app_id: str = M_APP_ID,
) -> str:
    """Build the MQTT username.

    Pattern: `{partnerIdentity}_v1_{mAppId}_{chKey}_mb_{token}{md5Tail}`.

    Confirmed against live-captured username 2026-04-20:
    - `mAppId`  = the short 20-char per-tenant key, NOT our composed APP_ID
    - `md5Tail` = last 16 chars of `md5_hex(md5_hex(mAppId) + ecode)`
    - `chKey`   = HMAC-SHA256(mAppId, APP_ID_SHORT)[4:8].hex()

    Where the `token` comes from is still being traced — Phase-1
    login's `rtc.session.offer` response has `auth` but that doesn't
    match the captured token length. Probably from a different
    login-flow endpoint; will resolve when we RE login end-to-end.
    """
    ch_key = get_ch_key(m_app_id)
    md5_outer = _md5_hex(_md5_hex(m_app_id) + ecode)
    md5_tail = md5_outer[-16:]
    return f"{partner_identity}_v1_{m_app_id}_{ch_key}_mb_{token}{md5_tail}"


def mqtt_password(app_id: str = APP_ID, salt: str | None = None) -> str:
    """Derive the MQTT password.

    Captured 2026-04-20: `doCommandNative(ctx, cmd=2, CH_KEY_SALT, null, false)`
    returns `md5(md5(APP_ID) + CH_KEY_SALT)` — i.e. the full
    hex-digest of MD5(MD5_HEX(APP_ID) + salt) — and the caller then
    takes the *middle* 16 chars: `result[(len>>1)-8:(len>>1)+8]`, which
    for a 32-char hex string is `result[8:24]`.

    Because both APP_ID and salt are compile-time constants, the
    MQTT password is a single value for every install of the app.
    For PetLibro US: `6dc400ed5776c39d`.
    """
    from ..cloud.crypto import CH_KEY_SALT
    if salt is None:
        salt = CH_KEY_SALT
    inner = hashlib.md5(app_id.encode("utf-8")).hexdigest()
    full = hashlib.md5((inner + salt).encode("utf-8")).hexdigest()
    mid = len(full) >> 1
    return full[mid - 8 : mid + 8]


# ---- config + message envelope ----


@dataclass
class MqttSignalingConfig:
    """Everything needed to open the Tuya app-mode MQTT connection.

    Two construction paths:

    - `MqttSignalingConfig.from_capture(...)` — pass in username /
      password / clientId that were captured live via
      `hooks/mqtt_capture.js`. This is the *only* reliable path until
      the native `doCommandNative(cmd=2)` password derivation is
      fully RE'd.
    - direct construction — derives creds from login-response fields
      using the static-RE formulas in `mqtt_client_id` /
      `mqtt_username`. Only username is actually computable; password
      still raises NotImplementedError.
    """

    host: str                             # from login response `mobileMqttsUrl`
    port: int = 8883                      # always 8883 per qdpppbq.qdddbpp
    package_name: str = "com.dl.petlibro"
    device_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    uid: str = ""
    partner_identity: str = ""            # from login response
    token: str = ""                       # from login response
    ecode: str = ""                       # from login response
    # Override-me path — when these are set, `client_id` / `username` /
    # `password` return them verbatim rather than deriving.
    override_client_id: str | None = None
    override_username: str | None = None
    override_password: str | None = None

    @classmethod
    def from_capture(
        cls, host: str, *, client_id: str, username: str,
        password: str | None = None,
    ) -> "MqttSignalingConfig":
        """Build a config from a Frida-captured credential pair.

        `password` is optional — since cmd=2 is now fully reversed
        (`mqtt_password()`), passing only `client_id` + `username`
        still works and the password falls back to the derived value.
        Useful when you only have captures of the username."""
        return cls(
            host=host,
            override_client_id=client_id,
            override_username=username,
            override_password=password,
        )

    @property
    def client_id(self) -> str:
        if self.override_client_id is not None:
            return self.override_client_id
        return mqtt_client_id(self.package_name, self.device_id, self.uid)

    @property
    def username(self) -> str:
        if self.override_username is not None:
            return self.override_username
        return mqtt_username(self.partner_identity, self.token, self.ecode)

    @property
    def password(self) -> str:
        if self.override_password is not None:
            return self.override_password
        return mqtt_password(self.ecode)

    @property
    def subscribe_topic(self) -> str:
        # Not used with captured creds — for captured creds we subscribe
        # to `smart/mb/in/{devId}` per device we care about.
        return f"smart/mb/in/{self.client_id}"

    def publish_topic(self, dev_id: str) -> str:
        return f"smart/mb/out/{dev_id}"

    def device_inbox(self, dev_id: str) -> str:
        """The topic to SUBSCRIBE to for a specific device's incoming signaling."""
        return f"smart/mb/in/{dev_id}"


# Message envelope — the OUTER JSON shape is known; the on-wire
# serialization (likely AES-CBC over this JSON with the device
# localKey) is still TBD.


def build_offer_message(
    uid: str, dev_id: str, session_id: str, sdp: str, *,
    path: str = "lan",
    ices: list[dict] | None = None,
    tcp_token: dict | None = None,
    log_cfg: dict | None = None,
    is_pre: bool = True,
    security_level: int = 3,
    p2p_skill: int = 99,
) -> dict:
    return {
        "header": {
            "from": uid,
            "to": dev_id,
            "sessionid": session_id,
            "moto_id": "",
            "type": "offer",
            "trace_id": "",
            "is_pre": 1 if is_pre else 0,
            "p2p_skill": p2p_skill,
            "security_level": security_level,
            "path": path,
        },
        "msg": {
            "sdp": sdp,
            "preconnect": True,
            "token": ices or [],
            "tcp_token": tcp_token or {},
            "log": log_cfg or {},
        },
    }


def build_candidate_message(
    uid: str, dev_id: str, session_id: str, candidate_sdp: str,
    *, path: str = "lan",
) -> dict:
    return {
        "header": {
            "from": uid,
            "to": dev_id,
            "sessionid": session_id,
            "moto_id": "",
            "type": "candidate",
            "trace_id": "",
            "path": path,
        },
        "msg": {"candidate": candidate_sdp},
    }


_VERSION_PREFIX = b"2.2"       # pv string as 3 bytes ASCII
_SRC_ID_DEFAULT = 0x0009C47E   # observed constant; suspected per-tenant

# Imported lazily inside pack/unpack so the module doesn't require
# pycryptodome at import time (the test suite doesn't exercise crypto).
def _aes_ecb(local_key: bytes):
    from Crypto.Cipher import AES  # type: ignore[import-not-found]
    return AES.new(local_key, AES.MODE_ECB)


def _pkcs7_pad(data: bytes, block: int = 16) -> bytes:
    pad = block - (len(data) % block)
    return data + bytes([pad]) * pad


def _pkcs7_unpad(data: bytes) -> bytes:
    pad = data[-1]
    if pad < 1 or pad > 16 or data[-pad:] != bytes([pad]) * pad:
        raise ValueError("bad PKCS7 padding")
    return data[:-pad]


def pack_envelope(
    inner: dict, *, protocol: int = 302, local_key: bytes, seq: int,
    timestamp_s: int | None = None, src_id: int = _SRC_ID_DEFAULT,
) -> bytes:
    """Serialize a signaling message into Tuya's MQTT binary envelope.

    Envelope (confirmed via live capture 2026-04-20):

        [3B "2.2"][4B CRC32-BE of the rest][4B seq BE]
        [4B src_id BE][AES-128-ECB(localKey, PKCS7(inner_wrapper))]

    The CRC32 covers every byte after itself (seq + src_id + ciphertext).
    `inner_wrapper` = `{"data": inner, "protocol": <code>, "t": <ts>}`.
    """
    if timestamp_s is None:
        timestamp_s = int(time.time())
    wrapper = {"data": inner, "protocol": protocol, "t": timestamp_s}
    # separators=(",",":") to match the compact JSON the app emits.
    payload = json.dumps(wrapper, separators=(",", ":")).encode("utf-8")
    cipher = _aes_ecb(local_key).encrypt(_pkcs7_pad(payload))

    header = seq.to_bytes(4, "big") + src_id.to_bytes(4, "big")
    crc = binascii.crc32(header + cipher).to_bytes(4, "big")
    return _VERSION_PREFIX + crc + header + cipher


def unpack_envelope(
    packet: bytes, *, local_key: bytes,
) -> tuple[int, int, dict]:
    """Inverse of `pack_envelope`. Returns `(protocol, seq, inner)`.

    Raises `ValueError` if the header or CRC is bad or the inner JSON
    cannot be parsed.
    """
    if len(packet) < 15 or packet[:3] != _VERSION_PREFIX:
        raise ValueError(f"bad envelope header: {packet[:16]!r}")
    crc_got = int.from_bytes(packet[3:7], "big")
    seq = int.from_bytes(packet[7:11], "big")
    src_id = int.from_bytes(packet[11:15], "big")
    body = packet[15:]
    crc_exp = binascii.crc32(packet[7:15] + body)
    if crc_exp != crc_got:
        raise ValueError(f"CRC mismatch: header={crc_got:08x} expected={crc_exp:08x}")
    plain = _pkcs7_unpad(_aes_ecb(local_key).decrypt(body))
    wrapper = json.loads(plain)
    return int(wrapper["protocol"]), seq, wrapper["data"]


# ---- client scaffold (connect() works once password is known) ----


class MqttSignaling:
    """Async wrapper around the Tuya app-mode MQTT channel, surfacing
    just the protocol-302 P2P signaling messages for one specific
    device.

    Uses `paho-mqtt` under the hood (installed via pyproject). Wraps
    its sync callbacks in asyncio via a loop handle so callers can
    `await` answers + remote candidates cleanly.
    """

    def __init__(
        self, config: MqttSignalingConfig, *, dev_id: str, local_key: bytes,
    ) -> None:
        self.config = config
        self.dev_id = dev_id
        self.local_key = local_key
        self._seq = 0
        self._on_answer: Callable[[str], None] | None = None
        self._on_remote_candidate: Callable[[str], None] | None = None
        self._client = None  # paho Client, lazy-init
        self._loop = None

    def on_answer(self, cb: Callable[[str], None]) -> None:
        self._on_answer = cb

    def on_remote_candidate(self, cb: Callable[[str], None]) -> None:
        self._on_remote_candidate = cb

    async def connect(self) -> None:
        import asyncio
        import ssl
        import paho.mqtt.client as mqtt  # type: ignore[import-not-found]

        self._loop = asyncio.get_running_loop()
        ready = self._loop.create_future()

        client = mqtt.Client(client_id=self.config.client_id, clean_session=True)
        client.username_pw_set(self.config.username, self.config.password)
        ctx = ssl.create_default_context()
        # Tuya brokers use standard public CA; no pinning needed on our side
        client.tls_set_context(ctx)

        def _on_connect(_c, _u, _flags, rc):
            if rc == 0:
                client.subscribe(self.config.device_inbox(self.dev_id), qos=1)
                self._loop.call_soon_threadsafe(
                    lambda: (not ready.done()) and ready.set_result(None)
                )
            else:
                self._loop.call_soon_threadsafe(
                    lambda: (not ready.done())
                    and ready.set_exception(RuntimeError(f"CONNACK rc={rc}"))
                )

        def _on_message(_c, _u, msg):
            try:
                protocol, seq, inner = unpack_envelope(
                    msg.payload, local_key=self.local_key
                )
            except Exception:
                return  # heartbeats, status messages, etc — not for us
            if protocol != 302:
                return
            self._dispatch(inner)

        client.on_connect = _on_connect
        client.on_message = _on_message
        client.connect_async(self.config.host, self.config.port, keepalive=60)
        client.loop_start()
        self._client = client
        await ready

    def _dispatch(self, inner: dict) -> None:
        header = inner.get("header", {})
        msg = inner.get("msg", {})
        t = header.get("type")
        if t == "answer" and self._on_answer and "sdp" in msg:
            self._on_answer(msg["sdp"])
        elif t == "candidate" and self._on_remote_candidate and "candidate" in msg:
            self._on_remote_candidate(msg["candidate"])

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    async def _publish(self, inner: dict) -> None:
        assert self._client is not None, "connect() first"
        packet = pack_envelope(
            inner, protocol=302, local_key=self.local_key,
            seq=self._next_seq(),
        )
        info = self._client.publish(
            self.config.publish_topic(self.dev_id), packet, qos=1,
        )
        info.wait_for_publish(timeout=5)

    async def publish_offer(self, envelope: dict) -> None:
        await self._publish(envelope)

    async def publish_candidate(self, envelope: dict) -> None:
        await self._publish(envelope)

    async def close(self) -> None:
        if self._client is not None:
            self._client.loop_stop()
            self._client.disconnect()
            self._client = None
