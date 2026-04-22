"""Constants for the PetLibro Lite integration."""

from __future__ import annotations

DOMAIN = "petlibro_lite"

# Config entry keys (match tinytuya)
CONF_DEVICE_ID = "device_id"
CONF_LOCAL_KEY = "local_key"
CONF_HOST = "host"
CONF_PROTOCOL = "protocol"

DEFAULT_PROTOCOL = "3.4"
# 10s balances reactivity (user presses feed, UI updates quickly) with LAN
# manners. tinytuya session setup is ~500ms, so 10s polls leave the socket
# idle 95% of the time. The LAN coordinator also fires bus events on DP
# transitions — faster polling means smaller gaps where multiple feeds in
# quick succession could collapse into a single event.
DEFAULT_SCAN_INTERVAL = 10

# DPs we care about on PLAF203. Write-only DPs never appear in status reads;
# keep them here so consumers have a single source of truth for the numbers.
DP_MASTER_SWITCH = 101           # bool
DP_FEED_PORTIONS = 232           # int, write-only; value = portions 1..50
DP_SCHEDULES = 231               # hex blob of 5-byte records
DP_DEVICE_STATE = 233            # "standby" | "feeding"
DP_WARNING = 236                 # int; 0 = ok, 2 = outlet blocked (jam). Other codes TBD.
DP_FOOD_LEVEL = 241              # "full" | "low" | "empty" (?)
DP_LAST_MANUAL_FEED = 247        # {"value":N,"time":unix}
DP_LAST_SCHEDULED_FEED = 237     # {"value":N,"time":unix}
# Running counters, observed as "N|N|N" pipe-delimited strings. The first
# segment is today's portion count; the other two are TBD (likely week +
# month). Sibling jjjonesjr33/petlibro exposes the first value as
# `todayFeedingQuantity` and confirms the per-day reset behavior.
DP_DAILY_COUNTERS = 109

# DP 236 (warning) value → human label. Values beyond 2 surface as "warning <N>"
# until we've observed them in the wild and confirmed the meaning.
WARNING_LABELS = {
    0: "ok",
    2: "outlet_blocked",
}

# Device-wide limits observed in the app UI
MIN_PORTIONS = 1
MAX_PORTIONS = 50
MAX_SCHEDULE_SLOTS = 20          # the app caps around here; device may accept more

# --- cloud login -------------------------------------------------------------
# Setup requires the user's PetLibro Lite email + password — we exchange
# them for a Tuya session (sid/ecode/uid) once, then derive both
# `localKey` (used for LAN control) and `p2p_admin_hash` (used for
# video signaling) from that session. LAN control runs fully offline
# after setup; the cloud session is needed at runtime only for video.
CONF_CLOUD_EMAIL = "cloud_email"
CONF_CLOUD_PASSWORD = "cloud_password"
CONF_CLOUD_COUNTRY_CODE = "cloud_country_code"
# Persisted session data (populated after a successful login).
CONF_CLOUD_SID = "cloud_sid"
CONF_CLOUD_ECODE = "cloud_ecode"
CONF_CLOUD_UID = "cloud_uid"

DEFAULT_CLOUD_COUNTRY = "1"                # US

# Max entries kept in the rolling feed-log buffer attribute.
LOG_MAX_ENTRIES = 100

# HA bus event names fired on observed feed / warning transitions. The
# dashboard + HA Logbook subscribe to these. `device_id` (Tuya devId) is
# included so multi-feeder households can filter.
EVENT_FEED = "petlibro_lite_feed"
EVENT_WARNING = "petlibro_lite_warning"

# --- video / P2P admin credentials -------------------------------------------
# Device-level P2P admin user + hash (Tuya-whitelabel "admin" over KCP on
# conv=0 binary stream). Derived from the cloud session at setup time and
# refreshed on reconfigure — the user never enters them.
CONF_P2P_ADMIN_USER = "p2p_admin_user"
CONF_P2P_ADMIN_HASH = "p2p_admin_hash"
DEFAULT_P2P_ADMIN_USER = "admin"
