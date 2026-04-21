"""HTTPx client for the Tuya-whitelabel PetLibro cloud (`a1.tuyaus.com`).

The `TuyaApiClient.call()` entry point signs, encrypts, ships, decrypts,
and returns a Python dict — same shape the PetLibro Lite app sees.

All crypto is in `.crypto`; this module is just the HTTP +
form-building glue.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

from . import crypto

# Fields that contribute to the sign_input, in the order the native code
# sorts them. `postData` is MD5 of the ciphertext (not the raw ciphertext).
_SIGN_FIELDS = (
    "a", "appVersion", "chKey", "clientId", "deviceId",
    "et", "lang", "os", "postData", "requestId", "sid", "time", "ttid", "v",
)


@dataclass
class TuyaApiClient:
    """Minimal Tuya-whitelabel cloud client for PetLibro.

    Pass `sid` if you already have a session token (from a prior login flow
    or mitm capture). Login itself is a future piece — for now, sessions
    must be supplied externally.
    """
    client_id: str = "vmwyfs95mmaqg5awvcjt"
    device_id: str = "a52225a5988f017a4564c06cc23cac5fd6a1c72067e3"
    app_version: str = "1.0.6"
    sid: str | None = None
    # Per-session salt returned by login as `ecode`. Falls back to the
    # tenant default when not supplied — works for some accounts but
    # the server is now rotating salts per login (seen 2026-04-20:
    # z2z7az77z917a1z7, z2z7az773917a1z7 on different logins of same
    # account). If unset and sid is set, the GCM MAC on the response
    # will fail — always pass ecode from login or via PETLIBRO_ECODE.
    ecode: str | None = None
    endpoint: str = "https://a1.tuyaus.com/api.json"
    ttid: str = field(default="", init=False)
    ch_key: str = field(default="", init=False)

    def __post_init__(self) -> None:
        self.ttid = f"sdk_thing@{self.client_id}"
        self.ch_key = crypto.get_ch_key(self.client_id)

    def _build_form(
        self,
        api: str,
        *,
        version: str = "1.0",
        body: dict | None = None,
        extra: dict | None = None,
    ) -> tuple[dict, str]:
        """Build the form-encoded request body + compute sign. Returns
        (form_dict, request_id) so the caller can match the response."""
        request_id = str(uuid.uuid4())
        now = str(int(time.time()))
        form: dict[str, str] = {
            "a": api,
            "v": version,
            "time": now,
            "requestId": request_id,
            "clientId": self.client_id,
            "ttid": self.ttid,
            "appVersion": self.app_version,
            "osSystem": "13",
            "channel": "oem",
            "deviceId": self.device_id,
            "chKey": self.ch_key,
            "lang": "en_US",
            "os": "Android",
            "et": "3",
            # The following form fields aren't part of the signed set (see
            # _SIGN_FIELDS) but the PetLibro Lite app sends them on every
            # call, including login. Tuya appears to accept the request
            # without them (we've hit USER_PASSWD_WRONG, which means the
            # server processed the body), but we mirror the app to minimize
            # surprise — e.g. in case Tuya uses appRnVersion or bizData to
            # route login flow variants per app-version cohort.
            "appRnVersion": "5.72",
            "bizData": (
                '{"customDomainSupport":"1","miniappVersion":'
                '"{\\"AudioKit\\":\\"1.0.0-rc.28\\",\\"BaseKit\\":\\"3.6.12\\",'
                '\\"BizKit\\":\\"3.6.2\\",\\"CategoryCommonBizKit\\":\\"1.0.0\\",'
                '\\"DeviceKit\\":\\"3.7.10\\",\\"HomeKit\\":\\"3.2.0\\",'
                '\\"IPCKit\\":\\"2.0.7\\",\\"MapKit\\":\\"3.0.7\\",'
                '\\"MediaKit\\":\\"3.0.3\\",\\"MiniKit\\":\\"3.3.2\\",'
                '\\"P2PKit\\":\\"2.0.3\\",\\"PlayNetKit\\":\\"1.3.0-rc.16\\",'
                '\\"SweeperKit\\":\\"0.1.13\\",\\"container\\":\\"3.7.38\\"}"}'
            ),
            "deviceCoreVersion": "5.2.0",
            "sdkVersion": "5.2.0",
            "platform": "Android SDK built for arm64",
            "timeZoneId": "America/New_York",
        }
        if self.sid:
            form["sid"] = self.sid
        if extra:
            form.update(extra)
        if body is not None:
            plaintext = json.dumps(body, separators=(",", ":"))
            # Key choice: pre-login (no sid) uses the unsalted request_key;
            # post-login uses the ecode-salted get_encrypto_key. The server
            # mirrors this on the response side. Ecode is per-login.
            if self.sid:
                salt = self.ecode or crypto.CH_KEY_SALT
                key = crypto.get_encrypto_key(request_id, salt=salt)
            else:
                key = crypto.request_key(request_id)
            form["postData"] = crypto.encrypt_postdata(request_id, plaintext, key=key)
        # Sign with the canonical sorted || joined string. `postData` is
        # replaced by its md5 of ciphertext in the sign input.
        sign_input = self._build_sign_input(form)
        form["sign"] = crypto.sign_request(sign_input)
        return form, request_id

    def _build_sign_input(self, form: dict) -> str:
        parts = []
        for k in sorted(_SIGN_FIELDS):
            if k not in form:
                continue
            v = form[k]
            if k == "postData":
                # For the sign_input, postData is replaced by a "Tuya MD5"
                # of the base64 postData *string*: standard MD5, but with
                # the 4 output words in order (w1, w0, w3, w2) — a swap of
                # adjacent pairs. Observed consistently across all 80
                # captured mitm flows in 2026-04-20.
                d = hashlib.md5(v.encode("ascii")).digest()
                v = (d[4:8] + d[0:4] + d[12:16] + d[8:12]).hex()
            parts.append(f"{k}={v}")
        return "||".join(parts)

    def device_log(
        self,
        dev_id: str,
        *,
        start_ms: int | None = None,
        end_ms: int | None = None,
        size: int = 100,
        offset: int = 0,
        dp_ids: str | None = None,
        log_type: int = 7,
    ) -> list[dict]:
        """Fetch the feeder's device-timestamped DP event log from Tuya cloud.

        Returns a list of entries like:
          {"dpId": 236, "timeStamp": <unix_s>, "timeStr": "YYYY-MM-DD HH:MM:SS", "value": "..."}

        Args:
          dp_ids: comma-separated DP IDs, e.g. "236,237,247".
            236=warning, 237=last scheduled feed, 247=last manual feed.
            Default None → server returns all tracked DPs for the device.
          log_type: 7 is the "operate" log (what the PetLibro app uses).
          start_ms / end_ms: defaults to last 24h if unset.
          size/offset: pagination.
        """
        import time as _time
        if end_ms is None:
            end_ms = int(_time.time() * 1000)
        if start_ms is None:
            start_ms = end_ms - 24 * 3600 * 1000
        body = {
            "devId": dev_id,
            "gwId": dev_id,
            "limit": size,
            "offset": offset,
            "sortType": "DESC",
            "startTime": start_ms,
            "endTime": end_ms,
        }
        if dp_ids:
            body["dpIds"] = dp_ids
        resp = self.call("tuya.m.smart.operate.all.log", version="1.0", body=body)
        if not resp.get("success"):
            raise RuntimeError(f"device_log failed: {resp}")
        return resp["result"].get("dps", [])

    def rtc_session_offer(self, dev_id: str, sdp_offer: dict) -> dict:
        """Call `smartlife.m.rtc.session.offer` to open a WebRTC session.

        `sdp_offer` is the decoded header+msg body the app sends — our
        Phase 2 client builds this from aiortc.
        """
        import json as _json
        return self.call(
            "smartlife.m.rtc.session.offer",
            body={
                "api": "thing.m.rtc.session.offer_1.0",
                "devId": dev_id,
                "msg": _json.dumps(sdp_offer, separators=(",", ":")),
            },
        )

    def call(
        self,
        api: str,
        *,
        version: str = "1.0",
        body: dict | None = None,
        extra: dict | None = None,
        timeout: float = 15.0,
    ) -> dict:
        """Sign + encrypt + POST + decrypt. Returns the decoded response dict."""
        form, request_id = self._build_form(api, version=version, body=body, extra=extra)
        with httpx.Client(timeout=timeout) as c:
            resp = c.post(self.endpoint, data=form)
            resp.raise_for_status()
            payload = resp.json()
        if "result" not in payload:
            return payload
        if self.sid:
            salt = self.ecode or crypto.CH_KEY_SALT
            key = crypto.get_encrypto_key(request_id, salt=salt)
        else:
            key = crypto.request_key(request_id)
        return crypto.decrypt_response_with_key(payload["result"], key)
