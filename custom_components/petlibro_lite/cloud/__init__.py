"""Tuya-whitelabel (PetLibro) cloud client.

Implements the login + `tuya.m.smart.operate.all.log` call the PetLibro
Lite app uses for feed / warning history. Vendored so HACS users only
need the manifest's requirements (`httpx`, `pycryptodome`) installed —
no extra pip install.

Only `TuyaApiClient`, `login`, and `LoginResult` are re-exported — the
rest of the crypto module is implementation detail the integration never
needs to touch directly.
"""

from .api import TuyaApiClient
from .login import LoginResult, login

__all__ = ["LoginResult", "TuyaApiClient", "login"]
