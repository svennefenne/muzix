#!/bin/sh
# Muzix Desktop as an AppImage, from PyInstaller's folder (dist/muzix-desktop):
#   packaging/linux/build-appimage.sh <appimagetool> <runtime> <out.AppImage>
# appimagetool and the AppImage runtime come pinned from the desktop workflow.
set -eu
cd "$(dirname "$0")/../.."
tool=$1 runtime=$2 out=$3
app=build/AppDir
rm -rf "$app"
mkdir -p "$app/usr/lib"
cp -a dist/muzix-desktop "$app/usr/lib/muzix-desktop"
cp packaging/linux/AppRun "$app/AppRun"
cp packaging/linux/muzix-desktop.desktop "$app/muzix-desktop.desktop"
cp muzix_desktop/assets/icon.png "$app/muzix-desktop.png"
ln -s muzix-desktop.png "$app/.DirIcon"
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$tool" --runtime-file "$runtime" "$app" "$out"
