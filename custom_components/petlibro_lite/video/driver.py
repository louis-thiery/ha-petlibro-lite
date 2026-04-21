"""End-to-end HEVC streaming driver for the PetLibro PLAF203.

Reusable async function that accepts explicit params and a sink callback
for Annex-B NAL bytes, with no env vars, no stdout, no file I/O.

Pipeline:

  1. `smartlife.m.rtc.session.offer` HTTPS → STUN/TURN pool + sessionId.
  2. MQTT connect to `m1.tuyaus.com:8883`, subscribe `smart/mb/in/{devId}`.
  3. Publish `offer` JSON wrapped with devices localKey; collect `answer`
     + candidate 302 messages.
  4. aioice.Connection against the STUN/TURN pool; publish local candidates.
  5. Attach a 20-byte HMAC-SHA1 trailer to every UDP packet (key = SDP
     `a=aes-key`).
  6. Multi-conv KCP demux: conv=0 signaling, conv=0x010000f3 signaling,
     conv=1 video, conv=2 audio.
  7. Publish `activate`, then send the 6-message binary stream-start batch
     on conv=0 (AUTH/POST_AUTH/CAPABILITY/3×STREAM_SUB) CBC-encrypted with
     `session.aes_key`.
  8. Drain conv=1: CBC-decrypt, parse Tuya frame header (44B for flags=0x08,
     36B otherwise), strip `00 00 00 0a` body prefix, HEVC FU reassemble,
     emit Annex-B NALs to the `sink` callback.
"""

from __future__ import annotations

import asyncio
import hashlib as _hashlib
import hmac as _hmac
import logging
import re
import secrets as _secrets
import ssl
import struct as _s
from dataclasses import dataclass
from typing import Awaitable, Callable

import paho.mqtt.client as mqtt

from ..cloud import TuyaApiClient
from ..cloud.crypto import CH_KEY_SALT
from .kcp_transport import KcpTransport
from .media_framing import decrypt_cbc_payload, encrypt_cbc_payload
from .session import (
    TuyaRtcSession,
    build_offer_envelope,
    build_offer_sdp,
    new_local_credentials,
    parse_offer_response,
)
from .signaling import (
    mqtt_client_id,
    mqtt_password,
    mqtt_username,
    pack_envelope,
    unpack_envelope,
)
from .stream_control import build_stream_start_batch

_LOGGER = logging.getLogger(__name__)

START_CODE = b"\x00\x00\x00\x01"
BODY_PREFIX = b"\x00\x00\x00\x0a"

_SDP_UFRAG = re.compile(r"a=ice-ufrag:(\S+)")
_SDP_PWD = re.compile(r"a=ice-pwd:(\S+)")
_SDP_AES = re.compile(r"a=aes-key:([0-9a-fA-F]+)")


@dataclass
class StreamParams:
    """Inputs for a single streaming session."""

    sid: str
    ecode: str
    uid: str
    dev_id: str
    local_key: bytes  # 16-byte ASCII-in-bytes Tuya localKey
    admin_user: str
    admin_hash: str
    partner: str = "p1375801"
    mqtt_host: str = "m1.tuyaus.com"
    offer_path: str = "mqtt"
    answer_timeout: float = 15.0
    ice_timeout: float = 30.0
    activate_timeout: float = 10.0
    first_frame_timeout: float = 15.0


NalSink = Callable[[bytes], Awaitable[None]]
PhaseCallback = Callable[[str], None]

# Lifecycle phases the driver reports via `on_phase`. Consumers (the stream
# manager, camera entity attributes, cards) use these to render a nice
# "connecting…" loader while the handshake runs. Matches what the PetLibro
# Lite app shows during its own ~5-10s cold start.
PHASE_SIGNALING = "signaling"    # rtc.session.offer + MQTT connect + offer/answer
PHASE_ICE = "ice"                # ICE candidate gather + connectivity check
PHASE_AUTH = "auth"              # activate + conv=0 AUTH/stream-start batch
PHASE_WAITING_FRAME = "waiting_frame"  # handshake done; waiting for first HEVC NAL
PHASE_STREAMING = "streaming"    # first frame emitted; stream is live
PHASE_ERROR = "error"            # handshake or driver failed


def _build_offer_inner(cfg, uid: str, dev_id: str, offer_path: str) -> dict:
    return {
        "header": {
            "from": uid,
            "is_pre": 0,
            "moto_id": "",
            "p2p_skill": 99,
            "path": offer_path,
            "security_level": 3,
            "sessionid": cfg.session_id,
            "to": dev_id,
            "trace_id": "",
            "type": "offer",
        },
        "msg": {
            "log": cfg.log_endpoint or {},
            "sdp": build_offer_sdp(cfg),
            "tcp_token": cfg.tcp_relay or {},
            "token": cfg.ices or [],
        },
    }


def _build_candidate_inner(
    uid: str, dev_id: str, session_id: str, candidate_sdp: str, offer_path: str,
) -> dict:
    return {
        "header": {
            "from": uid,
            "moto_id": "",
            "path": offer_path,
            "sessionid": session_id,
            "to": dev_id,
            "trace_id": "",
            "type": "candidate",
        },
        "msg": {"candidate": candidate_sdp},
    }


def _build_activate_inner(uid: str, dev_id: str, session_id: str, offer_path: str) -> dict:
    return {
        "header": {
            "from": uid,
            "moto_id": "",
            "path": offer_path,
            "sessionid": session_id,
            "to": dev_id,
            "trace_id": "",
            "type": "activate",
        },
        "msg": {"handle": 1, "seq": 1},
    }


def _parse_answer_sdp(sdp: str) -> tuple[str, str, bytes | None]:
    u = _SDP_UFRAG.search(sdp)
    p = _SDP_PWD.search(sdp)
    a = _SDP_AES.search(sdp)
    if not u or not p:
        raise ValueError("answer SDP missing ufrag/pwd")
    aes = bytes.fromhex(a.group(1)) if a else None
    return u.group(1), p.group(1), aes


class StreamError(RuntimeError):
    """Any non-recoverable failure during handshake or streaming."""


async def run_stream(
    params: StreamParams,
    sink: NalSink,
    stop_event: asyncio.Event,
    on_phase: PhaseCallback | None = None,
) -> None:
    """Run the full stream loop until `stop_event` is set or an error raises.

    `sink` is awaited once per emitted NAL with the Annex-B framed bytes
    (already prefixed by `\\x00\\x00\\x00\\x01`).

    `on_phase` is fired synchronously at each lifecycle transition with
    one of the PHASE_* strings — consumers use it to render "connecting"
    overlays while the ~5-10s handshake runs.
    """

    def _phase(p: str) -> None:
        if on_phase is not None:
            try:
                on_phase(p)
            except Exception:  # noqa: BLE001
                _LOGGER.debug("on_phase callback raised", exc_info=True)

    if len(params.local_key) != 16:
        _phase(PHASE_ERROR)
        raise StreamError(f"local_key must be 16 bytes, got {len(params.local_key)}")

    _phase(PHASE_SIGNALING)
    # ---- Phase-1 HTTPS: rtc.session.offer ----
    client = TuyaApiClient(sid=params.sid, ecode=params.ecode)
    pre_cfg = new_local_credentials(params.dev_id, params.uid)
    env = build_offer_envelope(pre_cfg)
    resp = await asyncio.to_thread(client.rtc_session_offer, params.dev_id, env)
    if not resp.get("success"):
        raise StreamError(
            f"rtc.session.offer failed: {resp.get('errorCode')} {resp.get('errorMsg')}"
        )
    cfg = parse_offer_response(resp)
    cfg.ice_ufrag = pre_cfg.ice_ufrag
    cfg.ice_pwd = pre_cfg.ice_pwd
    _LOGGER.debug(
        "rtc.session.offer ok: sid=%s ices=%d aes=%s",
        cfg.session_id, len(cfg.ices or []), cfg.aes_key.hex(),
    )

    # ---- MQTT connect + subscribe ----
    client_id = mqtt_client_id("com.dl.petlibro", _secrets.token_hex(8), params.uid)
    mqtt_salt = params.ecode or CH_KEY_SALT
    username = mqtt_username(params.partner, params.sid, mqtt_salt)
    password = mqtt_password(salt=mqtt_salt)

    loop = asyncio.get_running_loop()
    connected: asyncio.Future[int] = loop.create_future()
    answer_received: asyncio.Future[dict] = loop.create_future()
    activate_resp_received: asyncio.Future[dict] = loop.create_future()
    remote_candidates: list[dict] = []
    remote_candidate_event = asyncio.Event()

    def on_connect(_c, _u, _f, rc):
        if not connected.done():
            loop.call_soon_threadsafe(
                lambda: connected.set_result(rc) if not connected.done() else None
            )

    def on_message(_c, _u, msg):
        try:
            proto, _seq, inner = unpack_envelope(msg.payload, local_key=params.local_key)
        except Exception:
            return
        if proto != 302:
            return
        t = inner.get("header", {}).get("type")
        if t == "answer" and not answer_received.done():
            loop.call_soon_threadsafe(
                lambda: answer_received.set_result(inner) if not answer_received.done() else None
            )
        elif t == "candidate":
            remote_candidates.append(inner)
            loop.call_soon_threadsafe(remote_candidate_event.set)
        elif t == "activate_resp" and not activate_resp_received.done():
            loop.call_soon_threadsafe(
                lambda: activate_resp_received.set_result(inner) if not activate_resp_received.done() else None
            )

    c = mqtt.Client(client_id=client_id, clean_session=True)
    c.username_pw_set(username, password)
    # `ssl.create_default_context()` reads cert files from disk; offload to a
    # thread so we don't trip HA's blocking-call detector.
    ssl_ctx = await asyncio.to_thread(ssl.create_default_context)
    c.tls_set_context(ssl_ctx)
    c.on_connect = on_connect
    c.on_message = on_message
    c.connect_async(params.mqtt_host, 8883, keepalive=60)
    c.loop_start()

    agent: TuyaRtcSession | None = None
    try:
        rc = await asyncio.wait_for(connected, timeout=10)
        if rc != 0:
            raise StreamError(f"MQTT CONNACK rc={rc}")
        c.subscribe(f"smart/mb/in/{params.dev_id}", qos=1)

        # ---- publish offer ----
        inner = _build_offer_inner(cfg, params.uid, params.dev_id, params.offer_path)
        packet = pack_envelope(inner, protocol=302, local_key=params.local_key, seq=1)
        info = c.publish(f"smart/mb/out/{params.dev_id}", packet, qos=1)
        await asyncio.to_thread(info.wait_for_publish, 5)

        # ---- wait for answer ----
        try:
            answer = await asyncio.wait_for(answer_received, timeout=params.answer_timeout)
        except asyncio.TimeoutError as e:
            raise StreamError("no answer received") from e
        remote_sdp = answer["msg"]["sdp"]
        remote_ufrag, remote_pwd, _remote_aes = _parse_answer_sdp(remote_sdp)

        _phase(PHASE_ICE)
        # ---- aioice agent ----
        agent = TuyaRtcSession(cfg)
        await agent.set_remote_credentials(remote_ufrag, remote_pwd)
        local_candidates = await agent.gather_candidates()
        seq = 2
        for cand_line in local_candidates:
            cand_inner = _build_candidate_inner(
                params.uid, params.dev_id, cfg.session_id,
                cand_line.rstrip("\r\n"), params.offer_path,
            )
            pkt = pack_envelope(cand_inner, protocol=302, local_key=params.local_key, seq=seq)
            info = c.publish(f"smart/mb/out/{params.dev_id}", pkt, qos=1)
            await asyncio.to_thread(info.wait_for_publish, 5)
            seq += 1

        try:
            await asyncio.wait_for(remote_candidate_event.wait(), timeout=5)
        except asyncio.TimeoutError:
            pass
        for cand_line in re.findall(r"a=candidate:[^\r\n]+", remote_sdp):
            remote_candidates.append({"msg": {"candidate": cand_line}})

        for rc_msg in remote_candidates:
            cand_sdp = rc_msg["msg"]["candidate"]
            try:
                await agent.add_remote_candidate(cand_sdp)
            except Exception as e:
                _LOGGER.debug("skipped candidate %s: %s", cand_sdp[:40], e)

        # ---- ICE connect ----
        try:
            await asyncio.wait_for(agent.connect(), timeout=params.ice_timeout)
        except asyncio.TimeoutError as e:
            raise StreamError("ICE did not complete in time") from e
        _LOGGER.info("ICE connected for dev_id=%s", params.dev_id[:12])

        # ---- HMAC-SHA1 trailer wrap on send, strip on recv ----
        hmac_key = cfg.aes_key
        _orig_send = agent.agent.send
        _orig_recv = agent.agent.recv

        async def _send_with_trailer(data: bytes) -> None:
            tag = _hmac.new(hmac_key, data, _hashlib.sha1).digest()
            await _orig_send(data + tag)

        async def _recv_strip_trailer() -> bytes:
            data = await _orig_recv()
            return data[:-20] if len(data) >= 20 else data

        agent.agent.send = _send_with_trailer  # type: ignore
        agent.agent.recv = _recv_strip_trailer  # type: ignore

        # ---- Multi-conv KCP demux ----
        kcp_bin = KcpTransport(agent, conv_id=0, send_window=512, recv_window=512)
        kcp_sig = KcpTransport(agent, conv_id=0x010000f3, send_window=128, recv_window=128)
        kcp_vid = KcpTransport(agent, conv_id=1, send_window=512, recv_window=512)
        kcp_aud = KcpTransport(agent, conv_id=2, send_window=128, recv_window=128)

        bin_rx_q: asyncio.Queue[bytes] = asyncio.Queue()
        sig_rx_q: asyncio.Queue[bytes] = asyncio.Queue()
        vid_rx_q: asyncio.Queue[bytes] = asyncio.Queue()
        aud_rx_q: asyncio.Queue[bytes] = asyncio.Queue()

        class _ConvRouter:
            def __init__(self, rx_q):
                self._q = rx_q
            async def recv(self):
                return await self._q.get()
            async def send(self, data):
                await agent.agent.send(data)  # type: ignore[union-attr]

        class _WrappedAgent:
            def __init__(self, rx_q):
                self.agent = _ConvRouter(rx_q)

        kcp_bin._agent = _WrappedAgent(bin_rx_q)
        kcp_sig._agent = _WrappedAgent(sig_rx_q)
        kcp_vid._agent = _WrappedAgent(vid_rx_q)
        kcp_aud._agent = _WrappedAgent(aud_rx_q)

        await kcp_bin.start()
        await kcp_sig.start()
        await kcp_vid.start()
        await kcp_aud.start()

        async def dispatcher():
            while True:
                try:
                    data = await agent.agent.recv()  # type: ignore[union-attr]
                except asyncio.CancelledError:
                    return
                except Exception:
                    await asyncio.sleep(0.01)
                    continue
                if len(data) < 24:
                    continue
                conv = _s.unpack_from("<I", data, 0)[0]
                if conv == 0:
                    await bin_rx_q.put(data)
                elif conv == 0x010000f3:
                    await sig_rx_q.put(data)
                elif conv == 1:
                    await vid_rx_q.put(data)
                elif conv == 2:
                    await aud_rx_q.put(data)

        dispatcher_task = loop.create_task(dispatcher(), name="petlibro-udp-dispatch")

        _phase(PHASE_AUTH)
        # ---- activate ----
        activate_inner = _build_activate_inner(
            params.uid, params.dev_id, cfg.session_id, params.offer_path,
        )
        act_pkt = pack_envelope(
            activate_inner, protocol=302, local_key=params.local_key, seq=seq,
        )
        info = c.publish(f"smart/mb/out/{params.dev_id}", act_pkt, qos=1)
        await asyncio.to_thread(info.wait_for_publish, 5)
        _LOGGER.info("published activate for dev_id=%s", params.dev_id[:12])
        try:
            act = await asyncio.wait_for(
                activate_resp_received, timeout=params.activate_timeout,
            )
            _LOGGER.info("activate_resp received: %s", act.get("msg"))
        except asyncio.TimeoutError:
            _LOGGER.warning(
                "no activate_resp in %ss; proceeding anyway", params.activate_timeout,
            )

        # ---- Binary CBC key: session.aesKey (camelCase) hex-decoded —
        # the SDP `a=aes-key` value. Some rtc.session.offer responses
        # include a separate `session.aes_key` (underscore, 16B ASCII)
        # but the feeder's app-layer AUTH handler is consistent with
        # `aesKey`, not the underscore variant.
        sess = resp.get("result", {}).get("p2pConfig", {}).get("session", {})
        aes_key_us = sess.get("aes_key")
        bin_aes_key = cfg.aes_key  # always use camelCase

        # ---- Send the 6-message stream-start batch ----
        batch = build_stream_start_batch(params.admin_user, params.admin_hash)
        for pt in batch:
            iv = _secrets.token_bytes(16)
            payload = encrypt_cbc_payload(pt, bin_aes_key, iv)
            await kcp_bin.send(payload)
        _LOGGER.info("stream-start batch sent for dev_id=%s", params.dev_id[:12])

        _phase(PHASE_WAITING_FRAME)
        # Wrap the consumer's sink so the FIRST NAL that flows promotes the
        # phase to `streaming` — that's the signal cards use to drop the
        # loading overlay and show live video.
        first_frame_event = asyncio.Event()

        async def _tracking_sink(nal: bytes) -> None:
            await sink(nal)
            if not first_frame_event.is_set():
                first_frame_event.set()
                _phase(PHASE_STREAMING)

        # ---- Drain video conv=1 until stop_event ----
        video_task = loop.create_task(
            _drain_video(kcp_vid, bin_aes_key, _tracking_sink, stop_event),
            name="petlibro-drain-video",
        )
        # Also drain conv=0 responses and conv=2 audio so they don't back up
        # KCP's recv window (we don't do anything with the bytes for now).
        bin_drain_task = loop.create_task(
            _drain_discard(kcp_bin, stop_event), name="petlibro-drain-bin",
        )
        aud_drain_task = loop.create_task(
            _drain_discard(kcp_aud, stop_event), name="petlibro-drain-aud",
        )

        # First-frame watchdog: if the feeder never sends conv=1 frames in
        # `first_frame_timeout` seconds despite a clean AUTH exchange, treat
        # it as a handshake stall. The stream manager's retry loop catches
        # the StreamError and re-attempts the whole handshake — matches the
        # PetLibro app's behavior when an auth handshake occasionally
        # succeeds at KCP level but the feeder drops the app-layer session.
        try:
            await asyncio.wait_for(
                first_frame_event.wait(), timeout=params.first_frame_timeout,
            )
        except asyncio.TimeoutError as e:
            for t in (video_task, bin_drain_task, aud_drain_task, dispatcher_task):
                t.cancel()
            raise StreamError(
                f"no video frame within {params.first_frame_timeout}s of AUTH",
            ) from e

        try:
            await stop_event.wait()
        finally:
            for t in (video_task, bin_drain_task, aud_drain_task, dispatcher_task):
                t.cancel()
            for t in (video_task, bin_drain_task, aud_drain_task, dispatcher_task):
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
            await kcp_bin.close()
            await kcp_sig.close()
            await kcp_vid.close()
            await kcp_aud.close()
    finally:
        if agent is not None:
            try:
                await agent.close()
            except Exception:
                pass
        try:
            c.loop_stop()
            c.disconnect()
        except Exception:
            pass


async def _drain_discard(kcp, stop_event: asyncio.Event) -> None:
    """Consume and throw away packets from a KCP transport until stopped."""
    while not stop_event.is_set():
        try:
            await kcp.recv()
        except asyncio.CancelledError:
            return
        except Exception:
            await asyncio.sleep(0.05)


async def _drain_video(
    kcp_vid,
    bin_aes_key: bytes,
    sink: NalSink,
    stop_event: asyncio.Event,
) -> None:
    """Decrypt conv=1 packets, reassemble HEVC FUs, push Annex-B NALs to sink.

    Wire format:
      • Each packet is IV(16) + CBC(bin_aes_key, plaintext).
      • Plaintext = [header][body]. Header is 44B when flags (u32@offset 16)
        is 0x08 (keyframes/param sets), 36B otherwise (P-frames).
      • Body starts with the fixed 4B marker `00 00 00 0a`, then raw HEVC
        NAL bytes. NAL type 49 = HEVC Fragmentation Unit, reassembled here;
        all other types are emitted directly.
      • IDR FU pairs occasionally split payloads across a (1328B-large,
        16B-small) pair; the small packet decrypts to a single byte that is
        real FU tail data and must be concatenated.
    """
    fu_buf = bytearray()
    while not stop_event.is_set():
        try:
            payload = await kcp_vid.recv()
        except asyncio.CancelledError:
            return
        except Exception as e:
            _LOGGER.debug("kcp_vid.recv err: %s", e)
            await asyncio.sleep(0.05)
            continue
        try:
            pt = decrypt_cbc_payload(payload, bin_aes_key)
        except Exception as e:
            _LOGGER.debug("conv=1 decrypt err: %s", e)
            continue

        # 1-byte tail of a split FU payload — append to in-flight FU.
        if len(pt) == 1 and fu_buf:
            fu_buf.extend(pt)
            continue
        if len(pt) < 40:
            continue

        flags = _s.unpack_from("<I", pt, 16)[0]
        hdr_len = 44 if flags == 0x08 else 36
        if len(pt) < hdr_len + 5:
            continue
        body = pt[hdr_len:]
        if body[:4] != BODY_PREFIX:
            continue
        nal = body[4:]
        if not nal:
            continue

        nal_type = (nal[0] >> 1) & 0x3F
        if nal_type == 49 and len(nal) >= 3:
            fu_hdr = nal[2]
            s_bit = fu_hdr & 0x80
            e_bit = fu_hdr & 0x40
            fu_type = fu_hdr & 0x3F
            if s_bit:
                b0 = (nal[0] & 0x81) | (fu_type << 1)
                b1 = nal[1]
                fu_buf = bytearray([b0, b1]) + nal[3:]
            elif fu_buf:
                fu_buf.extend(nal[3:])
            if e_bit and fu_buf:
                await sink(START_CODE + bytes(fu_buf))
                fu_buf = bytearray()
        else:
            await sink(START_CODE + nal)
