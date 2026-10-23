# VidHarbor for Android

The Android app of VidHarbor. It downloads on the phone itself (yt-dlp, Python and ffmpeg
are built in), so it uses the phone's own internet connection and needs no PC or server.

Based on [Seal](https://github.com/JunkFood02/Seal) by JunkFood02, licensed under the
GNU GPL v3 (see `LICENSE`); this folder is distributed under the same licence.

## What VidHarbor adds to Seal

- `app/src/main/assets/ytdlp-plugins/` – yt-dlp plugins, passed to every download with
  `--plugin-dirs` (`util/VidHarborPlugins.kt`):
  - Douyin without cookies, via the mobile share page (falls back to yt-dlp's extractor)
  - short links from Chinese apps: v.douyin.com, xhslink.com, v.kuaishou.com, b23.tv
  - Kuaishou, which yt-dlp does not support
- App name, package `io.github.mike131419.vidharbor`, icon, and update checks against this
  repository's `android-v*` releases.

## Building

GitHub Actions builds it (`.github/workflows/android.yml`). Locally: JDK 21 + Android SDK,
then `./gradlew assembleGenericRelease`. Signing: see `signing/README.md`.

New version: change `currentVersion` in `buildSrc/src/main/kotlin/Version.kt` and push;
the workflow publishes the `android-vX.Y.Z` release.
