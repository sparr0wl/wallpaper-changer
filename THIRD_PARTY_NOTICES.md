# Third-party components

Wallpaper changer uses Qt 6 through dynamically linked libraries. Qt Core, GUI, QML,
Quick, Quick Controls, Network and Multimedia are available under their applicable
Qt open-source licenses, including LGPLv3. Qt is developed by The Qt Company and
contributors. https://www.qt.io/licensing/open-source-lgpl-obligations

Windows packages keep Qt DLLs and plugins separate so they can be replaced. The
release includes Qt's license files and the precise Qt source release URL. Source
for Qt 6.8.3 is at https://download.qt.io/archive/qt/6.8/6.8.3/single/ .

The Windows backend bundles Python, PyInstaller and python-lz4. Their license files
are included in the backend's distribution metadata. Python: PSF License;
PyInstaller: GPL with its bootloader exception; python-lz4: BSD-3-Clause.

Windows packages include FFmpeg/ffprobe from the Chocolatey FFmpeg package. FFmpeg
is developed by the FFmpeg contributors and uses LGPL/GPL licenses according to
the selected build. The workflow retains the distributor's license files and the
build configuration. Sources and build instructions: https://ffmpeg.org/ and
https://github.com/GyanD/codexffmpeg . Linux packages use distribution-provided
FFmpeg and Qt rather than bundling them.

Dota 2, Valve's game files, event artwork and third-party background templates
belong to their respective authors. They are not part of these source or binary
packages. No affiliation with Valve or Omarchy is implied.
