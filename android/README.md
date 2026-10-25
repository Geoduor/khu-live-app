# KHU Live — Android app (APK / Play Store)

The Android app is a **Trusted Web Activity (TWA)**: a thin Android shell that opens the
live site full-screen, so it always shows the latest version of the web app (no separate
codebase, no re-release when the site changes).

> The Android build tools can't be downloaded in Claude's cloud workspace, so the file itself
> is built on your side. Everything else is prepared: `twa-manifest.json`, the asset-links
> template, the icons (`frontend/khu-frontend/public/icon-*.png`) and `play-listing.md`.

## The one thing to protect: your signing key
Whichever route you use, a **keystore file** is created. Google only accepts future updates
signed with the SAME key. **Back it up (two places) and never commit it to git.**
(`.gitignore` already blocks `*.keystore` / `*.jks`.)

## Option A — PWABuilder (easiest, no installs, ~10 minutes)
1. Open <https://www.pwabuilder.com>, enter `https://khu-live-app.vercel.app`, press **Start**.
2. Press **Package for stores → Android**.
3. Package ID: `app.vercel.khu_live_app.twa` · App name: `KHU Live`.
   Under *Signing key*, choose **New** and keep the generated key file safe.
4. Download the zip. It contains:
   - `*.apk` — installable file for people to download directly,
   - `*.aab` — the file you upload to Google Play,
   - `signing.keystore` + `signing-key-info.txt` — **keep these private**,
   - `assetlinks.json` — see step "Remove the address bar" below.

## Option B — Bubblewrap CLI (on a computer with Node + Java)
```bash
npm i -g @bubblewrap/cli
mkdir khu-android && cd khu-android
cp /path/to/repo/android/twa-manifest.json .
bubblewrap init --manifest=https://khu-live-app.vercel.app/manifest.json   # accepts the SDK download
bubblewrap build        # creates app-release-signed.apk and app-release-bundle.aab
bubblewrap fingerprint  # prints the SHA-256 you need below
```

## Remove the address bar (Digital Asset Links)
Without this step the app works but shows a browser bar at the top.
1. Take the **SHA-256 fingerprint** of your signing key (PWABuilder shows it; or
   `keytool -list -v -keystore <file> -alias <alias>`).
   If you publish on Google Play with *Play App Signing* (the default), also add the
   fingerprint shown in Play Console → *Setup → App signing*.
2. Copy `android/assetlinks.template.json` to
   `frontend/khu-frontend/public/.well-known/assetlinks.json` and paste the fingerprint(s).
3. Push to `main`, wait for Vercel, then check
   `https://khu-live-app.vercel.app/.well-known/assetlinks.json` opens.

## Share the APK directly (no Play Store yet)
1. Put the APK at `frontend/khu-frontend/public/khu-live.apk`, push to `main`.
2. The **"Download for Android"** button then appears automatically on
   `https://khu-live-app.vercel.app/install.html` (it hides itself until the file exists).
3. People must allow "install from this browser" once; Android shows a normal warning.
   Play Protect may say "unrecognised app" — that is expected for files outside the Play Store.

## Publish on Google Play
1. Create a Play Console account (<https://play.google.com/console>), one-time US$25, and verify identity.
2. New personal accounts must run a **closed test with at least 12 testers for 14 days**
   before production access. Create the closed-test track first and invite testers by email.
3. Create the app → upload the **.aab** → fill in the listing from `play-listing.md`.
4. Privacy policy URL: `https://khu-live-app.vercel.app/privacy.html`.
5. Content rating questionnaire (all "no"), target audience 13+ (not a children's app), data-safety form
   (see the notes in `play-listing.md`).

## Updating later
Normal site changes appear in the app automatically. Only rebuild the Android file if you
change the icon, app name or Android settings (then raise `appVersion` and upload again).
