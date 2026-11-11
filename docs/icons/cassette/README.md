# The cassette app icon (until 2026-11-11)

Muzix's app icons before the six stripes with the two beamed eighth notes
(commit 60ac129): the cassette logo made of the five colour stripes, on a
Midnight Navy plate. They're kept here, in the folders they belong in, so they can
come back. The in-app logo is still the cassette (frontend/src/components/Logo.tsx)
and isn't part of this. Unraid's Docker icon was never the cassette: it had the
five bars until 2026-11-11 (docs/icons/bars).

| Here | What it is |
| --- | --- |
| `frontend/public/favicon.svg` | the favicon, with its own 16 px drawing |
| `frontend/public/icon-192.png`, `icon-512.png`, `icon-maskable-512.png`, `apple-touch-icon.png` | the web app's icons |
| `desktop/muzix_desktop/assets/icon.png`, `icon.ico`, `icons/*.png` | Muzix Desktop's icon, drawn for each size |
| `android/app/src/main/res/drawable/ic_launcher_foreground.xml`, `ic_launcher_monochrome.xml`, `mipmap-anydpi/ic_launcher.xml` | Android's adaptive launcher icon, on the plain `@color/muzix_bg` background |

## Going back

From the repo's root, copy the files over the ones in use and take away the
background layer that only the newer icon has:

```sh
cp -r docs/icons/cassette/frontend docs/icons/cassette/desktop docs/icons/cassette/android .
git rm android/app/src/main/res/drawable/ic_launcher_background.xml
```

Then put back the end of the docstring of `icon()` in
desktop/muzix_desktop/ui/theme.py ("16 px is Muzix's simpler drawing for that
size"), and the icon's description in DESIGN.md and PRODUCT.md (as in commit
83939fb). Raise the Android and desktop versions so the apps get the icon.
