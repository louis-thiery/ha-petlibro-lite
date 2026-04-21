"""HTTP endpoint serving HLS playlist + segments for a PetLibro stream.

Registered once per HA instance in `async_setup_entry`; looks up the
per-entry `PetLibroStreamManager` from `hass.data` on each request.
"""

from __future__ import annotations

import logging
import mimetypes
from pathlib import Path

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from ..const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class PetLibroStreamView(HomeAssistantView):
    url = "/api/petlibro_lite_stream/{entry_id}/{filename}"
    name = "api:petlibro_lite_stream"
    # Home Assistant's Stream component forwards auth via the HLS URL we
    # return from `stream_source()`. The dashboard (same-origin) sends the
    # user's auth token too. Unauthenticated requests are rejected.
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    async def get(
        self, request: web.Request, entry_id: str, filename: str,
    ) -> web.StreamResponse:
        # Prevent path traversal: only allow plain filenames (no `/`, `..`).
        if "/" in filename or ".." in filename or filename.startswith("."):
            return web.Response(status=400)

        runtime = self._hass.data.get(DOMAIN, {}).get(entry_id)
        if runtime is None or runtime.stream is None:
            return web.Response(status=404)

        manager = runtime.stream
        # Extend the keep-alive deadline so an active viewer keeps the
        # stream warm.
        manager.bump_deadline()

        path: Path = manager.output_dir / filename
        if not path.exists():
            # If this is the playlist and the stream hasn't started yet,
            # kick it off. The caller (HA Stream / <video> tag) will retry
            # on 404 with a short delay.
            if filename.endswith(".m3u8"):
                await manager.async_ensure_running()
                if not path.exists():
                    return web.Response(status=404)
            else:
                return web.Response(status=404)

        content_type, _ = mimetypes.guess_type(str(path))
        if content_type is None:
            if filename.endswith(".m3u8"):
                content_type = "application/vnd.apple.mpegurl"
            elif filename.endswith(".m4s"):
                content_type = "video/iso.segment"
            elif filename.endswith(".mp4"):
                content_type = "video/mp4"
            else:
                content_type = "application/octet-stream"

        headers = {
            "Cache-Control": "no-cache",
            "Content-Type": content_type,
        }
        return web.FileResponse(path, headers=headers)
