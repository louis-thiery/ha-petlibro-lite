"""On-demand HEVC stream manager for a single PetLibro feeder.

Wraps `driver.run_stream()` in a long-running task whose sink pipes raw
Annex-B HEVC into `ffmpeg`, which writes a fragmented-MP4 HLS playlist
into a per-entry tmp directory that `HomeAssistantView` serves to HA's
Stream component and the custom dashboard.

Keep-alive model: every HLS GET (playlist or segment) and every snapshot
request extends a deadline (`IDLE_TIMEOUT` seconds in the future). A
background watchdog tears the stream down once the deadline elapses with
no traffic. This works cleanly with HA's Stream component — which has no
"release" callback paired with `stream_source()` — because viewers that
stop watching naturally stop polling the HLS playlist.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from pathlib import Path

from typing import Callable

from homeassistant.components.ffmpeg import get_ffmpeg_manager
from homeassistant.core import HomeAssistant

from .driver import (
    PHASE_ERROR,
    PHASE_SIGNALING,
    StreamError,
    StreamParams,
    run_stream,
)

PHASE_IDLE = "idle"

_LOGGER = logging.getLogger(__name__)

IDLE_TIMEOUT = 90.0  # seconds of no HLS traffic before teardown
MAX_RETRIES = 3       # attempts before giving up on a cold start
RETRY_BACKOFF_S = 2.0 # delay between retries
SEGMENT_DURATION = 2  # HLS segment length (seconds)
SEGMENT_COUNT = 6  # live playlist window


def _read_if_exists(path: Path) -> str | None:
    """Blocking read helper, run via executor from the event loop."""
    if not path.exists() or path.stat().st_size == 0:
        return None
    return path.read_text()
HLS_PLAYLIST = "stream.m3u8"
FIRST_SEGMENT_TIMEOUT = 20.0  # wait up to this long for the first HLS segment


class PetLibroStreamManager:
    """Per-config-entry manager holding a single live HLS session."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        params: StreamParams,
    ) -> None:
        self._hass = hass
        self._entry_id = entry_id
        self._params = params
        self._lock = asyncio.Lock()
        self._stop_event: asyncio.Event | None = None
        self._driver_task: asyncio.Task | None = None
        self._ffmpeg: asyncio.subprocess.Process | None = None
        self._ffmpeg_stderr_task: asyncio.Task | None = None
        self._watchdog_task: asyncio.Task | None = None
        self._deadline: float = 0.0
        self._output_dir: Path = Path(
            hass.config.path("tmp", f"petlibro_lite_{entry_id}")
        )
        self._ready_event = asyncio.Event()
        self._phase: str = PHASE_IDLE
        # Consumers (camera entity) subscribe to phase changes so their
        # attributes update in real time and the Lovelace card's loading
        # overlay flips without a polling delay.
        self._phase_listeners: list[Callable[[str], None]] = []

    @property
    def phase(self) -> str:
        return self._phase

    def add_phase_listener(self, cb: Callable[[str], None]) -> Callable[[], None]:
        self._phase_listeners.append(cb)

        def _unsub() -> None:
            try:
                self._phase_listeners.remove(cb)
            except ValueError:
                pass

        return _unsub

    def _set_phase(self, phase: str) -> None:
        if phase == self._phase:
            return
        self._phase = phase
        _LOGGER.debug("petlibro stream %s phase=%s", self._entry_id, phase)
        for cb in list(self._phase_listeners):
            try:
                cb(phase)
            except Exception:  # noqa: BLE001
                _LOGGER.debug("phase listener raised", exc_info=True)

    @property
    def entry_id(self) -> str:
        return self._entry_id

    @property
    def output_dir(self) -> Path:
        return self._output_dir

    @property
    def is_running(self) -> bool:
        return self._driver_task is not None and not self._driver_task.done()

    def bump_deadline(self) -> None:
        """Push the idle deadline out by `IDLE_TIMEOUT` seconds.

        Called by `PetLibroStreamView` on every HLS GET so an active
        viewer keeps the pipeline alive.
        """
        self._deadline = time.monotonic() + IDLE_TIMEOUT

    async def async_ensure_running(self, *, wait_for_segment: bool = False) -> None:
        """Start the stream if not already running.

        By default returns as soon as the pipeline is spawned — callers
        that need the first segment (snapshot) pass `wait_for_segment`
        to block until the playlist is populated.
        """
        async with self._lock:
            self.bump_deadline()
            if not self.is_running:
                await self._start_locked()
        if not wait_for_segment:
            return
        try:
            await asyncio.wait_for(
                self._ready_event.wait(), timeout=FIRST_SEGMENT_TIMEOUT,
            )
        except asyncio.TimeoutError:
            _LOGGER.warning(
                "petlibro stream %s: no HLS segment after %ss",
                self._entry_id, FIRST_SEGMENT_TIMEOUT,
            )

    def hls_url(self) -> str:
        return f"/api/petlibro_lite_stream/{self._entry_id}/{HLS_PLAYLIST}"

    async def async_stop(self) -> None:
        """Tear down unconditionally (HA unload / shutdown)."""
        async with self._lock:
            await self._stop_locked()

    async def async_get_snapshot(self) -> bytes | None:
        """Return a JPEG of the current frame, or None if unavailable."""
        await self.async_ensure_running(wait_for_segment=True)
        playlist = self._output_dir / HLS_PLAYLIST
        if not await asyncio.to_thread(playlist.exists):
            return None
        self.bump_deadline()
        proc = await asyncio.create_subprocess_exec(
            get_ffmpeg_manager(self._hass).binary,
            "-hide_banner", "-loglevel", "error",
            "-i", str(playlist),
            "-frames:v", "1",
            "-q:v", "3",
            "-f", "mjpeg",
            "pipe:1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        except asyncio.TimeoutError:
            proc.kill()
            return None
        return stdout or None

    # ------------------------------------------------------------------ #
    # internals
    # ------------------------------------------------------------------ #

    async def _start_locked(self) -> None:
        def _prep_output_dir() -> None:
            self._output_dir.mkdir(parents=True, exist_ok=True)
            # Wipe stale segments so clients don't pick up a playlist with
            # broken segment URIs from a prior session.
            for f in self._output_dir.iterdir():
                try:
                    f.unlink()
                except OSError:
                    pass

        await asyncio.to_thread(_prep_output_dir)

        self._ready_event.clear()
        self._stop_event = asyncio.Event()

        # ffmpeg: raw HEVC Annex-B on stdin → fragmented-MP4 HLS on disk.
        # Binary path comes from HA's ffmpeg integration manager so it
        # respects any user-configured override instead of relying on $PATH.
        self._ffmpeg = await asyncio.create_subprocess_exec(
            get_ffmpeg_manager(self._hass).binary,
            "-hide_banner",
            "-loglevel", "warning",
            "-f", "hevc",
            "-i", "pipe:0",
            "-c:v", "copy",
            "-an",
            "-f", "hls",
            "-hls_time", str(SEGMENT_DURATION),
            "-hls_list_size", str(SEGMENT_COUNT),
            "-hls_flags", "delete_segments+append_list+omit_endlist+independent_segments",
            "-hls_segment_type", "fmp4",
            "-hls_segment_filename", str(self._output_dir / "seg_%05d.m4s"),
            str(self._output_dir / HLS_PLAYLIST),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        self._ffmpeg_stderr_task = asyncio.create_task(
            self._drain_ffmpeg_stderr(),
            name=f"petlibro-ffmpeg-stderr-{self._entry_id}",
        )

        async def _sink(nal_bytes: bytes) -> None:
            if self._ffmpeg is None or self._ffmpeg.stdin is None:
                return
            try:
                self._ffmpeg.stdin.write(nal_bytes)
                await self._ffmpeg.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass

        self._set_phase(PHASE_SIGNALING)
        self._driver_task = asyncio.create_task(
            self._run_driver(_sink),
            name=f"petlibro-driver-{self._entry_id}",
        )
        self._watchdog_task = asyncio.create_task(
            self._watchdog(),
            name=f"petlibro-watchdog-{self._entry_id}",
        )
        asyncio.create_task(
            self._watch_ready(), name=f"petlibro-ready-{self._entry_id}",
        )

        _LOGGER.info(
            "petlibro stream %s: started (output_dir=%s)",
            self._entry_id, self._output_dir,
        )

    async def _run_driver(self, sink) -> None:
        """Drive the stream, retrying handshake failures a few times.

        The Tuya RTC handshake can fail transiently — the PetLibro app itself
        retries silently when it hits an activate_resp timeout or a stalled
        AUTH exchange (feeder ACKs KCP but never emits conv=1 frames).
        We mirror that: up to MAX_RETRIES attempts with a short backoff
        between each. Only a successful transition to streaming OR an
        explicit stop_event stops the retries.
        """
        assert self._stop_event is not None
        last_err: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            if self._stop_event.is_set():
                return
            try:
                await run_stream(
                    self._params,
                    sink,
                    self._stop_event,
                    on_phase=self._set_phase,
                )
                # Clean exit via stop_event — no need to retry.
                return
            except StreamError as e:
                last_err = e
                _LOGGER.warning(
                    "petlibro stream %s: handshake attempt %d/%d failed: %s",
                    self._entry_id, attempt, MAX_RETRIES, e,
                )
            except asyncio.CancelledError:
                return
            except Exception as e:  # pragma: no cover
                last_err = e
                _LOGGER.exception(
                    "petlibro stream %s: driver crashed on attempt %d/%d",
                    self._entry_id, attempt, MAX_RETRIES,
                )
            if attempt < MAX_RETRIES:
                # Keep the phase in SIGNALING during backoff so the card's
                # "Connecting…" overlay stays visible instead of flashing
                # the error state between retries.
                self._set_phase(PHASE_SIGNALING)
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=RETRY_BACKOFF_S,
                    )
                    return  # stop_event fired mid-backoff
                except asyncio.TimeoutError:
                    pass
        _LOGGER.error(
            "petlibro stream %s: handshake failed after %d attempts: %s",
            self._entry_id, MAX_RETRIES, last_err,
        )
        self._set_phase(PHASE_ERROR)

    async def _watchdog(self) -> None:
        try:
            while True:
                now = time.monotonic()
                if now >= self._deadline:
                    async with self._lock:
                        if time.monotonic() >= self._deadline and self.is_running:
                            _LOGGER.info(
                                "petlibro stream %s: idle %.0fs — stopping",
                                self._entry_id, IDLE_TIMEOUT,
                            )
                            await self._stop_locked()
                            return
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            return

    async def _watch_ready(self) -> None:
        playlist = self._output_dir / HLS_PLAYLIST
        deadline = time.monotonic() + FIRST_SEGMENT_TIMEOUT
        while time.monotonic() < deadline and not self._ready_event.is_set():
            try:
                text = await self._hass.async_add_executor_job(
                    _read_if_exists, playlist,
                )
            except OSError:
                text = None
            if text and "#EXTINF" in text:
                self._ready_event.set()
                return
            await asyncio.sleep(0.25)

    async def _drain_ffmpeg_stderr(self) -> None:
        if self._ffmpeg is None or self._ffmpeg.stderr is None:
            return
        while True:
            line = await self._ffmpeg.stderr.readline()
            if not line:
                return
            _LOGGER.debug(
                "petlibro[%s] ffmpeg: %s",
                self._entry_id, line.decode(errors="replace").rstrip(),
            )

    async def _stop_locked(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        tasks: list[asyncio.Task] = [
            t for t in (self._driver_task, self._watchdog_task)
            if t is not None
        ]
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await asyncio.wait_for(t, timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                pass
        if self._ffmpeg is not None:
            if self._ffmpeg.stdin is not None:
                try:
                    self._ffmpeg.stdin.close()
                except Exception:
                    pass
            try:
                await asyncio.wait_for(self._ffmpeg.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._ffmpeg.kill()
                try:
                    await self._ffmpeg.wait()
                except Exception:
                    pass
        if self._ffmpeg_stderr_task is not None:
            self._ffmpeg_stderr_task.cancel()
            try:
                await self._ffmpeg_stderr_task
            except Exception:
                pass
        def _cleanup_output_dir() -> None:
            try:
                if self._output_dir.exists():
                    shutil.rmtree(self._output_dir, ignore_errors=True)
            except OSError:
                pass

        await asyncio.to_thread(_cleanup_output_dir)
        self._driver_task = None
        self._watchdog_task = None
        self._ffmpeg = None
        self._ffmpeg_stderr_task = None
        self._stop_event = None
        self._deadline = 0.0
        # Only reset to idle if we weren't already in an error phase — error
        # state should persist past teardown so the card can surface "retry"
        # UX instead of just flipping to idle as if nothing happened.
        if self._phase != PHASE_ERROR:
            self._set_phase(PHASE_IDLE)
        _LOGGER.info("petlibro stream %s: stopped", self._entry_id)
