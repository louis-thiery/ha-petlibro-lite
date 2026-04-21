# Capturing the P2P admin hash

The camera platform needs a 32-character hex md5 hash that the feeder was provisioned with at pairing. The hash is:

- Per-device and permanent. Capture it once and keep it as long as the feeder stays paired to the same Tuya account.
- Not exposed by any Tuya cloud endpoint probed so far (~45 actions × 4 API versions — `smartlife.m.p2p.*`, `thing.m.ipc.password.get`, `tuya.m.ipc.p2p.config.get`, etc.).
- Not derivable from your email, password, devId, or localKey.

The only method I know today is Frida instrumentation of the PetLibro Lite mobile app. If that's not something you want to set up, skip this page — everything else in the integration works without the hash.

## What you need

- Android device (physical or emulator) with the PetLibro Lite app installed and signed into the same Tuya account that owns the feeder. Emulator is easier, see the AVD recipe below.
- `adb` (Android platform-tools). [install guide](https://developer.android.com/studio/command-line/adb)
- `frida-tools` via `pip install frida-tools` (tested with 17.x).
- `frida-server` matching your Android architecture, copied to `/data/local/tmp/frida-server` on the device and made executable.
- Root on the device. A `google_apis` (dev-keyed) emulator image gives you this for free; a physical phone needs a rooted OS.

## Step by step

1. Start frida-server on the device:
   ```sh
   adb root
   adb shell "pkill frida-server; /data/local/tmp/frida-server &"
   ```

2. Force-stop the app so a fresh launch pulls the session:
   ```sh
   adb shell am force-stop com.dl.petlibro
   ```

3. Launch the app under Frida with SSL pinning bypass. Any maintained unpin script works — [objection](https://github.com/sensepost/objection) exposes a one-liner, or you can use a standalone Frida script like [frida-android-unpinning](https://codeshare.frida.re/@pcipolloni/universal-android-ssl-pinning-bypass-with-frida/). The script also needs to hook SecureNativeApi methods used by the PetLibro Lite app so the Tuya cert pinning falls through.
   ```sh
   frida -U -f com.dl.petlibro \
     -l frida_unpin.js \
     --runtime=v8 > /tmp/frida_capture.log 2>&1 &
   ```

4. In the app, open the feeder's camera tab. This triggers the `rtc.session.offer` call that exchanges the admin credentials with the device. The Frida log will capture the `sessionId`, `aesKey`, `tcpRelay.credential`, and the admin hash.

5. Grep the Frida log for the admin user block:
   ```sh
   grep -A2 '"admin"' /tmp/frida_capture.log
   ```
   You should see something like:
   ```
   "admin": {
     "username": "admin",
     "password": "1a2b3c4d5e6f7890abcdef1234567890"
   }
   ```
   The 32-char hex string is the hash. Copy it.

6. Paste into Home Assistant:
   - Settings → Devices & Services → PetLibro Lite → Configure
   - Paste the hash into the "P2P admin hash" field. Leave "P2P admin user" as `admin` unless your app session shows otherwise.
   - Save. HA reloads the integration and the camera entity appears.

## Android emulator (AVD) recipe

If you don't want to root a physical phone, an emulator is the easier path.

```sh
# Install Android cmdline-tools + an API 33 arm64 system image. x86_64
# works too; arm64 matches macOS Apple Silicon.
brew install --cask android-commandlinetools
sdkmanager "platform-tools" "emulator" "system-images;android-33;google_apis;arm64-v8a"

avdmanager create avd -n petlibro_re -k "system-images;android-33;google_apis;arm64-v8a"

emulator -avd petlibro_re -no-window -no-audio -no-snapshot -no-boot-anim \
  -gpu swiftshader_indirect &

# Wait ~30s for boot, then:
adb root
adb shell setenforce 0

# Side-load PetLibro Lite from an APK file you supply:
adb install petlibro-lite.apk

# Copy frida-server (arm64 matches the AVD):
adb push frida-server-17.x-android-arm64 /data/local/tmp/frida-server
adb shell chmod +x /data/local/tmp/frida-server
```

## Troubleshooting

- **Frida can't connect.** `adb root` failed silently. Confirm your AVD uses a `google_apis` image, not `google_play` (production-signed, root is blocked).
- **App closes immediately under Frida.** The unpin script threw. Check `/tmp/frida_capture.log`; a missing method signature usually means the app version drifted, so update the class names in the unpin script.
- **`rtc.session.offer` never fires.** The app sometimes needs a clean state. Run `adb shell pm clear com.dl.petlibro`, sign in again, then repeat from step 3.
- **Hash is correct but the camera still doesn't stream.** Most commonly leading/trailing whitespace on paste. Strip it.

## Security

The admin hash is a per-device secret. Treat it like a localKey: don't paste it into shared chats, don't commit it, don't post screenshots of the Configure dialog without redacting. If the feeder is factory-reset and re-paired, capture a new hash — the old one won't work.

## Plans

The long-term fix is auto-fetching the hash from Tuya cloud — no endpoint we've probed returns it so far. Tracks on deck: deeper sweeps of the `thing.m.*` cloud namespace, the LAN `LAN_EXT_STREAM` (cmd `0x40`) register path, and as a last resort a packaged hash-capture helper CLI that wraps the Frida steps below.
