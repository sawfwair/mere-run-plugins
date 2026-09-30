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

function result(payload: Record<string, unknown>, includeImage = true, compact = false) {
  const screenshot = payload.screenshot_png_b64;
  const mime = payload.screenshot_mime_type;
  delete payload.screenshot_png_b64;
  delete payload.screenshot_mime_type;
  if (compact && Array.isArray(payload.elements)) {
    const fields = ["element_token", "role", "label", "value", "selected", "enabled", "in_web_content"];
    const interactive = new Set(["AXButton", "AXCheckBox", "AXPopUpButton", "AXMenuItem", "AXTextArea", "AXTextField", "AXRadioButton", "AXComboBox"]);
    const hasWebContent = payload.elements.some((element) => typeof element === "object" && element !== null &&
      (element as { in_web_content?: boolean }).in_web_content === true);
    payload.elements = payload.elements
      .filter((element) => typeof element === "object" && element !== null &&
        interactive.has((element as { role?: string }).role ?? "") &&
        (!hasWebContent || (element as { in_web_content?: boolean }).in_web_content === true ||
          (element as { role?: string }).role === "AXMenuItem"))
      .map((element) => Object.fromEntries(fields
        .filter((field) => field in (element as Record<string, unknown>))
        .map((field) => {
          const value = (element as Record<string, unknown>)[field];
          return [field, field === "label" && typeof value === "string" ? value.slice(0, 140) : value];
        })));
    payload.element_count = payload.elements.length;
  }
  const content: ({ type: "text"; text: string } | { type: "image"; data: string; mimeType: string })[] = [
    { type: "text", text: JSON.stringify(payload) },
  ];
  if (includeImage && typeof screenshot === "string") {
    content.push({ type: "image", data: screenshot, mimeType: typeof mime === "string" ? mime : "image/png" });
  }
  return { content, details: payload };
}

async function actionAndObserve(action: string, flags: string[], lineBreaksAsSpaces = false) {
  const actionResult = await call(action, flags);
  await new Promise((resolve) => setTimeout(resolve, 250));
  const observed = await call("observe");
  observed.action_result = actionResult;
  if (lineBreaksAsSpaces) observed.line_breaks_as_spaces = true;
  return result(observed, false, true);
}

export default function desktop(pi: ExtensionAPI) {
  let observationCount = 0;
  pi.registerTool({
    name: "desktop_observe",
    label: "Observe selected window",
    description: "Get a fresh accessibility snapshot of the selected window. The first observation includes the screenshot and full text. Later observations keep concise interactive element tokens and labels but omit static text, geometry, and image to preserve context; pass full:true for page text/geometry or image:true for pixels and final visual verification. Actions return their own fresh observation.",
    parameters: Type.Object({ image: Type.Optional(Type.Boolean()), full: Type.Optional(Type.Boolean()) }),
    execute: async (_id, params) => {
      const payload = await call("observe");
      const includeImage = observationCount === 0 || params.image === true;
      observationCount += 1;
      return result(payload, includeImage, observationCount > 1 && params.full !== true);
    },
  });
  pi.registerTool({
    name: "desktop_click",
    label: "Click selected-window element",
    description: "Click an accessibility token alone, or x/y screenshot pixels with the latest snapshot ID. Returns a fresh post-click observation and tokens. In a browser, prefer the menu item marked in_web_content when a native popup shows a duplicate label; native popup tokens can belong to a different window.",
    parameters: Type.Object({
      elementToken: Type.Optional(Type.String()),
      x: Type.Optional(Type.Number()),
      y: Type.Optional(Type.Number()),
      snapshotId: Type.Optional(Type.String()),
    }),
    execute: async (_id, params) => actionAndObserve("click", [
      ...(params.elementToken ? ["--element-token", params.elementToken] : []),
      ...(params.x !== undefined ? ["--x", String(params.x)] : []),
      ...(params.y !== undefined ? ["--y", String(params.y)] : []),
      ...(params.snapshotId && !params.elementToken ? ["--snapshot-id", params.snapshotId] : []),
    ]),
  });
  pi.registerTool({
    name: "desktop_select",
    label: "Choose selected-window popup option",
    description: "For an accessibility PopUpButton from the latest observation, open it and choose one exact option in a single bounded Cua Driver sequence. Pass its element token, control label, and desired option label. The tool observes and verifies the result itself, then returns fresh interactive element tokens for the next action.",
    parameters: Type.Object({ controlToken: Type.String(), controlLabel: Type.String(), optionLabel: Type.String() }),
    execute: async (_id, params) => {
      await call("click", ["--element-token", params.controlToken]);
      await new Promise((resolve) => setTimeout(resolve, 400));
      const opened = await call("observe");
      const elements = Array.isArray(opened.elements) ? opened.elements as Record<string, unknown>[] : [];
      const matching = elements.filter((element) => element.role === "AXMenuItem" &&
        (element.value === params.optionLabel || element.label === params.optionLabel));
      const option = matching.find((element) => element.in_web_content === true) ?? matching[0];
      if (typeof option?.element_token !== "string") {
        return result({ error: `Option ${params.optionLabel} was not visible in the selected window`,
          snapshot_id: opened.snapshot_id, elements: opened.elements }, false, true);
      }
      await call("click", ["--element-token", option.element_token]);
      await new Promise((resolve) => setTimeout(resolve, 250));
      const final = await call("observe");
      const controls = Array.isArray(final.elements) ? final.elements as Record<string, unknown>[] : [];
      const control = controls.find((element) => element.role === "AXPopUpButton" && element.label === params.controlLabel);
      final.selected_control = params.controlLabel;
      final.selected_value = params.optionLabel;
      final.verified = control?.value === params.optionLabel;
      return result(final, false, true);
    },
  });
  pi.registerTool({
    name: "desktop_type",
    label: "Type in selected-window element",
    description: "Type into an accessibility token, or x/y screenshot pixels with the latest snapshot ID, in the selected window. Line breaks become spaces because the Cua Driver keyboard path drops them. Returns a fresh post-type observation and tokens.",
    parameters: Type.Object({
      elementToken: Type.Optional(Type.String()),
      x: Type.Optional(Type.Number()),
      y: Type.Optional(Type.Number()),
      snapshotId: Type.Optional(Type.String()),
      text: Type.String(),
    }),
    execute: async (_id, params) => actionAndObserve("type", [
      ...(params.elementToken ? ["--element-token", params.elementToken] : []),
      ...(params.x !== undefined ? ["--x", String(params.x)] : []),
      ...(params.y !== undefined ? ["--y", String(params.y)] : []),
      ...(params.snapshotId && !params.elementToken ? ["--snapshot-id", params.snapshotId] : []),
      "--text", params.text.replace(/\r?\n+/g, " "),
    ], /\r?\n/.test(params.text)),
  });
  pi.registerTool({
    name: "desktop_key",
    label: "Press selected-window key",
    description: "Press one key in the selected window, optionally with modifiers such as cmd for Command-S, and an element token from the latest observation.",
    parameters: Type.Object({ key: Type.String(), modifiers: Type.Optional(Type.Array(Type.String())), elementToken: Type.Optional(Type.String()) }),
    execute: async (_id, params) => actionAndObserve("key", [
      "--key", params.key,
      ...(params.elementToken ? ["--element-token", params.elementToken] : []),
      ...(params.modifiers ?? []).flatMap((modifier) => ["--modifier", modifier]),
    ]),
  });
}
