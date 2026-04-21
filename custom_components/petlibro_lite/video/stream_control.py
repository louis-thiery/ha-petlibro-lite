"""Binary stream-start opcodes that gate video bytes from the feeder.

After the cowboy TCP handshake completes and signaling (SDP offer +
candidate trickle + end-of-candidates) has been exchanged, the
feeder stops responding to JSON messages and expects a short
**binary** handshake inside the same KCP tunnel. Six messages,
each a `0x12345678`-magic opcode + body, each CBC-encrypted with
the same SDP `a=aes-key` used for signaling. The feeder only
starts sending H.264 frames AFTER the full six-message exchange.

Layout of every message (on the wire, plaintext pre-PKCS7):

```
+--------+--------+---- body (opcode-specific) ----+
| magic  | opcode |                                |
| u32 LE | u32 LE |                                |
+--------+--------+--------------------------------+
  4         4         AUTH = 96B, others = 16-20B
```

The **opcode value itself** encodes a session/request tag; the
low 16 bits are a sequential counter (starts at 1 for AUTH on a
fresh session) and the high 16 bits hold a per-session
high-word that is echoed in every opcode of the batch. We treat
opcode base as an input parameter rather than a hard constant.

**Bodies** are the same across sessions — we replay byte-for-byte
the values captured from the live app.

See `findings_handshake.md` — "Binary stream-start protocol FULLY
DECODED" section for the exhaustive capture that produced these.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass


STREAM_MAGIC = 0x12345678  # LE on wire: 78 56 34 12

# Frozen body payloads captured from live app sessions. The fields
# are enum-like (resolution/codec/stream-type flags) and the feeder
# answered positively to these exact values across three separate
# live sessions, so we replay rather than re-interpret.
POST_AUTH_BODY    = struct.pack("<IIII",  0,     10, 4, 0x10000)
CAPABILITY_BODY   = struct.pack("<IIII",  0,      2, 4, 0)
STREAM_SUB_1_BODY = struct.pack("<IIIII", 0,      9, 8, 0, 4)
STREAM_SUB_2_BODY = struct.pack("<IIIII", 0,      6, 8, 0, 0)
# Second field of SUB_3 combines a stream-type tag (0x04 in high u16)
# with the same base value as SUB_2, so 0x00040006 = 262150.
STREAM_SUB_3_BODY = struct.pack("<IIIII", 0, 0x00040006, 8, 0, 4)

# Backwards-compatibility alias — earlier we (mistakenly) called
# POST_AUTH the server's AUTH_ACK. Removing soon.
AUTH_ACK_BODY = POST_AUTH_BODY


@dataclass
class OpcodeSeq:
    """The six opcode ints the app fires for a stream-start batch.

    Opcodes are DYNAMIC per-app-run. On a fresh app launch the counter
    starts at AUTH=0x01 and each subsequent session advances the low
    byte; sub_tag (high u16) starts at 0x0001 and increments per
    session. Observed on a fresh launch (2026-04-20):

    | name        | value      | body | purpose                       |
    | ----------- | ---------- | ---- | ----------------------------- |
    | auth        | 0x00000001 | 96B  | admin + md5_hex               |
    | post_auth   | 0x00000000 | 16B  | always 0 (feeder-initiated?)  |
    | capability  | 0x00000002 | 16B  | capability negotiation        |
    | sub_1       | 0x00010004 | 20B  | stream subscribe group 1      |
    | sub_2       | 0x00010003 | 20B  | stream subscribe group 2      |
    | sub_3       | 0x00010005 | 20B  | stream subscribe group 3      |

    Feeder echoes our opcodes back in ACKs (AUTH_ACK is always opc=0).
    POST_AUTH opcode=0 suggests it's a client-side response to feeder's
    AUTH_ACK rather than a new request — we send opcode=0 to acknowledge
    auth success. Subsequent live views within the same app run bump
    the counter: +6 per session (5 handles + 1 skipped).
    """
    auth: int
    post_auth: int
    capability: int
    sub_1: int
    sub_2: int
    sub_3: int


def make_opcode_seq(
    auth_tag: int = 0x0000, sub_tag: int = 0x0001,
) -> OpcodeSeq:
    """Build the 6 opcode ints for a fresh-session stream-start.

    Defaults mirror the first-session values observed after a cold app
    launch: auth_tag=0x0000, sub_tag=0x0001, low bytes 0x01/0x00/0x02
    for the auth phase and 0x04/0x03/0x05 for the sub phase. Feeder
    echoes the opcode back in each ACK (except AUTH_ACK=0). Override
    via env/args for replayed/subsequent sessions within the same
    app run.
    """
    a = (auth_tag & 0xFFFF) << 16
    s = (sub_tag & 0xFFFF) << 16
    return OpcodeSeq(
        auth=       a | 0x0001,
        post_auth=  a | 0x0000,
        capability= a | 0x0002,
        sub_1=      s | 0x0004,
        sub_2=      s | 0x0003,
        sub_3=      s | 0x0005,
    )


def encode_auth_body(username: str, md5_hex: str) -> bytes:
    """Pack the 96-byte AUTH body.

    `username` is the admin username (factory default is
    `"admin"`); `md5_hex` is the 32-char ASCII-hex representation
    of a 16-byte auth token provisioned per-device on pairing. See
    `findings_handshake.md` for where this value comes from — it's
    a device-level constant, captured once via Frida or memscan,
    stored in `device_credentials.json`.
    """
    if len(username) > 32:
        raise ValueError(f"username too long: {len(username)}B (max 32)")
    if len(md5_hex) != 32 or not all(c in "0123456789abcdefABCDEF" for c in md5_hex):
        raise ValueError(f"md5_hex must be 32 hex chars, got {md5_hex!r}")
    body = bytearray(96)
    body[0:len(username)] = username.encode("ascii")
    body[32:32 + 32] = md5_hex.lower().encode("ascii")
    # bytes 64..96 stay zero (captured reserved field)
    return bytes(body)


def encode_message(opcode: int, body: bytes) -> bytes:
    """Wrap an opcode + body in the `0x12345678` magic framing.

    Output is the *plaintext* that will be PKCS7-padded, CBC-
    encrypted with the SDP AES key, wrapped in a KCP segment, and
    sent as a 0xF600 TLV frame (same path as signaling JSON).
    """
    return struct.pack("<II", STREAM_MAGIC, opcode) + body


def build_stream_start_batch(
    username: str, md5_hex: str, *,
    auth_tag: int = 0x0000, sub_tag: int = 0x0001,
) -> list[bytes]:
    """Return the 6 outbound messages in the order the app sends them.

    AUTH → post_auth (16B zero-ish body) → CAPABILITY → 3× STREAM_SUB.
    After this the feeder opens the media stream and starts pushing
    H.264 frames on the same KCP conv as additional 0xF600 TLVs.
    """
    seq = make_opcode_seq(auth_tag, sub_tag)
    return [
        encode_message(seq.auth,       encode_auth_body(username, md5_hex)),
        encode_message(seq.post_auth,  POST_AUTH_BODY),
        encode_message(seq.capability, CAPABILITY_BODY),
        encode_message(seq.sub_1,      STREAM_SUB_1_BODY),
        encode_message(seq.sub_2,      STREAM_SUB_2_BODY),
        encode_message(seq.sub_3,      STREAM_SUB_3_BODY),
    ]


def parse_message(plaintext: bytes) -> tuple[int, bytes]:
    """Decode an `[0x12345678][opcode][body]` plaintext.

    Returns `(opcode, body)`. Raises `ValueError` on bad magic.
    """
    if len(plaintext) < 8:
        raise ValueError(f"too short: {len(plaintext)}B")
    magic, opcode = struct.unpack("<II", plaintext[:8])
    if magic != STREAM_MAGIC:
        raise ValueError(f"bad magic: 0x{magic:08x} (want 0x{STREAM_MAGIC:08x})")
    return opcode, plaintext[8:]


def is_auth_ack(opcode: int) -> bool:
    """The feeder's ACK to AUTH is always opcode 0x00000000."""
    return opcode == 0
