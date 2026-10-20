# VidHarbor – Video & MP3 Downloader for Windows

A desktop app built on **yt-dlp** (1,750+ supported sites) with extra handling for Chinese
platforms: paste a link or a whole share message, get an MP4 or MP3.

## What it does

- **Paste share text as-is.** `7.43 复制打开抖音，看看【…】 https://v.douyin.com/xxxx/` or
  `http://xhslink.com/a/xxxx，复制本条信息` – links are pulled out, short links resolved, and
  app/mobile URLs rewritten into the form yt-dlp needs.
- **Video (MP4)** up to 4K, with a "most compatible (H.264)" option, or **audio** as MP3
  (128–320 kbps, cover art + tags embedded) or M4A (no re-encode).
- **Queue** with parallel downloads, progress, speed, ETA, cancel, retry (resumes), open file.
- **Built-in browser.** Sign in to Douyin, RedNote, YouTube, Instagram, etc. once; cookies are
  saved and used automatically. It also **captures video streams** from any page you play a
  video on ("Detected media") – the fallback for sites yt-dlp can't read.
- **Automatic fresh cookies** for Douyin, RedNote and Kuaishou (loads the site invisibly first).
- **Page-scan fallback** for unsupported pages: looks for an MP4/M3U8 in the page.
- **Self-updating engine.** "Engine & tools → Update download engine" pulls the latest yt-dlp
  from PyPI without rebuilding the .exe. Sites change often; update when downloads start failing.
- Optional: auto-download links you copy, proxy, speed limit, filename template, per-platform folders.

## Platform support

| Platform | Status |
|---|---|
| 抖音 Douyin | ✅ needs fresh cookies – handled automatically |
| 小红书 RedNote | ✅ use the full share link (it carries `xsec_token`) |
| B站 Bilibili, 微博 Weibo, 西瓜 Ixigua, 头条 Toutiao, 知乎 Zhihu | ✅ |
| 优酷 Youku, 爱奇艺 iQiyi, 腾讯视频 Tencent Video, AcFun, 虎牙 Huya, 斗鱼 Douyu | ✅ (paid/VIP content excluded) |
| 快手 Kuaishou | ⚠️ experimental extractor; if blocked, use the built-in browser capture |
| 公众号 WeChat article videos | ⚠️ page scan / browser capture |
| 视频号 WeChat Channels | ❌ videos only play inside the WeChat app and are encrypted – not possible from a link |
| YouTube, TikTok, Instagram, Facebook, X, Vimeo, Reddit, SoundCloud, … | ✅ (YouTube needs Deno, installed by the build) |

## Install

Open this repository's **Releases** page and download the newest `VidHarbor-x.y.z-setup.exe`.
It installs for your user only (no admin prompt), adds Start-menu and desktop shortcuts, and
includes ffmpeg and Deno. Prefer no installer? Use `VidHarbor-x.y.z-portable.zip` instead.

Windows SmartScreen may warn the first time because the installer isn't code-signed:
click *More info → Run anyway*.

## Updating

- **The app** checks GitHub Releases at startup and shows a banner when a new version is out.
  Run the new setup over the old one – settings, sign-ins and cookies are kept.
- **The download engine** (yt-dlp) updates separately: *Engine & tools → Update download engine*.
  Do this whenever a site stops working; no new app release is needed.

## Publishing a new version (maintainer)

```
git tag v1.0.1
git push origin v1.0.1
```

The *Build Windows app* workflow builds the exe, runs the tests and a self-test, makes the
installer and portable zip, and publishes them as a release. It also stamps the version and
this repository's name into the app, so the update banner points here automatically.
You can also run the workflow by hand from the Actions tab to get a test build without releasing.

## Build locally (optional)

Install [Python 3.11+](https://www.python.org/downloads/) (tick "Add python.exe to PATH") and
double-click **`build.bat`**: it builds `dist\VidHarbor\VidHarbor.exe`, adds ffmpeg + Deno and
runs a self-test. `run_dev.bat` runs straight from source. The app folder is roughly 400 MB
because the built-in browser (Qt WebEngine) is included.

## Troubleshooting

- **Douyin: "Fresh cookies are needed"** – click *Built-in browser → 抖音*, let the page load, Retry.
- **YouTube: "Sign in to confirm you're not a bot"** – sign in to YouTube in the built-in browser.
- **Downloads suddenly fail on one site** – *Engine & tools → Update download engine*, restart.
- **"From Chrome/Edge" cookies fail** – newer Chrome/Edge encrypt cookies against other apps;
  use the built-in browser or Firefox.
- **Check an install:** `VidHarbor.exe --selftest` writes `%LOCALAPPDATA%\VidHarbor\selftest.txt`.

## Project layout

```
vidharbor/
  app.py         entry point, theme, --selftest
  ui.py          main window, settings, engine dialog
  downloader.py  yt-dlp options, worker threads, friendly errors, page-scan fallback
  linkparse.py   share-text parsing, platform detection, URL normalisation
  browser.py     built-in browser, cookie export, stream capture, cookie warm-up
  engine.py      engine self-update (PyPI wheels), ffmpeg/Deno installer, paths
  extractors.py  extra extractors (Kuaishou)
  updates.py     checks GitHub Releases for a newer app version
tests/           pytest suite for link handling
VidHarbor.spec   PyInstaller build      installer.iss  Inno Setup installer
build.bat / run_dev.bat / tools/fetch_tools.ps1   local build helpers
```

User data lives in `%LOCALAPPDATA%\VidHarbor` (engine updates, cookies.txt, browser profile).

## Licences and responsible use

- yt-dlp: Unlicense · PySide6/Qt: LGPLv3 (fine in this one-folder build) · Deno: MIT
- The bundled ffmpeg is the **GPL** build. If you distribute VidHarbor, follow the GPL for
  ffmpeg (provide its source or a written offer), or switch `fetch_tools.ps1` to an LGPL build.
- Downloading may break a platform's terms of service and copyright law. Use it for your own
  content, content you have permission to save, or personal offline viewing where that's legal.
