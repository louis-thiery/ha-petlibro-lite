"""Pure-Python KCP implementation — subset sufficient for PetLibro.

KCP is a reliable-ARQ protocol over UDP (skywind3000/kcp, ikcp.c). The
PyPI `kcp` Cython package can't be installed on HAOS (aarch64 Linux has
no prebuilt wheel, and new Python versions lack wheels entirely), so we
need a pure-Python implementation.

This port targets the narrow feature set PetLibro requires:

• Outbound: send small payloads on conv=0 (<= MTU, no fragmentation).
  The AUTH/CAPABILITY batch is six ~100-byte messages total.
• Inbound: receive large streams on conv=1/2 (video/audio), with KCP
  fragmentation already split by the sender into <=1400B frames. We
  reassemble by `frg` count per logical message.
• ACKs: send one UNA-bearing ACK per received PUSH so the sender stops
  retransmitting.

Skipped features (safe to ignore for Tuya's server-driven video):
  · Fast retransmit (resend) — RTO timeout only.
  · Congestion control — Tuya disables it; we match.
  · Window probe (wask/wins) — we advertise large `wnd` and rely on it.
  · Stream mode.

Wire format (24-byte header + payload, all LE except cmd/frg):
  conv: u32  cmd: u8  frg: u8  wnd: u16  ts: u32  sn: u32  una: u32  len: u32
"""

from __future__ import annotations

import struct
import time
from collections import deque
from dataclasses import dataclass, field

IKCP_RTO_DEF = 1500
IKCP_RTO_MIN = 100
IKCP_RTO_MAX = 60000
IKCP_CMD_PUSH = 81
IKCP_CMD_ACK = 82
IKCP_CMD_WASK = 83
IKCP_CMD_WINS = 84
IKCP_OVERHEAD = 24
IKCP_MTU_DEF = 1400
IKCP_INTERVAL = 10
IKCP_WND_SND = 128
IKCP_WND_RCV = 128


def _ms() -> int:
    return int(time.monotonic() * 1000) & 0xFFFFFFFF


def _pack_header(
    conv: int, cmd: int, frg: int, wnd: int,
    ts: int, sn: int, una: int, length: int,
) -> bytes:
    return struct.pack(
        "<IBBHIIII",
        conv & 0xFFFFFFFF,
        cmd & 0xFF,
        frg & 0xFF,
        wnd & 0xFFFF,
        ts & 0xFFFFFFFF,
        sn & 0xFFFFFFFF,
        una & 0xFFFFFFFF,
        length & 0xFFFFFFFF,
    )


def _unpack_header(buf: bytes, off: int = 0):
    return struct.unpack_from("<IBBHIIII", buf, off)


@dataclass
class _Segment:
    conv: int = 0
    cmd: int = 0
    frg: int = 0
    wnd: int = 0
    ts: int = 0
    sn: int = 0
    una: int = 0
    data: bytes = b""
    # outbound bookkeeping
    resendts: int = 0
    rto: int = 0
    fastack: int = 0
    xmit: int = 0


class KCP:
    """Subset of ikcp.c sufficient for the PetLibro streaming pipeline.

    Matches the public surface used by `KcpTransport`:

        k = KCP(conv, mtu, nodelay, update_ms, resend, no_cc, snd_wnd, rcv_wnd)
        k.outbound_handler(lambda kcp, data: ...)
        k.enqueue(b"payload")     # queue for send (may fragment)
        k.update(ts_ms=None)      # drive ACKs + retransmissions
        k.flush()                 # push queued segments out through the handler
        k.receive(raw_bytes)      # feed inbound UDP payload
        n = k.get_next_packet_size()
        data = k.get_received()   # pull next reassembled message
    """

    def __init__(
        self,
        conv: int,
        mtu: int = IKCP_MTU_DEF,
        nodelay: bool = False,
        update_interval_ms: int = IKCP_INTERVAL,
        resend: int = 0,
        no_congestion: bool = True,
        send_window: int = IKCP_WND_SND,
        recv_window: int = IKCP_WND_RCV,
    ) -> None:
        self.conv = conv
        self.mtu = mtu
        self.mss = mtu - IKCP_OVERHEAD
        self.snd_wnd = send_window
        self.rcv_wnd = recv_window
        self.rmt_wnd = recv_window
        self.nodelay = nodelay
        self.interval = max(update_interval_ms, 10)
        self.resend = resend  # fast-retransmit threshold (unused in this subset)
        self.no_cc = no_congestion

        self.snd_nxt = 0
        self.snd_una = 0
        self.rcv_nxt = 0
        self.current = _ms()

        self.rx_rto = IKCP_RTO_DEF
        self.rx_srtt = 0
        self.rx_rttval = 0

        self.snd_queue: deque[_Segment] = deque()  # enqueued, not yet fragmented
        self.snd_buf: deque[_Segment] = deque()    # fragmented, awaiting ACK
        self.rcv_buf: list[_Segment] = []          # received, out-of-order
        self.rcv_queue: deque[_Segment] = deque()  # in-order, ready for user

        self.acklist: list[tuple[int, int]] = []   # (sn, ts) pairs to ACK back

        self._out_cb = None

    # ------------------------------------------------------------------
    # public API matching the Cython `kcp` package
    # ------------------------------------------------------------------

    def outbound_handler(self, cb) -> None:
        """Register a callback `cb(kcp, bytes)` invoked for each emitted UDP frame."""
        self._out_cb = cb

    def enqueue(self, data: bytes) -> int:
        """Queue a message for transmission. Fragments across `mss` if needed."""
        if not data:
            return -1
        count = max(1, (len(data) + self.mss - 1) // self.mss)
        if count > 255:
            return -2
        for i in range(count):
            chunk = data[i * self.mss : (i + 1) * self.mss]
            seg = _Segment(data=chunk, frg=count - i - 1)
            self.snd_queue.append(seg)
        return 0

    def update(self, ts_ms: int | None = None) -> None:
        """Advance the clock and emit retransmissions + ACKs."""
        self.current = ts_ms if ts_ms is not None else _ms()
        self.flush()

    def flush(self) -> None:
        """Drain the send queue + retransmit stale segments."""
        if self._out_cb is None:
            return
        cwnd = min(self.snd_wnd, self.rmt_wnd)
        # Move eligible segments from snd_queue to snd_buf.
        while self.snd_queue and (
            (self.snd_nxt - self.snd_una) < cwnd
        ):
            seg = self.snd_queue.popleft()
            seg.conv = self.conv
            seg.cmd = IKCP_CMD_PUSH
            seg.wnd = self._wnd_unused()
            seg.ts = self.current
            seg.sn = self.snd_nxt
            seg.una = self.rcv_nxt
            seg.resendts = self.current
            seg.rto = self.rx_rto
            seg.xmit = 0
            self.snd_buf.append(seg)
            self.snd_nxt += 1

        # Emit pending ACKs.
        wnd_unused = self._wnd_unused()
        for sn, ts in self.acklist:
            self._emit(
                _pack_header(
                    self.conv, IKCP_CMD_ACK, 0, wnd_unused, ts, sn, self.rcv_nxt, 0,
                )
            )
        self.acklist.clear()

        # Emit PUSH segments (first send or retransmit after RTO).
        for seg in self.snd_buf:
            need_send = False
            if seg.xmit == 0:
                need_send = True
                seg.xmit = 1
                seg.resendts = self.current + seg.rto
            elif self.current >= seg.resendts:
                need_send = True
                seg.xmit += 1
                seg.rto = min(seg.rto * 2, IKCP_RTO_MAX)
                seg.resendts = self.current + seg.rto
            if need_send:
                seg.ts = self.current
                seg.wnd = wnd_unused
                seg.una = self.rcv_nxt
                header = _pack_header(
                    self.conv, seg.cmd, seg.frg, seg.wnd,
                    seg.ts, seg.sn, seg.una, len(seg.data),
                )
                self._emit(header + seg.data)

    def receive(self, data: bytes) -> int:
        """Feed a raw inbound UDP payload. Multiple KCP frames may be packed."""
        if len(data) < IKCP_OVERHEAD:
            return -1
        off = 0
        while off + IKCP_OVERHEAD <= len(data):
            conv, cmd, frg, wnd, ts, sn, una, length = _unpack_header(data, off)
            off += IKCP_OVERHEAD
            if conv != self.conv:
                return -2
            if off + length > len(data):
                return -3
            payload = data[off : off + length] if length else b""
            off += length
            self.rmt_wnd = wnd
            self._parse_una(una)

            if cmd == IKCP_CMD_ACK:
                self._update_rtt(self.current - ts)
                self._parse_ack(sn)
            elif cmd == IKCP_CMD_PUSH:
                self.acklist.append((sn, ts))
                if sn >= self.rcv_nxt + self.rcv_wnd:
                    # Out of window; drop.
                    continue
                self._ingest_push(_Segment(
                    conv=conv, cmd=cmd, frg=frg, wnd=wnd, ts=ts,
                    sn=sn, una=una, data=payload,
                ))
            elif cmd == IKCP_CMD_WASK:
                # Peer is probing our window; respond.
                self._emit(_pack_header(
                    self.conv, IKCP_CMD_WINS, 0, self._wnd_unused(),
                    self.current, 0, self.rcv_nxt, 0,
                ))
            elif cmd == IKCP_CMD_WINS:
                pass
            else:
                return -4
        return 0

    def get_next_packet_size(self) -> int:
        """Return the length of the next reassembled message, or 0 if none ready."""
        if not self.rcv_queue:
            return 0
        # Peek: check that the first `frg+1` segments form a complete message.
        first = self.rcv_queue[0]
        if first.frg == 0:
            return len(first.data)
        if len(self.rcv_queue) < first.frg + 1:
            return 0
        total = 0
        for i, seg in enumerate(self.rcv_queue):
            total += len(seg.data)
            if seg.frg == 0:
                return total
            if i >= first.frg:
                break
        return 0

    def get_received(self) -> bytes:
        """Pop and return the next reassembled message. Returns b'' if none."""
        size = self.get_next_packet_size()
        if size == 0:
            return b""
        parts: list[bytes] = []
        while self.rcv_queue:
            seg = self.rcv_queue.popleft()
            parts.append(seg.data)
            if seg.frg == 0:
                break
        return b"".join(parts)

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _emit(self, frame: bytes) -> None:
        try:
            self._out_cb(self, frame)
        except Exception:  # pragma: no cover
            pass

    def _wnd_unused(self) -> int:
        unused = self.rcv_wnd - len(self.rcv_queue)
        return max(0, unused)

    def _update_rtt(self, rtt: int) -> None:
        if rtt < 0:
            return
        if self.rx_srtt == 0:
            self.rx_srtt = rtt
            self.rx_rttval = rtt // 2
        else:
            delta = abs(rtt - self.rx_srtt)
            self.rx_rttval = (3 * self.rx_rttval + delta) // 4
            self.rx_srtt = (7 * self.rx_srtt + rtt) // 8
            if self.rx_srtt < 1:
                self.rx_srtt = 1
        rto = self.rx_srtt + max(self.interval, 4 * self.rx_rttval)
        self.rx_rto = max(IKCP_RTO_MIN, min(IKCP_RTO_MAX, rto))

    def _parse_una(self, una: int) -> None:
        """Remove acknowledged segments (sn < una) from the send buffer."""
        while self.snd_buf and self.snd_buf[0].sn < una:
            self.snd_buf.popleft()
        self.snd_una = una if una > self.snd_una else self.snd_una

    def _parse_ack(self, sn: int) -> None:
        for i, seg in enumerate(self.snd_buf):
            if seg.sn == sn:
                del self.snd_buf[i]
                return
            if seg.sn > sn:
                return

    def _ingest_push(self, seg: _Segment) -> None:
        if seg.sn < self.rcv_nxt:
            return  # duplicate
        # Insert into rcv_buf in order, skipping duplicates.
        inserted = False
        for i, existing in enumerate(self.rcv_buf):
            if existing.sn == seg.sn:
                return  # duplicate
            if existing.sn > seg.sn:
                self.rcv_buf.insert(i, seg)
                inserted = True
                break
        if not inserted:
            self.rcv_buf.append(seg)
        # Move contiguous segments starting at rcv_nxt into rcv_queue.
        while self.rcv_buf and self.rcv_buf[0].sn == self.rcv_nxt:
            self.rcv_queue.append(self.rcv_buf.pop(0))
            self.rcv_nxt += 1
