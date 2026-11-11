// Made by scripts/icons.py, from the app icon's measures: don't edit by hand.
// The Muzix logo's cassette (components/Logo.tsx colours it from the theme), on the icon's 512 grid.

export const VIEWBOX = [19.84, 77.04, 472.32, 373.92] as const;

/** The six stripes, the first with the notch, the last split into feet by the tape opening. */
export const STRIPES = [
  "M19.84 125.81V116.40A39.36 39.36 0 0 1 59.20 77.04H216.64L256 116.40L295.36 77.04H452.80A39.36 39.36 0 0 1 492.16 116.40V125.81Z",
  "M19.84 142.07H492.16V190.84H19.84Z",
  "M19.84 207.10H492.16V255.87H19.84Z",
  "M19.84 272.13H492.16V320.90H19.84Z",
  "M19.84 337.16H492.16V385.93H19.84Z",
  "M19.84 402.19H170.43L137.92 450.96H59.20A39.36 39.36 0 0 1 19.84 411.60ZM492.16 402.19V411.60A39.36 39.36 0 0 1 452.80 450.96H374.08L341.57 402.19Z",
];

/** The deck's outline, cut out of the stripes. */
export const RIM = "M128 167H384A69 69 0 0 1 453 236V236A69 69 0 0 1 384 305H128A69 69 0 0 1 59 236V236A69 69 0 0 1 128 167Z";

/** The deck's panel, with the window and the two reels cut out of it (even-odd). */
export const PANEL = "M128 174H384A62 62 0 0 1 446 236V236A62 62 0 0 1 384 298H128A62 62 0 0 1 66 236V236A62 62 0 0 1 128 174ZM205 197.56H307A7 7 0 0 1 314 204.56V267.44A7 7 0 0 1 307 274.44H205A7 7 0 0 1 198 267.44V204.56A7 7 0 0 1 205 197.56ZM76 236A52 52 0 1 0 180 236A52 52 0 1 0 76 236ZM332 236A52 52 0 1 0 436 236A52 52 0 1 0 332 236Z";

/** The reels' hubs, each with its middle cut out (even-odd). */
export const HUBS = ["M88 236A40 40 0 1 0 168 236A40 40 0 1 0 88 236ZM116.80 236A11.20 11.20 0 1 0 139.20 236A11.20 11.20 0 1 0 116.80 236Z", "M344 236A40 40 0 1 0 424 236A40 40 0 1 0 344 236ZM372.80 236A11.20 11.20 0 1 0 395.20 236A11.20 11.20 0 1 0 372.80 236Z"];
