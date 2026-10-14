# Shock Android Stream 0.3.0

Android host to iPad mini 1 / Safari iOS 9 over local Wi-Fi. Capture consent and the accessibility service must be enabled on Android.

## Changes

- The default page pulls one JPEG at a time and waits for image decoding before requesting the next. The producer retains only the latest encoded frame, uses acquireLatestImage, and stops encoding without demand. This bounds frame backlog; it does not guarantee a measured latency or frame rate. The legacy /stream multipart endpoint remains available and can still buffer in the network/browser.
- ES5 browser code uses explicit image dimensions, centered fit/cover sizing, and live coordinate mapping for portrait/landscape. Touch starts outside the displayed image are ignored; coordinates inside a cover-cropped image map to the original image.
- Input requests are serialized, movement is coalesced without discarding down/up/cancel, and up is dispatched before removing a finger. Five fingers and stationary holds are supported. Heartbeats retain long holds; lost clients expire after two seconds. Accessibility simulates gestures and is not equivalent to raw MotionEvent injection. Cancellation releases the simulated stroke, rather than promising a native ACTION_CANCEL. Repeated identifiers wait for the previous terminal stroke.
- Android 14 uses onCapturedContentResize to resize the existing VirtualDisplay and replace the ImageReader surface. It never calls createVirtualDisplay twice on the same projection token. Pixel endpoints are preserved across gesture continuations; normalized destination coordinates adapt to the current display.

## Build and signing

GitHub Actions builds and tests pull requests, main pushes, and manual runs. Version name is 0.3.0; local versionCode is 3, CI versionCode is 3 + the workflow run number. The previous checked-in versionCode was 2. Keep this workflow's run numbering or explicitly set a higher SHOCK_VERSION_CODE when migrating CI.

For consistent signing, configure all four repository secrets:

- SHOCK_KEYSTORE_BASE64
- SHOCK_KEYSTORE_PASSWORD
- SHOCK_KEY_ALIAS
- SHOCK_KEY_PASSWORD

The key must be the same one that signed the installed APK. A new persistent key cannot update an APK signed by a previous random runner debug key. Without the original key, an uninstall/reinstall is required and app data may be lost. No installed-certificate match has been verified. CI exports signing-certificate.txt and apk-version.txt alongside the APK so this can be checked explicitly. When no key is supplied, the artifact uses the runner debug key and is not guaranteed to update another installation.

## Validation

Run `npm install --no-save --ignore-scripts --no-package-lock acorn@8.15.0` and `node tests/browser.test.cjs` for ES5 parsing and simulated-browser regression checks. GitHub builds the APK with SDK 35 and verifies its signature. These checks do not prove physical-device behavior.

Device checks still required:

1. Tap rapidly; drag and release; hold without moving beyond two seconds; release one of two fingers while the other remains down; cancel by leaving Safari. Confirm there are no stuck fingers or accidental long presses.
2. Rotate Android repeatedly during capture and inspect logs for token reuse/security exceptions. Rotate iPad while dragging; verify fit/cover mapping at center and all four edges. The Android system itself can cancel active input on rotation.
3. Slow the Wi-Fi connection and confirm video skips old frames rather than accumulating delay. Measure actual glass-to-glass latency with a high-speed recording; no millisecond improvement is claimed without this measurement.
4. Compare installed and new APK signing-certificate SHA-256 digests and version codes before assuming an in-place update.

Do not expose the unauthenticated HTTP port 8088 to the internet or untrusted networks. Protected content may appear black. Audio is not implemented.
