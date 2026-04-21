"""TLV + KCP framing for the post-handshake media stream.

After the cowboy handshake completes (`handshake.py` / `tcp_relay.py`),
the same TCP connection carries three kinds of frames:

| TLV id | Purpose                                              |
| ------ | ---------------------------------------------------- |
| 0xF400 | Handshake only; not emitted once we're past state=2. |
| 0xF500 | Keepalive ping. Empty body (total = 4 bytes).        |
| 0xF600 | Data. attr type 7 = one KCP segment (standard        |
|        | skywind3000/kcp.c wire format).                      |

This module packs/unpacks those three frames and exposes a small
`KcpSegment` helper. Actual KCP reassembly lives in
`kcp_transport.py`.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass


TLV_ID_HANDSHAKE = 0xF400
TLV_ID_KEEPALIVE = 0xF500
TLV_ID_DATA      = 0xF600

ATTR_PAYLOAD = 7  # same attr type the handshake uses for its ciphertext

# conv_id the PetLibro app uses for post-handshake KCP streams.
# Multiple conv_ids multiplex over the SAME TCP tunnel — each logical
# stream has its own. Discovered 2026-04-20 via Frida `ikcp_input` hook
# while the app live-viewed:
#
#   conv 0x0        — binary stream-control opcodes (AUTH/CAPABILITY/SUBs)
#   conv 0x1        — video stream (H.264)
#   conv 0x2        — audio stream
#   conv 0x010000F3 — signaling channel (JSON SDP offers / candidates)
#
# The app sends binary AUTH on conv 0x0, NOT on 0x010000F3 — sending on
# the wrong conv is why the feeder silently ignored our earlier smoke.
KCP_CONV_SIGNALING = 0x010000F3
KCP_CONV_CONTROL   = 0x00000000
KCP_CONV_VIDEO     = 0x00000001
KCP_CONV_AUDIO     = 0x00000002

# Back-compat alias — signaling was the first conv we identified.
KCP_CONV_MEDIA = KCP_CONV_SIGNALING

# KCP command codes (skywind3000/kcp.c, unchanged in Tuya's build).
KCP_CMD_PUSH = 0x51
KCP_CMD_ACK  = 0x52
KCP_CMD_WASK = 0x53
KCP_CMD_WINS = 0x54


def _pad4(n: int) -> int:
    r = n % 4
    return 0 if r == 0 else 4 - r


@dataclass
class KcpSegment:
    """A single KCP packet as emitted by ikcp_flush / parsed by ikcp_input.

    Header layout is fixed 24 bytes, all multi-byte fields are little-
    endian (standard skywind3000/kcp.c).
    """

    conv: int
    cmd: int
    frg: int
    wnd: int
    ts: int
    sn: int
    una: int
    data: bytes

    def encode(self) -> bytes:
        hdr = struct.pack(
            "<IBBHIIII",
            self.conv, self.cmd, self.frg, self.wnd,
            self.ts, self.sn, self.una, len(self.data),
        )
        return hdr + self.data

    @classmethod
    def decode(cls, buf: bytes) -> "KcpSegment":
        if len(buf) < 24:
            raise ValueError(f"kcp segment too short: {len(buf)}B")
        conv, cmd, frg, wnd, ts, sn, una, plen = struct.unpack("<IBBHIIII", buf[:24])
        if 24 + plen > len(buf):
            raise ValueError(
                f"kcp segment plen={plen} overflows buffer len={len(buf)-24}"
            )
        return cls(conv, cmd, frg, wnd, ts, sn, una, bytes(buf[24:24 + plen]))


def encode_keepalive() -> bytes:
    """A zero-body 0xF500 frame — 4 bytes on the wire."""
    return struct.pack(">HH", TLV_ID_KEEPALIVE, 0)


def encode_data_frame(segment: KcpSegment) -> bytes:
    """Wrap a KCP segment in a TLV 0xF600 frame with a single attr 7."""
    seg_bytes = segment.encode()
    # Single attribute, value = the whole KCP segment. attr header +
    # value + 4-byte align padding.
    attr_hdr = struct.pack(">HH", ATTR_PAYLOAD, len(seg_bytes))
    pad = b"\x00" * _pad4(len(seg_bytes))
    body = attr_hdr + seg_bytes + pad
    # body_len field = length of the body only (not including the 4B
    # TLV header). Same convention as handshake frames.
    hdr = struct.pack(">HH", TLV_ID_DATA, len(body))
    return hdr + body


def decode_data_frame(frame: bytes) -> KcpSegment:
    """Pull the KCP segment out of a TLV 0xF600 frame.

    Raises ValueError if the frame isn't a 0xF600 or doesn't contain
    exactly one attr-7 payload that parses as a KCP segment.
    """
    if len(frame) < 4:
        raise ValueError("frame too short for TLV header")
    tlv_id, body_len = struct.unpack(">HH", frame[:4])
    if tlv_id != TLV_ID_DATA:
        raise ValueError(f"expected TLV 0xF600, got 0x{tlv_id:04x}")
    frame_end = 4 + body_len
    if frame_end > len(frame):
        raise ValueError(f"body_len={body_len} overflows frame len={len(frame)}")
    pos = 4
    while pos + 4 <= frame_end:
        at, al = struct.unpack(">HH", frame[pos:pos+4])
        val = frame[pos+4:pos+4+al]
        if at == ATTR_PAYLOAD:
            return KcpSegment.decode(val)
        pos += 4 + al + _pad4(al)
    raise ValueError("no attr 7 (payload) found in 0xF600 frame")


def frame_tlv_id(frame: bytes) -> int:
    """Peek at the TLV id of a fully-framed buffer."""
    if len(frame) < 2:
        raise ValueError("frame too short")
    return int.from_bytes(frame[:2], "big")


# ----------------------- Signaling-over-KCP -----------------------
#
# Inside a 0xF600 data frame's KCP payload the app carries:
#
#     [u16 BE type=0x0001][u16 BE body_len] + body
#
# body is JSON (the offer / candidate / disconnect / etc. messages
# already built by `signaling.build_offer_message` and friends),
# PKCS7-padded to a 16-byte boundary and AES-128-CBC encrypted with
# the SDP `a=aes-key` value. The 16-byte IV is prepended to the
# ciphertext, so the on-wire KCP payload is:
#
#     [16B IV] + CBC_encrypt(inner, sdp_aes_key, IV)
#
# where `inner = [0x00 0x01 body_len] + pkcs7_pad(json_bytes)`.
#
# Confirmed 2026-04-20 by comparing Frida `mbedtls_aes_crypt_cbc`
# captures (plaintext with `\x00\x01<u16>` prefix, random 16B IV)
# against the outbound KCP payload lengths in the host-side tcpdump.

SIGNALING_TYPE_NORMAL = 0x0001


def wrap_signaling(body_json: bytes) -> bytes:
    """Build the pre-encryption `[type][len][body]` frame.

    `body_json` is the UTF-8-encoded JSON string we want to send
    (output of `json.dumps(build_offer_message(...))` or similar).
    """
    if len(body_json) > 0xFFFF:
        raise ValueError(f"signaling body too large: {len(body_json)}")
    return struct.pack(">HH", SIGNALING_TYPE_NORMAL, len(body_json)) + body_json


def unwrap_signaling(frame: bytes) -> bytes:
    """Reverse of `wrap_signaling`. Returns the raw JSON bytes."""
    if len(frame) < 4:
        raise ValueError("signaling frame too short")
    type_id, body_len = struct.unpack(">HH", frame[:4])
    if type_id != SIGNALING_TYPE_NORMAL:
        raise ValueError(f"unexpected signaling type: 0x{type_id:04x}")
    if 4 + body_len > len(frame):
        raise ValueError(
            f"signaling body_len={body_len} overflows frame len={len(frame)}"
        )
    return frame[4:4 + body_len]


def _pkcs7_pad(data: bytes, block: int = 16) -> bytes:
    pad = block - (len(data) % block)
    return data + bytes([pad]) * pad


def _pkcs7_unpad(data: bytes) -> bytes:
    if not data:
        raise ValueError("empty buffer for unpadding")
    pad = data[-1]
    if pad < 1 or pad > 16 or data[-pad:] != bytes([pad]) * pad:
        raise ValueError(f"bad PKCS7 padding (byte={pad})")
    return data[:-pad]


def encrypt_cbc_payload(
    plaintext: bytes, sdp_aes_key: bytes, iv: bytes,
) -> bytes:
    """Generic CBC wrap for the post-handshake KCP tunnel.

    Both signaling JSON and binary stream-control opcodes ride the
    same transport: `iv (16B) || AES-128-CBC(sdp_aes_key, iv, pkcs7(plaintext))`.
    Signaling wraps JSON in `[type=1][len][body]` first; stream-control
    opcodes start directly with the `0x12345678` magic.
    """
    if len(iv) != 16:
        raise ValueError("IV must be 16 bytes")
    if len(sdp_aes_key) != 16:
        raise ValueError("sdp_aes_key must be 16 bytes")
    from Crypto.Cipher import AES  # type: ignore[import-not-found]
    padded = _pkcs7_pad(plaintext)
    ct = AES.new(sdp_aes_key, AES.MODE_CBC, iv).encrypt(padded)
    return iv + ct


def decrypt_cbc_payload(
    kcp_payload: bytes, sdp_aes_key: bytes,
) -> bytes:
    """Inverse of `encrypt_cbc_payload`. Returns raw plaintext."""
    if len(kcp_payload) < 32:
        raise ValueError(
            f"kcp payload too short for IV+ciphertext: {len(kcp_payload)}"
        )
    if len(sdp_aes_key) != 16:
        raise ValueError("sdp_aes_key must be 16 bytes")
    from Crypto.Cipher import AES  # type: ignore[import-not-found]
    iv, ct = kcp_payload[:16], kcp_payload[16:]
    if len(ct) % 16 != 0:
        raise ValueError(f"ciphertext not a multiple of 16: {len(ct)}")
    return _pkcs7_unpad(AES.new(sdp_aes_key, AES.MODE_CBC, iv).decrypt(ct))


def encrypt_signaling_payload(
    json_bytes: bytes, sdp_aes_key: bytes, iv: bytes,
) -> bytes:
    """JSON-signaling variant: wrap in `[0x0001][len][body]` then CBC."""
    return encrypt_cbc_payload(wrap_signaling(json_bytes), sdp_aes_key, iv)


def decrypt_signaling_payload(
    kcp_payload: bytes, sdp_aes_key: bytes,
) -> bytes:
    """Inverse of `encrypt_signaling_payload`. Returns JSON bytes."""
    return unwrap_signaling(decrypt_cbc_payload(kcp_payload, sdp_aes_key))
