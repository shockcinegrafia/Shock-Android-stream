# Shock Android Stream v0.1 (experimental)

Android 14 host -> iPad mini 1 Safari iOS 9 via local HTTP MJPEG.

## Build
Android Studio: open this root project and build Debug APK. GitHub Actions workflow provided; uses runner Gradle (if absent, install Gradle or add wrapper).

## Use
1. Install APK on Android, connect Android and iPad to same Wi-Fi.
2. Tap Authorize Capture, approve system screen sharing.
3. Find Android local IP in Wi-Fi settings and open `http://ANDROID_IP:8088` in Safari.
4. Stop capture in the Android app.

## Scope and warnings
- Video only, no audio, no remote touch, no authentication, no encryption. **Do not expose port 8088 to internet or untrusted Wi-Fi.**
- MJPEG is CPU-intensive and may not play in Safari 9; verify on device. Frame capture is 640px wide, JPEG 55, server nominal 5 fps.
- Some games block screen capture; protected surfaces may be black.
- Capture consent required per session. No hidden capture.
- This is a first-stage proof of concept, not yet a playable game streamer.
- The screen orientation/resolution is fixed at start; restart on rotation.
- Gradle wrapper is not included; workflow installs Gradle 8.9 via setup-gradle action.
