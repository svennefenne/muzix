# Six stripes with two eighth notes (2026-11-11, briefly)

The app icons of commit 60ac129, used for a few hours on 2026-11-11: six upright
stripes in the colours of Hooden's icon on its near-black plate with the ember
glow, and across them two beamed eighth notes shown only as a colour shift (each
stripe taking the colour three along), with the beam bent into an M. They're kept
here, in the folders they belong in, so they can come back.

| Here | What it is |
| --- | --- |
| `frontend/public/favicon.svg`, `icon-192.png`, `icon-512.png`, `icon-maskable-512.png`, `apple-touch-icon.png` | the web's icons |
| `desktop/muzix_desktop/assets/icon.png`, `icon.ico`, `icons/*.png` | Muzix Desktop's icon in each size |
| `android/app/src/main/res/drawable/ic_launcher_*.xml`, `mipmap-anydpi/ic_launcher.xml` | Android's adaptive icon, with the notes alone as the themed icon |
| `unraid/muzix.png` | Unraid's Docker icon |

## Going back

From the repo's root, copy the files over the ones in use:

```sh
cp -r docs/icons/eighths/frontend docs/icons/eighths/desktop docs/icons/eighths/android docs/icons/eighths/unraid .
```

The notification icon was still the five-stripe cassette's then
(docs/icons/cassette). Raise the Android and desktop versions so the apps get the
icon, and replace Unraid's own copy of the Docker icon (see docs/icons/bars).
