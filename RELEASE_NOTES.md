# Wallpaper changer — 7.41f+Trove_of_Terror

Native Qt 6 desktop application for Dota 2 menu video backgrounds and fonts.

- One interface on Windows and Linux, without Quickshell or Python installation on Windows.
- `.exe` per-user installer and portable Windows ZIP, with FFmpeg and the Python backend bundled.
- `.deb` for Debian 12+/Ubuntu 24.04+, `.rpm` for recent Fedora, and a Linux archive for Omarchy/Arch.
- `wallpaper-changer` terminal command and application-menu entry.
- Video library, previews, automatic MP4 → VP9/WebM conversion and monitor stretching.
- Current Trove of Terror scene fix and reversible font switches.
- Automatic Omarchy palette when available; dark theme on other desktops.
- English UI language preserved; recognized audio-language layer used for game resources.

Linux packages require system Qt 6.4+, Python 3.10+, FFmpeg and LZ4. Package managers install
the declared dependencies. Fedora's optional proprietary codecs may require a fuller FFmpeg
build for some input videos. Windows 10 1809+ x64 is supported by the packaged Qt version.

Game resources, videos and third-party background templates are not included. The app downloads
the base template on first use; a compatible local template can also be selected in Settings.

Installers and checksums are published only after both Linux and Windows build/test jobs pass.
The version label records the intended Dota/event baseline, not a guarantee for future patches.
