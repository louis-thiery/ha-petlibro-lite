"""High-level async video stream from a PLAF203 feeder.

Wraps the full stack — cloud rtc.session.offer → MQTT signaling →
ICE → KCP demux + HMAC trailer → CBC decrypt → HEVC reassembly —
behind an `async for nal in stream.frames()` interface. Intended for
consumers that want to pipe NAL units to a local ffmpeg subprocess
(HA camera entity, standalone MP4 recorder, etc.).

Usage:

```python
stream = PetLibroVideoStream(
    sid=<cloud_sid>, uid=<cloud_uid>, dev_id=<device_id>,
    local_key=<16B device local key>, ecode=<account ecode>,
)
async with stream:
    async for annex_b_nal in stream.frames():
        ffmpeg_stdin.write(annex_b_nal)
```

See `smoke_ice.py` for the reference flow this module packages up.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac as _hmac
import json
import os
import re
import secrets as _secrets
import ssl
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

import aioice

from ..cloud import TuyaApiClient
from ..cloud.crypto import CH_KEY_SALT

from .kcp_transport import KcpTransport
from .media_framing import decrypt_cbc_payload, encrypt_cbc_payload
from .session import (
    RtcSessionConfig,
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


START_CODE = b"\x00\x00\x00\x01"


@dataclass
class StreamConfig:
    sid: str                  # cloud session id (Tuya `sid=` URL param)
    uid: str                  # cloud user id
    dev_id: str               # Tuya device id (tinytuya scan / pairing output)
    local_key: bytes          # 16B device local key (from DeviceBean)
    ecode: str                # per-account ecode (16-char)
    admin_user: str = "admin"
    admin_hash: str = ""      # 32-char hex; feeder p2p admin hash
    partner: str = "p1375801"
    mqtt_host: str = "m1.tuyaus.com"
    answer_timeout: float = 15
    ice_timeout: float = 25
    offer_path: str = "mqtt"  # "mqtt" or "lan"


_SDP_UFRAG = re.compile(r"a=ice-ufrag:(\S+)")
_SDP_PWD = re.compile(r"a=ice-pwd:(\S+)")


def _parse_answer_sdp(sdp: str) -> tuple[str, str]:
    u = _SDP_UFRAG.search(sdp)
    p = _SDP_PWD.search(sdp)
    if not u or not p:
        raise ValueError(f"answer SDP missing ufrag/pwd:\n{sdp}")
    return u.group(1), p.group(1)


def _build_offer_inner(cfg: RtcSessionConfig, uid: str, dev_id: str, path: str) -> dict:
    return {
        "header": {
            "from": uid, "is_pre": 0, "moto_id": "",
            "p2p_skill": 99, "path": path, "security_level": 3,
            "sessionid": cfg.session_id, "to": dev_id,
            "trace_id": "", "type": "offer",
        },
        "msg": {
            "log": cfg.log_endpoint or {},
            "sdp": build_offer_sdp(cfg),
            "tcp_token": cfg.tcp_relay or {},
            "token": cfg.ices or [],
        },
    }


def _build_candidate_inner(uid: str, dev_id: str, session_id: str,
                           cand_sdp: str, path: str) -> dict:
    return {
        "header": {
            "from": uid, "moto_id": "", "path": path,
            "sessionid": session_id, "to": dev_id, "trace_id": "",
            "type": "candidate",
        },
        "msg": {"candidate": cand_sdp},
    }


def _build_activate_inner(uid: str, dev_id: str, session_id: str, path: str) -> dict:
    return {
        "header": {
            "from": uid, "moto_id": "", "path": path,
            "sessionid": session_id, "to": dev_id, "trace_id": "",
            "type": "activate",
        },
        "msg": {"handle": 1, "seq": 1},
    }


class PetLibroVideoStream:
    """One live video session from a PLAF203 feeder.

    Use as `async with stream: async for nal in stream.frames(): ...`.
    On enter runs the full handshake; on exit closes everything.
    """

    def __init__(self, cfg: StreamConfig) -> None:
        self.cfg = cfg
        self._mqtt = None
        self._agent: TuyaRtcSession | None = None
        self._rtc_cfg: RtcSessionConfig | None = None
        self._kcp_bin: KcpTransport | None = None
        self._kcp_vid: KcpTransport | None = None
        self._kcp_aud: KcpTransport | None = None
        self._dispatcher_task: asyncio.Task | None = None
        self._closed = False

    async def __aenter__(self) -> "PetLibroVideoStream":
        await self._handshake()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for t in (self._dispatcher_task,):
            if t is not None:
                t.cancel()
        for k in (self._kcp_bin, self._kcp_vid, self._kcp_aud):
            if k is not None:
                try:
                    await k.close()
                except Exception:
                    pass
        if self._agent is not None:
            try:
                await self._agent.close()
            except Exception:
                pass
        if self._mqtt is not None:
            try:
                self._mqtt.loop_stop()
                self._mqtt.disconnect()
            except Exception:
                pass

    async def _handshake(self) -> None:
        cfg = self.cfg
        loop = asyncio.get_running_loop()

        # ---- Phase-1: rtc.session.offer over HTTPS ----
        client = TuyaApiClient(sid=cfg.sid, ecode=cfg.ecode)
        pre_cfg = new_local_credentials(cfg.dev_id, cfg.uid)
        env = build_offer_envelope(pre_cfg)
        resp = client.rtc_session_offer(cfg.dev_id, env)
        if not resp.get("success"):
            raise RuntimeError(f"rtc.session.offer failed: {resp}")
        rtc_cfg = parse_offer_response(resp)
        rtc_cfg.ice_ufrag = pre_cfg.ice_ufrag
        rtc_cfg.ice_pwd = pre_cfg.ice_pwd
        self._rtc_cfg = rtc_cfg

        # ---- MQTT signaling ----
        import paho.mqtt.client as mqtt
        client_id = mqtt_client_id("com.dl.petlibro", os.urandom(8).hex(), cfg.uid)
        mqtt_salt = cfg.ecode or CH_KEY_SALT
        username = mqtt_username(cfg.partner, cfg.sid, mqtt_salt)
        password = mqtt_password(salt=mqtt_salt)

        connected = loop.create_future()
        answer_fut: asyncio.Future[dict] = loop.create_future()
        activate_fut: asyncio.Future[dict] = loop.create_future()
        remote_candidates: list[dict] = []
        cand_event = asyncio.Event()

        def on_connect(_c, _u, _f, rc):
            if not connected.done():
                loop.call_soon_threadsafe(
                    lambda: connected.set_result(rc) if not connected.done() else None)

        def on_message(_c, _u, msg):
            try:
                proto, _, inner = unpack_envelope(msg.payload, local_key=cfg.local_key)
            except Exception:
                return
            if proto != 302:
                return
            t = inner.get("header", {}).get("type")
            if t == "answer" and not answer_fut.done():
                loop.call_soon_threadsafe(
                    lambda: answer_fut.set_result(inner) if not answer_fut.done() else None)
            elif t == "candidate":
                remote_candidates.append(inner)
                loop.call_soon_threadsafe(cand_event.set)
            elif t == "activate_resp" and not activate_fut.done():
                loop.call_soon_threadsafe(
                    lambda: activate_fut.set_result(inner) if not activate_fut.done() else None)

        c = mqtt.Client(client_id=client_id, clean_session=True)
        c.username_pw_set(username, password)
        c.tls_set_context(ssl.create_default_context())
        c.on_connect = on_connect
        c.on_message = on_message
        c.connect_async(cfg.mqtt_host, 8883, keepalive=60)
        c.loop_start()
        self._mqtt = c

        rc = await asyncio.wait_for(connected, timeout=10)
        if rc != 0:
            raise RuntimeError(f"MQTT CONNACK rc={rc}")
        c.subscribe(f"smart/mb/in/{cfg.dev_id}", qos=1)

        # ---- Publish offer ----
        inner = _build_offer_inner(rtc_cfg, cfg.uid, cfg.dev_id, cfg.offer_path)
        packet = pack_envelope(inner, protocol=302, local_key=cfg.local_key, seq=1)
        c.publish(f"smart/mb/out/{cfg.dev_id}", packet, qos=1).wait_for_publish(5)
        seq = 2

        # ---- Answer ----
        answer = await asyncio.wait_for(answer_fut, timeout=cfg.answer_timeout)
        remote_sdp = answer["msg"]["sdp"]
        rem_ufrag, rem_pwd = _parse_answer_sdp(remote_sdp)

        # ---- Gather our ICE + publish, then ingest remote candidates ----
        agent = TuyaRtcSession(rtc_cfg)
        self._agent = agent
        await agent.set_remote_credentials(rem_ufrag, rem_pwd)
        local_cands = await agent.gather_candidates()
        for cl in local_cands:
            ci = _build_candidate_inner(cfg.uid, cfg.dev_id, rtc_cfg.session_id,
                                        cl.rstrip("\r\n"), cfg.offer_path)
            pkt = pack_envelope(ci, protocol=302, local_key=cfg.local_key, seq=seq)
            c.publish(f"smart/mb/out/{cfg.dev_id}", pkt, qos=1).wait_for_publish(5)
            seq += 1

        try:
            await asyncio.wait_for(cand_event.wait(), timeout=5)
        except asyncio.TimeoutError:
            pass
        for cand in re.findall(r"a=candidate:[^\r\n]+", remote_sdp):
            remote_candidates.append({"msg": {"candidate": cand}})
        for rc_msg in remote_candidates:
            cand_sdp = rc_msg["msg"]["candidate"]
            try:
                await agent.add_remote_candidate(cand_sdp)
            except Exception:
                pass

        # ---- ICE connect ----
        await asyncio.wait_for(agent.connect(), timeout=cfg.ice_timeout)

        # ---- Send activate via MQTT (BEFORE any KCP work) ----
        # Feeder must be flipped to "active" session state before it will
        # process binary KCP traffic. Order matches smoke_ice.py.
        act_inner = _build_activate_inner(cfg.uid, cfg.dev_id, rtc_cfg.session_id, cfg.offer_path)
        act_pkt = pack_envelope(act_inner, protocol=302, local_key=cfg.local_key, seq=seq)
        c.publish(f"smart/mb/out/{cfg.dev_id}", act_pkt, qos=1).wait_for_publish(5)
        seq += 1
        await asyncio.wait_for(activate_fut, timeout=10)

        # ---- HMAC trailer wrapping ----
        hmac_key = rtc_cfg.aes_key
        _orig_send = agent.agent.send
        _orig_recv = agent.agent.recv
        _dbg_enabled = os.environ.get("PETLIBRO_STREAM_DEBUG") == "1"
        recv_counter = [0]
        async def _send_with_trailer(data: bytes) -> None:
            tag = _hmac.new(hmac_key, data, hashlib.sha1).digest()
            await _orig_send(data + tag)
        async def _recv_strip_trailer() -> bytes:
            d = await _orig_recv()
            recv_counter[0] += 1
            if _dbg_enabled and recv_counter[0] % 50 == 0:
                print(f"[recv] count={recv_counter[0]} last_len={len(d)}")
            return d[:-20] if len(d) >= 20 else d
        # Bind with the "types" of the originals to match aioice expectations.
        setattr(agent.agent, 'send', _send_with_trailer)
        setattr(agent.agent, 'recv', _recv_strip_trailer)

        # ---- Multi-conv KCP demux ----
        self._bin_rx: asyncio.Queue[bytes] = asyncio.Queue()
        self._vid_rx: asyncio.Queue[bytes] = asyncio.Queue()
        self._aud_rx: asyncio.Queue[bytes] = asyncio.Queue()

        class _Router:
            def __init__(self, q): self._q = q
            async def recv(self): return await self._q.get()
            async def send(self, data): await agent.agent.send(data)

        class _Wrapped:
            def __init__(self, q): self.agent = _Router(q)

        kcp_bin = KcpTransport(agent, conv_id=0, send_window=512, recv_window=512)
        kcp_bin._agent = _Wrapped(self._bin_rx)
        kcp_vid = KcpTransport(agent, conv_id=1, send_window=512, recv_window=512)
        kcp_vid._agent = _Wrapped(self._vid_rx)
        kcp_aud = KcpTransport(agent, conv_id=2, send_window=128, recv_window=128)
        kcp_aud._agent = _Wrapped(self._aud_rx)
        await kcp_bin.start()
        await kcp_vid.start()
        await kcp_aud.start()
        self._kcp_bin, self._kcp_vid, self._kcp_aud = kcp_bin, kcp_vid, kcp_aud

        debug = os.environ.get("PETLIBRO_STREAM_DEBUG") == "1"
        disp_counts = {"total": 0, 0: 0, 1: 0, 2: 0, "other": 0}
        async def dispatcher():
            if debug: print(f"[dispatcher] starting")
            while not self._closed:
                try:
                    data = await agent.agent.recv()
                except asyncio.CancelledError:
                    if debug: print(f"[dispatcher] cancelled")
                    break
                except Exception as e:
                    if debug: print(f"[dispatcher] recv err: {e}")
                    await asyncio.sleep(0.01)
                    continue
                disp_counts["total"] += 1
                if len(data) < 24:
                    continue
                conv = struct.unpack('<I', data[:4])[0]
                if conv == 0:
                    disp_counts[0] += 1
                    await self._bin_rx.put(data)
                elif conv == 1:
                    disp_counts[1] += 1
                    await self._vid_rx.put(data)
                elif conv == 2:
                    disp_counts[2] += 1
                    await self._aud_rx.put(data)
                else:
                    disp_counts["other"] += 1
                if debug and disp_counts["total"] % 50 == 0:
                    print(f"[dispatcher] total={disp_counts['total']} "
                          f"conv0={disp_counts[0]} conv1={disp_counts[1]} "
                          f"conv2={disp_counts[2]} other={disp_counts['other']}")

        self._dispatcher_task = asyncio.get_running_loop().create_task(dispatcher())
        if debug: print(f"[handshake] dispatcher started; ICE pair = "
                        f"{getattr(agent.agent, '_nominated', None)}")

        # ---- Send binary stream-start batch ----
        # Prefer session.aes_key (underscore) for CBC; fall back to aesKey.
        self._bin_aes_key = rtc_cfg.binary_aes_key or rtc_cfg.aes_key
        if debug: print(f"[handshake] bin_aes_key={self._bin_aes_key.hex()[:16]}...")
        batch = build_stream_start_batch(cfg.admin_user, cfg.admin_hash)
        for pt in batch:
            iv = _secrets.token_bytes(16)
            enc = encrypt_cbc_payload(pt, self._bin_aes_key, iv)
            await kcp_bin.send(enc)
        if debug: print(f"[handshake] sent {len(batch)} binary stream-start msgs")

    async def frames(self) -> AsyncIterator[bytes]:
        """Yield Annex-B H.265 NAL units for ffmpeg stdin."""
        assert self._kcp_vid is not None
        fu_buf = bytearray()
        debug = os.environ.get("PETLIBRO_STREAM_DEBUG") == "1"
        count = 0
        while not self._closed:
            try:
                payload = await self._kcp_vid.recv()
            except asyncio.CancelledError:
                return
            except Exception as e:
                if debug: print(f"[stream] recv err: {e}")
                await asyncio.sleep(0.05)
                continue
            try:
                pt = decrypt_cbc_payload(payload, self._bin_aes_key)
            except Exception as e:
                if debug: print(f"[stream] decrypt err: {e}")
                continue
            if len(pt) < 48:
                if debug: print(f"[stream] pt too short: {len(pt)}")
                continue
            nal = pt[48:]
            if not nal:
                continue
            first = nal[0]
            nal_type = (first >> 1) & 0x3F
            count += 1
            if debug and (count <= 5 or count % 50 == 0):
                print(f"[stream] vid#{count}: pt={len(pt)}B nal={len(nal)}B type={nal_type}")
            if nal_type == 49 and len(nal) >= 3:
                fu_hdr = nal[2]
                s_bit = fu_hdr & 0x80
                e_bit = fu_hdr & 0x40
                fu_type = fu_hdr & 0x3F
                if s_bit:
                    b0 = (nal[0] & 0x81) | (fu_type << 1)
                    b1 = nal[1]
                    fu_buf = bytearray([b0, b1]) + nal[3:]
                else:
                    if fu_buf:
                        fu_buf.extend(nal[3:])
                if e_bit and fu_buf:
                    yield START_CODE + bytes(fu_buf)
                    fu_buf = bytearray()
            else:
                yield START_CODE + nal
