// Potato mode's own guess (src/theme/potato.ts): on by itself where the page is drawn without a graphics card.
import assert from "node:assert/strict";
import { test } from "node:test";
import { softwareRenderer } from "../src/theme/potato.ts";

test("drawn in software: a virtual machine's, or no WebGL at all", () => {
  for (const name of [
    "ANGLE (Microsoft, Microsoft Basic Render Driver (0x0000008C) Direct3D11 vs_5_0 ps_5_0, D3D11)",
    "ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) (0x0000C0DE)), SwiftShader driver)",
    "Google SwiftShader",
    "llvmpipe (LLVM 19.1.7, 256 bits)",
    "Apple Software Renderer",
    null,
  ]) assert.equal(softwareRenderer(name), true, String(name));
});

test("a graphics card's", () => {
  for (const name of [
    "ANGLE (NVIDIA, NVIDIA GeForce RTX 3070 Ti (0x00002207) Direct3D11 vs_5_0 ps_5_0, D3D11)",
    "ANGLE (Intel, Intel(R) UHD Graphics 770 (0x00004680) Direct3D11 vs_5_0 ps_5_0, D3D11)",
    "Mesa Intel(R) UHD Graphics 770 (ADL-S GT1)",
    "NVIDIA GeForce RTX 3070 Ti/PCIe/SSE2",
    "Adreno (TM) 740",
    "Apple M2",
  ]) assert.equal(softwareRenderer(name), false, name);
});
