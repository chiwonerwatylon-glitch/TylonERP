# TylonERP for Android

An Android app (Android 7.0 and later, up to Android 15) for TylonERP.

- **Online** it shows the full TylonERP web app, so every feature works exactly as on the web: Quick sell, stock,
  sales, receipts, debtors, members, payments and settings. Camera scanning, photo uploads, printing and file
  downloads work inside the app.
- **Offline** it switches by itself to screens built into the app. You can sell (cash, OneMoney, credit), count stock
  by barcode, register products, add clients and record debtor payments. Everything is saved on the phone first.
- **Sync**: when the phone is online again, it uploads what was saved to your TylonERP server and its Postgres
  database, then downloads fresh stock levels. This also happens in the background, even with the app closed.
  Every saved change has its own id, so an upload that is cut off and retried never records anything twice.

## Build it in Android Studio

1. Install Android Studio (Ladybug 2024.2 or newer) with the Android SDK Platform 35. Studio offers to install
   anything missing.
2. **File > Open** and choose this `android` folder (not the repository root).
3. Open `gradle.properties` and set `tylonServerUrl` to your server, for example
   `tylonServerUrl=https://your-app.up.railway.app`. People can also change it on the phone's sign-in screen.
4. Wait for **Gradle sync** to finish. The first time, it downloads Gradle 8.10.2 and the Android build plugin.
5. Plug in a phone with USB debugging on (or start an emulator) and press **Run**.
6. To get an APK file: **Build > Build App Bundle(s) / APK(s) > Build APK(s)**. The debug APK lands in
   `app/build/outputs/apk/debug/`. For the Play Store or wide distribution, use
   **Build > Generate Signed App Bundle / APK** and keep your signing key safe.

The server must run TylonERP 1.10.0 or later, which adds the phone API (`/api/v1/...`).

### Trying it against a server on your computer

A debug build may use plain `http`. On the Android emulator your computer is `10.0.2.2`, so run the server with
`make run` and enter `http://10.0.2.2:8080` as the server address on the phone. Release builds only use `https`.

## Using the app

1. Sign in with your business name (the part after `/t/` in your sign-in link, or paste the whole link), your
   email and your password. Administrator console accounts cannot sign in on the phone.
2. With a connection, the full web app opens. Without one, the offline screens open. A green bar says when the
   connection is back, with **Open full app**.
3. **Changes** (offline screens) lists everything saved on the phone and whether it reached the server. A change
   the server could not accept (for example, a product that was deleted on the web meanwhile) is shown with the
   reason, and stock levels follow the server after the next sync.

Offline, these need a connection and are only in the full app: EcoCash payments, registering products by photo or
scent, importing stock lists, members, payment settings and the login page settings.

**Sign out of this phone** (under Changes) refuses while changes are still waiting to upload, unless you confirm
that they may be deleted.

## How it is built

Plain Java and Android's own APIs, with no third-party libraries, so the build only needs the Android Gradle plugin.

| File | What it does |
|---|---|
| `MainActivity.java` | The web view: online web app or offline screens, camera and file permissions, downloads, back button, edge-to-edge layout |
| `Store.java` | SQLite on the phone: products, clients, open debts, and the queue of changes waiting to upload |
| `SyncManager.java` | Uploads the queue in batches, records each result, refreshes the phone's copy |
| `SyncJobService.java` | Background uploads when a connection appears, and an hourly refresh |
| `Bridge.java` | What the pages can ask the phone to do. Data calls only answer the app's own offline pages |
| `Api.java`, `Prefs.java`, `Printer.java` | Server calls, settings, printing through Android's print service |
| `assets/offline/` | The offline screens, using the same styles, fonts and barcode scanner as the web app |

When the web app's look changes, copy its styles into the app with `./sync-web-assets.sh`.
