#!/bin/sh
# Copy the web app's styles, fonts and barcode scanner into the Android app's offline screens,
# so the app looks the same as the web after a design change. Run from the android folder.
set -e
here=$(cd "$(dirname "$0")" && pwd)
web="$here/../app/static"
dest="$here/app/src/main/assets/offline/static"
mkdir -p "$dest/vendor" "$dest/fonts"
cp "$web/style.css" "$web/capture.js" "$web/theme.js" "$dest/"
cp "$web/vendor/bootstrap.min.css" "$web/vendor/bootstrap.bundle.min.js" "$web/vendor/zxing.min.js" "$dest/vendor/"
cp "$web/fonts/"*.woff2 "$web/fonts/"OFL-*.txt "$dest/fonts/"
echo "Copied web assets into $dest"
