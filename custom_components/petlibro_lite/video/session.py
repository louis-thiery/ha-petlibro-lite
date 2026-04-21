"""Parse rtc.session.offer responses + drive the per-session ICE agent.

This is a thin shim on top of `..cloud.api.TuyaApiClient.rtc_session_offer`
that:
  1. turns the server response into a typed `RtcSessionConfig` value,
  2. kicks off an `aioice.Connection` against the returned STUN/TURN pool,
  3. exposes the UDP datagram pipe so higher layers (KCP, SRTP) can layer on.

Signaling — publishing the SDP offer and trickle candidates to the device
over MQTT, and receiving the device's answer + remote candidates — is
still a stub (`signaling.py`). Until that's wired in, ICE won't complete
against the feeder because no candidates are exchanged.
"""
from __future__ import annotations

import asyncio
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

import aioice


@dataclass
class RtcSessionConfig:
    session_id: str
    dev_id: str
    uid: str                            # our uid (from login)
    moto_id: str                        # Tuya signaling-gateway id
    aes_key: bytes                      # 16-byte SRTP master key (hex-decoded, matches server's session.aesKey)
    ice_ufrag: str                      # our ICE ufrag (we chose it in the offer)
    ice_pwd: str                        # our ICE pwd
    ices: list[dict]                    # STUN + TURN servers from the server
    tcp_relay: dict                     # TCP fallback config
    is_low_power: bool
    skill: dict                         # decoded device skill (H.264/H.265 capabilities)
    auth_token: str                     # session auth (for rtc.log telemetry calls)
    log_endpoint: dict                  # telemetry endpoint config
    # Server-minted 16-byte ASCII key (session.aes_key w/ underscore) —
    # DIFFERENT from aesKey. Used as CBC key for conv=0 stream-control
    # binary opcodes. Empty on local-only configs.
    binary_aes_key: bytes = b""
    raw: dict = field(default_factory=dict, repr=False)


def parse_offer_response(response: dict) -> RtcSessionConfig:
    """Decode the raw `rtc_session_offer()` result into a typed config.

    Expects the dict returned by `TuyaApiClient.rtc_session_offer` (i.e.
    the already-decrypted response body with `result` at top-level).
    """
    r = response["result"]
    sess = r["p2pConfig"]["session"]
    skill_raw = r.get("skill", "{}")
    skill = json.loads(skill_raw) if isinstance(skill_raw, str) else skill_raw
    # The session object carries two AES keys:
    #   aesKey   — random 16 bytes, goes in SDP a=aes-key for SRTP/media
    #   aes_key  — 16 ASCII chars (hex-encoded in the field), for conv=0 binary
    # We keep aesKey as .aes_key (existing naming) and expose the underscored
    # variant as .binary_aes_key. Older sessions occasionally set them equal.
    ascii_key_hex = sess.get("aes_key") or ""
    binary_key = bytes.fromhex(ascii_key_hex) if ascii_key_hex else b""
    return RtcSessionConfig(
        session_id=sess["sessionId"],
        dev_id=r["id"],
        uid=sess["uid"],
        moto_id=r["motoId"],
        aes_key=bytes.fromhex(sess["aesKey"]),
        ice_ufrag=sess["iceUfrag"],
        ice_pwd=sess["icePassword"],
        ices=r["p2pConfig"]["ices"],
        tcp_relay=r.get("p2pConfig", {}).get("tcpRelay") or r.get("tcpRelay", {}),
        is_low_power=bool(r.get("isLowPower", False)),
        skill=skill,
        auth_token=r.get("auth", ""),
        log_endpoint=r["p2pConfig"].get("log", {}),
        binary_aes_key=binary_key,
        raw=r,
    )


def build_offer_sdp(cfg: RtcSessionConfig) -> str:
    """Build the SDP offer string that the native code emits.

    Format is specific to Tuya's `imm` protocol — not standard
    webrtc-ish SDP. See video_re_findings.md for the capture.
    """
    return (
        "v=0\r\n"
        f"o=- {int(time.time())} 1 IN IP4 127.0.0.1\r\n"
        "s=-\r\n"
        "t=0 0\r\n"
        "a=group:BUNDLE imm0\r\n"
        f"a=msid-semantic: WMS {cfg.session_id}\r\n"
        "m=application 9 imm 6001\r\n"
        "c=IN IP4 0.0.0.0\r\n"
        "a=rtcp:9 IN IP4 0.0.0.0\r\n"
        f"a=ice-ufrag:{cfg.ice_ufrag}\r\n"
        f"a=ice-pwd:{cfg.ice_pwd}\r\n"
        "a=ice-options:trickle\r\n"
        f"a=aes-key:{cfg.aes_key.hex()}\r\n"
        "a=mid:imm0\r\n"
        "a=rtpmap:6001 AES/KCP 330\r\n"
        f"a=ssrc:0 cname:{cfg.uid}\r\n"
    )


def build_offer_envelope(cfg: RtcSessionConfig, *, is_pre: bool = True) -> dict:
    """Build the outer envelope that rtc.session.offer expects.

    We generate a fresh session_id, ice_ufrag/pwd, and aes_key; the
    server-side provisions a new session tied to these.
    """
    return {
        "header": {
            "from": cfg.uid,
            "to": cfg.dev_id,
            "sessionid": cfg.session_id,
            "moto_id": "",
            "type": "offer",
            "trace_id": "",
            "is_pre": 1 if is_pre else 0,
            "p2p_skill": 99,
        },
        "msg": {"sdp": build_offer_sdp(cfg)},
    }


# ice-char alphabet per RFC 5245 §15.1 — ALPHA / DIGIT (we skip the
# '+' and '/' allowed chars since they can cause SDP parsing issues on
# some implementations). Matches what the feeder itself emits.
_ICE_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"


def _ice_token(n: int) -> str:
    return "".join(secrets.choice(_ICE_CHARS) for _ in range(n))


def new_local_credentials(dev_id: str, uid: str) -> RtcSessionConfig:
    """Generate per-session random local ICE + AES credentials BEFORE calling
    rtc.session.offer. The server will echo them back in its response."""
    session_id = f"{dev_id}{int(time.time())}{_ice_token(10)}"
    return RtcSessionConfig(
        session_id=session_id,
        dev_id=dev_id,
        uid=uid,
        moto_id="",
        aes_key=secrets.token_bytes(16),
        ice_ufrag=_ice_token(4),
        ice_pwd=_ice_token(24),
        ices=[],
        tcp_relay={},
        is_low_power=False,
        skill={},
        auth_token="",
        log_endpoint={},
    )


class TuyaRtcSession:
    """A single live RTC session. Owns an aioice agent and (eventually) the
    KCP+SRTP+RTP stack.

    Current state: can create the agent with the STUN/TURN pool the server
    returns. Does NOT yet complete ICE — that requires MQTT signaling to
    exchange candidates with the device.
    """

    def __init__(self, cfg: RtcSessionConfig) -> None:
        self.cfg = cfg
        stun_server = None
        turn_server = None
        turn_username = None
        turn_password = None
        for ice in cfg.ices:
            url = ice["urls"]
            if url.startswith("stun:") and stun_server is None:
                host, port = url[5:].rsplit(":", 1)
                stun_server = (host, int(port))
            elif url.startswith("turn:") and turn_server is None:
                host, port = url[5:].rsplit(":", 1)
                turn_server = (host, int(port))
                turn_username = ice.get("username")
                turn_password = ice.get("credential")
        import os as _os
        _controlling = _os.environ.get("PETLIBRO_ICE_CONTROLLING", "1") == "1"
        self.agent = aioice.Connection(
            ice_controlling=_controlling,
            stun_server=stun_server,
            turn_server=turn_server,
            turn_username=turn_username,
            turn_password=turn_password,
            local_username=cfg.ice_ufrag,
            local_password=cfg.ice_pwd,
        )

    async def gather_candidates(self) -> list[str]:
        """Gather local ICE candidates. Returns them as SDP-a= candidate lines
        ready to trickle to the device via MQTT."""
        await self.agent.gather_candidates()
        return [
            f"a=candidate:{c.foundation} {c.component} {c.transport} {c.priority} "
            f"{c.host} {c.port} typ {c.type}\r\n"
            for c in self.agent.local_candidates
        ]

    async def add_remote_candidate(self, candidate_sdp: str) -> None:
        """Feed a remote candidate received via MQTT signaling."""
        c = aioice.Candidate.from_sdp(candidate_sdp.rstrip("\r\n").removeprefix("a="))
        await self.agent.add_remote_candidate(c)

    async def set_remote_credentials(self, ufrag: str, pwd: str) -> None:
        """Tell our agent what ufrag/pwd to use in outgoing STUN checks."""
        self.agent.remote_username = ufrag
        self.agent.remote_password = pwd

    async def connect(self) -> None:
        await self.agent.connect()

    async def close(self) -> None:
        await self.agent.close()
