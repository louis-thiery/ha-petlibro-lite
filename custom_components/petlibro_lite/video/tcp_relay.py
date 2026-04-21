"""TCP transport for the Tuya 'imm' cowboy handshake.

Confirmed via host-side tcpdump on 2026-04-20: the handshake runs
over TCP to the endpoint in `tcp_token.urls[0]` (a `tcp4:HOST:PORT`
URL from the `rtc.session.offer` HTTPS response), NOT over the
ICE/KCP path used for media. See `findings_handshake.md`.

Each logical handshake message is a single TLV frame on the wire:

    [u16 tlv_id=0xF400][u16 body_len][body_len body bytes]

so the receiver can pull a frame length from the first 4 bytes and
then read the rest. `TcpRelayTransport.recv()` does exactly that.
"""
from __future__ import annotations

import asyncio
from typing import Optional


class TcpRelayTransport:
    """Length-framed TLV transport over a raw TCP socket.

    Usage::

        transport = TcpRelayTransport("44.233.60.51", 1443)
        await transport.connect()
        await transport.send(frame_bytes)
        reply = await transport.recv()
        await transport.close()
    """

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None

    async def connect(self, timeout: float = 10.0) -> None:
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port), timeout=timeout
        )

    async def send(self, frame: bytes) -> None:
        if self._writer is None:
            raise RuntimeError("transport not connected")
        self._writer.write(frame)
        await self._writer.drain()

    async def recv(self, timeout: float = 10.0) -> bytes:
        """Read one full TLV frame off the wire.

        First 4 bytes give `[tlv_id(2) body_len(2)]`; we then read
        exactly `body_len` more bytes so the returned buffer is a
        complete TLV frame ready for `tlv_decode()`.
        """
        if self._reader is None:
            raise RuntimeError("transport not connected")
        hdr = await asyncio.wait_for(self._reader.readexactly(4), timeout=timeout)
        body_len = int.from_bytes(hdr[2:4], "big")
        body = await asyncio.wait_for(
            self._reader.readexactly(body_len), timeout=timeout
        )
        return hdr + body

    async def close(self) -> None:
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None


def parse_tcp_url(url: str) -> tuple[str, int]:
    """Split a `tcp4:HOST:PORT` url (as returned in `tcp_token.urls`)
    into `(host, port)`. Accepts bare `HOST:PORT` as well."""
    if url.startswith("tcp4:"):
        url = url[len("tcp4:"):]
    elif url.startswith("tcp6:"):
        url = url[len("tcp6:"):]
    # IPv6 form: `[addr]:port`
    if url.startswith("["):
        close_bracket = url.rfind("]")
        host = url[1:close_bracket]
        port = int(url[close_bracket + 2:])
        return host, port
    host, _, port_s = url.rpartition(":")
    return host, int(port_s)
