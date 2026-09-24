import { execFile } from "node:child_process";
import { promisify } from "node:util";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const execFileAsync = promisify(execFile);
const executable = process.env.MERE_COMPUTER_USE_COMMAND || "mere-computer-use";
const manifest = process.env.MERE_COMPUTER_USE_MANIFEST;

async function call(action: string, flags: string[] = []): Promise<Record<string, unknown>> {
  if (!manifest) throw new Error("Launch through mere-computer-use run");
  const { stdout } = await execFileAsync(executable, ["_tool", manifest, action, ...flags], {
    maxBuffer: 32 * 1024 * 1024,
    timeout: 45_000,
  });
  return JSON.parse(stdout) as Record<string, unknown>;
}

function result(payload: Record<string, unknown>) {
  const screenshot = payload.screenshot_png_b64;
  const mime = payload.screenshot_mime_type;
  delete payload.screenshot_png_b64;
  delete payload.screenshot_mime_type;
  const content: ({ type: "text"; text: string } | { type: "image"; data: string; mimeType: string })[] = [
    { type: "text", text: JSON.stringify(payload) },
  ];
  if (typeof screenshot === "string") {
    content.push({ type: "image", data: screenshot, mimeType: typeof mime === "string" ? mime : "image/png" });
  }
  return { content, details: payload };
}

export default function desktop(pi: ExtensionAPI) {
  pi.registerTool({
    name: "desktop_observe",
    label: "Observe selected window",
    description: "Get a fresh screenshot and accessibility snapshot for the selected window. Required before every action and after the final action.",
    parameters: Type.Object({}),
    execute: async () => result(await call("observe")),
  });
  pi.registerTool({
    name: "desktop_click",
    label: "Click selected-window element",
    description: "Click an accessibility token, or x/y screenshot pixels with the latest capture ID, in the selected window.",
    parameters: Type.Object({
      elementToken: Type.Optional(Type.String()),
      x: Type.Optional(Type.Number()),
      y: Type.Optional(Type.Number()),
      captureId: Type.Optional(Type.String()),
    }),
    execute: async (_id, params) => result(await call("click", [
      ...(params.elementToken ? ["--element-token", params.elementToken] : []),
      ...(params.x !== undefined ? ["--x", String(params.x)] : []),
      ...(params.y !== undefined ? ["--y", String(params.y)] : []),
      ...(params.captureId ? ["--capture-id", params.captureId] : []),
    ])),
  });
  pi.registerTool({
    name: "desktop_type",
    label: "Type in selected-window element",
    description: "Type into an accessibility token, or x/y screenshot pixels with the latest capture ID, in the selected window.",
    parameters: Type.Object({
      elementToken: Type.Optional(Type.String()),
      x: Type.Optional(Type.Number()),
      y: Type.Optional(Type.Number()),
      captureId: Type.Optional(Type.String()),
      text: Type.String(),
    }),
    execute: async (_id, params) => result(await call("type", [
      ...(params.elementToken ? ["--element-token", params.elementToken] : []),
      ...(params.x !== undefined ? ["--x", String(params.x)] : []),
      ...(params.y !== undefined ? ["--y", String(params.y)] : []),
      ...(params.captureId ? ["--capture-id", params.captureId] : []),
      "--text", params.text,
    ])),
  });
  pi.registerTool({
    name: "desktop_key",
    label: "Press selected-window key",
    description: "Press one key in the selected window, optionally addressing a token from the latest observation.",
    parameters: Type.Object({ key: Type.String(), elementToken: Type.Optional(Type.String()) }),
    execute: async (_id, params) => result(await call("key", ["--key", params.key, ...(params.elementToken ? ["--element-token", params.elementToken] : [])])),
  });
}
