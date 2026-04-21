<p align="center">
  <img src="docs/images/card-video-dark.png" alt="PetLibro Lite Lovelace card with live video" width="360">
</p>

PetLibro Lite is a Home Assistant integration for **already-paired** PetLibro smart feeders (PLAF203 and other models that use the **PetLibro Lite** mobile app — the Tuya-whitelabel one). It runs entirely over LAN for every non-video feature. Optional live video requires additional credentials (PetLibro Lite account email/password and a P2P admin hash) but nothing else does.

**This is not a replacement for the popular `petlibro` community integration.** Feeders that use the main "PetLibro" app use a different cloud API and need that integration instead. This integration is for the subset of feeders on the "Lite" Tuya-whitelabel stack.

Initial pairing must be done with the PetLibro Lite mobile app — this integration cannot onboard a factory-fresh feeder. After pairing, extract `device_id` + `local_key` (tinytuya scan works) and configure via the HA UI.

See the README for setup, supported features, and the video-stream caveat.
