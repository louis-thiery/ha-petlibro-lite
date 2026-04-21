"""KCP reliability layer on top of an aioice UDP pipe.

Confirmed via Frida hook on `ikcp_create` (2026-04-20): Tuya uses the
vanilla skywind3000/kcp.c implementation with:

- `conv_id` = a monotonic per-device counter starting at 0. Not derived
  from the sessionid. Each logical stream (video/audio/control) gets
  its own KCP instance with its own conv. We'll start at 0 for the
  primary video stream and see what comes back.
- Default window sizes + `nodelay` (the Tuya LogP2PSDK binary strings
  hint at this but we haven't Frida-confirmed the exact parameters;
  safe defaults are no_delay=True, send/recv window 128+, resend=2).

The skywind kcp.py PyPI package (RealistikDash) is a thin
cython-wrapped binding of the same ikcp.c we already identified
inside `libThingP2PSDK.so`, so the wire protocol is bit-identical.

## Usage

```python
agent = TuyaRtcSession(cfg)
await agent.connect()                       # ICE complete
kcp = KcpTransport(agent, conv_id=0)
await kcp.start()                           # begins send/recv pumps
await kcp.send(b"hello")                    # bytes go out via KCP
data = await kcp.recv()                     # next reassembled stream chunk
```

The class owns two asyncio tasks: `_rx_pump` reads datagrams off
aioice and feeds them into `KCP.receive`, and `_tick` calls
`kcp.update()` and emits any outbound packets through the handler
we registered. A third background Future drives the receive queue so
callers can `await kcp.recv()`.
"""
from __future__ import annotations

import asyncio
from typing import Callable

from .ikcp import KCP


_TICK_INTERVAL_S = 0.01   # 10ms ikcp_update cadence — matches Tuya's update_interval
_DEFAULT_WND = 128


class KcpTransport:
    """Async wrapper that runs a single KCP stream over an aioice UDP pipe."""

    def __init__(
        self,
        agent,                     # TuyaRtcSession or anything with `.agent.recv/.agent.send`
        *,
        conv_id: int = 0,
        max_transmission: int = 1400,
        no_delay: bool = True,
        update_interval_ms: int = 10,
        resend: int = 2,
        send_window: int = _DEFAULT_WND,
        recv_window: int = _DEFAULT_WND,
    ) -> None:
        self._agent = agent
        self.conv_id = conv_id
        self._kcp = KCP(
            conv_id,
            max_transmission,
            no_delay,
            update_interval_ms,
            resend,
            False,  # no_congestion_control = default (not disabled)
            send_window,
            recv_window,
        )
        # Outbound packets from KCP go through this handler. The kcp.py
        # library expects a callback with signature (data: bytes).
        self._kcp.outbound_handler(self._kcp_outbound)
        self._recv_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._outbound_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._rx_task: asyncio.Task | None = None
        self._tick_task: asyncio.Task | None = None
        self._tx_task: asyncio.Task | None = None
        self._closed = False
        # Optional callback hook for subclasses (SRTP wrap, etc.)
        self._on_recv: Callable[[bytes], None] | None = None

    # ---- lifecycle ----------------------------------------------------

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._loop = loop
        self._rx_task = loop.create_task(self._rx_pump())
        self._tick_task = loop.create_task(self._tick_pump())
        self._tx_task = loop.create_task(self._tx_pump())

    async def close(self) -> None:
        self._closed = True
        for t in (self._rx_task, self._tick_task, self._tx_task):
            if t is not None:
                t.cancel()
        for t in (self._rx_task, self._tick_task, self._tx_task):
            if t is not None:
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass

    # ---- public send / recv -------------------------------------------

    async def send(self, data: bytes) -> None:
        """Enqueue application bytes for transmission via KCP."""
        self._kcp.enqueue(data)
        # update() is what actually schedules outbound packets; flush()
        # alone doesn't emit anything on a freshly-enqueued payload.
        self._kcp.update()
        self._kcp.flush()

    async def recv(self, timeout: float | None = None) -> bytes:
        """Wait for the next reassembled chunk from KCP."""
        if timeout is None:
            return await self._recv_queue.get()
        return await asyncio.wait_for(self._recv_queue.get(), timeout)

    def set_on_recv(self, cb: Callable[[bytes], None]) -> None:
        """Register a callback invoked synchronously for each received chunk.

        Useful for pipelines that want push-style delivery (SRTP + RTP
        depacketizer) instead of polling `recv()`."""
        self._on_recv = cb

    # ---- internals ----------------------------------------------------

    def _kcp_outbound(self, _kcp, data: bytes) -> None:
        """Called by KCP synchronously when it has a packet to put on the
        wire (signature is `(kcp_instance, bytes)`). We must NOT do
        async work here; queue bytes for `_tx_pump` to drain instead."""
        self._outbound_queue.put_nowait(bytes(data))

    async def _tx_pump(self) -> None:
        while not self._closed:
            try:
                data = await self._outbound_queue.get()
            except asyncio.CancelledError:
                break
            try:
                await self._agent.agent.send(data)
            except Exception as e:
                print(f"[kcp] send error: {e}")

    async def _rx_pump(self) -> None:
        while not self._closed:
            try:
                data = await self._agent.agent.recv()
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(0.1)
                continue
            if not data:
                continue
            try:
                self._kcp.receive(data)
            except Exception as e:
                print(f"[kcp] receive error: {e}")
                continue
            # update() after ingest lets KCP schedule the ACK for the
            # segments we just consumed — without this, the sender keeps
            # retransmitting until it times out.
            self._kcp.update()
            self._kcp.flush()
            # Drain any fully-reassembled chunks
            while self._kcp.get_next_packet_size() > 0:
                chunk = bytes(self._kcp.get_received())
                if self._on_recv is not None:
                    try:
                        self._on_recv(chunk)
                    except Exception as e:
                        print(f"[kcp] on_recv error: {e}")
                await self._recv_queue.put(chunk)

    async def _tick_pump(self) -> None:
        while not self._closed:
            try:
                self._kcp.update()
                self._kcp.flush()
            except Exception:
                pass
            await asyncio.sleep(_TICK_INTERVAL_S)


# ---- offline transport for unit tests ----


class _LoopbackAgent:
    """A minimal stand-in for aioice.Connection that wires two
    transports together in-process. Used only for tests."""

    def __init__(self) -> None:
        self._out: asyncio.Queue[bytes] = asyncio.Queue()
        self._peer: "_LoopbackAgent | None" = None

    def pair(self, other: "_LoopbackAgent") -> None:
        self._peer = other
        other._peer = self

    async def send(self, data: bytes) -> None:
        assert self._peer is not None
        await self._peer._out.put(bytes(data))

    async def recv(self) -> bytes:
        return await self._out.get()


class _AgentAdapter:
    """Wrap a _LoopbackAgent so KcpTransport sees `.agent.send/.agent.recv`."""

    def __init__(self, lb: _LoopbackAgent) -> None:
        self.agent = lb
