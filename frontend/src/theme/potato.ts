/** Potato mode (Settings, per device): nothing blurred, and backgrounds, skins' headlines and frames that stand
 * still. For a device that draws without a graphics card (a virtual machine), where blur and whatever moves on
 * its own have the processor redraw the window on every frame. Until the device is told otherwise, it's on
 * where the page is drawn in software. */

const SOFTWARE = /swiftshader|llvmpipe|softpipe|lavapipe|software|basic render|\bwarp\b/i;

/** Whether WebGL's renderer (its name, or null: no WebGL at all) draws without a graphics card. */
export function softwareRenderer(name: string | null): boolean {
  return name === null || SOFTWARE.test(name);
}

let found: boolean | undefined;

/** Whether this device draws the page without a graphics card: WebGL won't start without software's
 * slowness, or its renderer is software's. */
export function noGraphicsCard(): boolean {
  if (found !== undefined) return found;
  let name: string | null = null;
  try {
    const gl = document.createElement("canvas").getContext("webgl", { failIfMajorPerformanceCaveat: true });
    if (gl) {
      const info = gl.getExtension("WEBGL_debug_renderer_info");
      name = String(gl.getParameter(info ? info.UNMASKED_RENDERER_WEBGL : gl.RENDERER) || "");
      gl.getExtension("WEBGL_lose_context")?.loseContext();
    }
  } catch {
    name = null;
  }
  return (found = softwareRenderer(name));
}

const KEY = "muzix.potato";

/** The device's own choice, or null: none made here. */
export function ownChoice(): boolean | null {
  try {
    const v = localStorage.getItem(KEY);
    return v === "1" ? true : v === "0" ? false : null;
  } catch {
    return null;
  }
}

export function choose(on: boolean) {
  try {
    localStorage.setItem(KEY, on ? "1" : "0");
  } catch {
    /* private mode */
  }
}
