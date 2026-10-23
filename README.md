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

## Android app

Downloads on the phone itself, so Douyin, RedNote, YouTube and TikTok see an ordinary
phone connection; no PC or server needed. (iPhone can't install apps this way.)

1. On the phone, open **Releases** on this page and find the newest **VidHarbor Android**.
2. Download **VidHarbor-x.y.z-arm64-v8a.apk** (or the *universal* one if that won't install) and tap it.
3. Allow your browser to install apps when Android asks, then tap **Install**.

Share a video from Douyin, RedNote, TikTok or YouTube → **VidHarbor**, or paste a link in the
app. The app offers new versions itself. Source and details: [`android/`](android/).

## Web app for phones – no PC needed

Run VidHarbor as a website that you and your friends open on any iPhone or Android phone.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/mike131419/vidharbor)

**Set up (once, about 5 minutes)**
1. Click **Deploy to Render** above and sign in with GitHub. No credit card is needed for the free plan.
2. Render asks for **VIDHARBOR_CODE**. Type the access code friends will use, e.g. `MIKE-2026-VIDS`.
3. Click **Deploy** and wait for "Live" (the first build takes a few minutes).
4. Your link is shown at the top, like `https://vidharbor-xxxx.onrender.com`. Send it and the code to friends.

**Using it:** open the link (iPhone: in Safari), enter the code once, then **Share → Add to Home Screen**.
Copy a link in Douyin, RedNote or any app → open VidHarbor → **Paste → Download → Save video**.

**Good to know (free plan)**
- After 15 minutes with nobody using it, the server sleeps. The next visit shows "Waking up the
  server…" for up to a minute, then works normally.
- Files are wiped when the server sleeps or restarts, so save them when they're ready.
- yt-dlp updates itself every time the server starts, so fixes for sites arrive automatically.
- Render's paid Starter plan ($7/month) stays awake all the time; change it under the service's Settings.
- Some sites block cloud servers. If YouTube says "confirm you're not a bot", add a
  **VIDHARBOR_COOKIES** environment variable in Render with cookies exported from a browser
  (cookies.txt format); a spare account is safest.
- Other hosts work too: `docker build -t vidharbor . && docker run -p 8787:8787 -e VIDHARBOR_CODE=... vidharbor`.

## Phone access through your PC (optional)

VidHarbor on your PC can also serve a **phone app** (a web app you add to the Home Screen).
Phones send links to your PC; the PC downloads them and the phone saves the result.
Meant for you and a few friends – everyone shares one access code.

**Set up on the PC (once)**
1. Click **Phone access → Start phone access**. Tick *Start when VidHarbor opens*.
2. For use **anywhere** (and so iPhones can install it as an app), click **Turn on internet link**.
   This uses [Tailscale](https://tailscale.com/download/windows) Funnel (free): install Tailscale on
   the PC, sign in, and approve Funnel the first time if it asks. Friends install nothing extra.
   Without it, the plain link works on your home Wi-Fi only.
3. Send friends the **link** (or let them scan the QR code) and the **access code**.

**On the iPhone**
1. Open the link in **Safari**, enter the access code.
2. Tap **Share → Add to Home Screen**, open VidHarbor from the Home Screen and enter the code once more
   (the Home Screen app keeps its own sign-in).
3. To download: in Douyin, RedNote or any app tap **Share → Copy link** → open VidHarbor → **Paste**
   → **Download** → **Save video** → *Save Video* (goes to Photos). MP3s: **Save to Files**.

Android phones work the same way in Chrome (*Add to Home screen*), and can also share links
straight to VidHarbor from the share sheet.

**Good to know**
- The PC must be on with VidHarbor open. *Keep this PC awake* stops it sleeping while phone access is on.
- Friends' downloads use your PC's internet connection and your VidHarbor sign-ins (cookies).
- Files are removed from the PC a few hours after they finish.
- **New code** signs every phone out. Use it if the code ends up with someone it shouldn't.
- No PC to leave on? `VidHarbor.exe --server --port 8787 --code YOUR-CODE` runs only the phone
  part, and `python -m vidharbor.server` does the same on Linux. Many sites block downloads from cloud servers, though, so a home computer works best.

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

On GitHub: **Actions → Build Windows app → Run workflow**, type the new version (e.g. `1.0.1`)
and click *Run workflow*. (Pushing a tag such as `v1.0.1` does the same.)

The workflow builds the exe, runs the tests and a self-test, makes the installer and portable
zip, creates the `v1.0.1` tag and publishes them as a release. It also stamps the version and
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
  extractors.py  extra extractors (Kuaishou, Douyin share-page fallback)
  updates.py     checks GitHub Releases for a newer app version
  core.py        download engine wrapper shared by the desktop and the phone server
  server.py      phone access web server (sign-in, jobs, file streaming)
  cloud.py       entry point for the hosted web app (env settings, yt-dlp auto-update)
  phone.py       Phone access dialog, Tailscale Funnel, QR code
  web/           the phone app (PWA): index.html, app.js, styles.css, sw.js, icons
tests/           pytest suites: link handling, phone server, Douyin fallback; cloud_probe.py
Dockerfile, render.yaml, requirements-server.txt   the hosted web app
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
