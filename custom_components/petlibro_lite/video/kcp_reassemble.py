"""Minimal KCP PUSH reassembly for the TCP-relay media path.

The full skywind3000/kcp.c protocol supports PUSH / ACK / WASK / WINS
plus window-based flow control. For our receive-only use case (the
feeder streams H.264 to us; we only send control opcodes which are
tiny one-segment messages), we need just enough to:

1. Consume incoming `KcpSegment` objects pulled off TLV 0xF600 frames.
2. Buffer out-of-order `sn` numbers and stitch multi-fragment frames
   (`frg` counts down to 0 on the final segment) into complete
   application messages.
3. Emit KCP ACK segments back so the feeder doesn't retransmit
   segments we've already received.

This is ONE-WAY reassembly on a single conv. The feeder retransmits
up to a few times before giving up, so even naive ACK-on-first-seen
is usually enough. If we drop a segment permanently, the frame is
lost — acceptable for live video where the next I-frame is <=2s away.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .media_framing import (
    KCP_CMD_ACK,
    KCP_CMD_PUSH,
    KcpSegment,
    encode_data_frame,
)


@dataclass
class KcpReassembler:
    """Track per-conv PUSH reassembly state.

    `on_ack` is called with an already-TLV-framed byte string each
    time we want to send an ACK back to the feeder; the caller is
    responsible for pushing it through the TCP transport.
    """
    conv: int
    # Window size to advertise in outgoing ACKs — the vanilla default
    # (128) matches what we see in captured flows.
    wnd: int = 128

    # sn -> segment waiting for earlier sns (only PUSH segments land here)
    _pending: dict[int, KcpSegment] = field(default_factory=dict)
    # next sn we expect to deliver (monotonic). Frames arrive with
    # consecutive sns; frg decrements to 0 on the final fragment.
    _next_sn: int = 0
    # Assembled fragments not yet flushed (because frg > 0).
    _current: list[bytes] = field(default_factory=list)

    # ---- inbound handling ---------------------------------------------

    def ingest(self, seg: KcpSegment) -> list[bytes]:
        """Feed a received KCP segment; return any completed messages.

        ACK segments are silently dropped (the feeder doesn't expect
        them back after we send control opcodes, and we don't
        retransmit). For PUSH segments, reassembled application-level
        payloads are returned — one element per complete message.
        """
        if seg.conv != self.conv:
            return []
        if seg.cmd != KCP_CMD_PUSH:
            return []
        self._pending[seg.sn] = seg

        out: list[bytes] = []
        while self._next_sn in self._pending:
            cur = self._pending.pop(self._next_sn)
            self._current.append(cur.data)
            self._next_sn += 1
            if cur.frg == 0:
                out.append(b"".join(self._current))
                self._current = []
        return out

    def build_ack(self, seg: KcpSegment) -> bytes:
        """Return a TLV-framed KCP ACK for a single PUSH segment."""
        ack = KcpSegment(
            conv=self.conv,
            cmd=KCP_CMD_ACK,
            frg=0,
            wnd=self.wnd,
            ts=seg.ts,           # echo the PUSH's ts back
            sn=seg.sn,           # which sn this ACK is for
            una=self._next_sn,   # everything below this is received
            data=b"",
        )
        return encode_data_frame(ack)
