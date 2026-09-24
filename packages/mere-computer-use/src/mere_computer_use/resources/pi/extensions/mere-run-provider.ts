import { createProvider, openAICompletionsApi, type Model } from "@earendil-works/pi-ai/compat";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

interface MereRunModel {
  id: string;
  name?: string;
  task?: string;
  reasoning?: boolean;
  tool_call?: boolean;
  modalities?: { input: string[] };
  limit?: { context: number; output: number };
  openai_compat?: {
    supports_store: boolean;
    supports_developer_role: boolean;
    supports_reasoning_effort: boolean;
    supports_usage_in_streaming: boolean;
    supports_finish_reason: boolean;
    max_tokens_field: "max_tokens" | "max_completion_tokens";
    supports_strict_mode: boolean;
    thinking_format?: "qwen" | "zai" | "deepseek";
    thinking_level_map?: Record<string, string | null>;
    requires_reasoning_content_on_assistant_messages: boolean;
  };
}

async function discover(baseUrl: string, apiKey: string, signal: AbortSignal): Promise<Model<"openai-completions">[]> {
  const response = await fetch(`${baseUrl}/models`, {
    headers: { Authorization: `Bearer ${apiKey}` }, signal,
  });
  if (!response.ok) throw new Error(`mere.run model discovery failed: HTTP ${response.status}`);
  const payload = (await response.json()) as { data?: MereRunModel[] };
  return (payload.data ?? [])
    .filter((model) => model.task === "chat.completions" && model.tool_call === true &&
      model.modalities?.input.includes("image"))
    .map((model) => {
      const compat = model.openai_compat;
      return {
        id: model.id,
        name: model.name ?? model.id,
        api: "openai-completions" as const,
        provider: "mere-run-computer-use",
        baseUrl,
        reasoning: model.reasoning ?? false,
        thinkingLevelMap: compat?.thinking_level_map,
        input: ["text", "image"] as ("text" | "image")[],
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
        contextWindow: model.limit?.context ?? 8_192,
        maxTokens: Math.min(model.limit?.output ?? 2_048, 4_096),
        compat: compat ? {
          supportsStore: compat.supports_store,
          supportsDeveloperRole: compat.supports_developer_role,
          supportsReasoningEffort: compat.supports_reasoning_effort,
          supportsUsageInStreaming: compat.supports_usage_in_streaming,
          supportsFinishReason: compat.supports_finish_reason,
          maxTokensField: compat.max_tokens_field,
          supportsStrictMode: compat.supports_strict_mode,
          thinkingFormat: compat.thinking_format,
          requiresReasoningContentOnAssistantMessages: compat.requires_reasoning_content_on_assistant_messages,
        } : undefined,
      };
    });
}

export default async function mereRunComputerUseProvider(pi: ExtensionAPI) {
  const baseUrl = process.env.MERERUN_BASE_URL ?? "http://127.0.0.1:8080/v1";
  const apiKey = process.env.MERERUN_API_KEY ?? "mere-run";
  const models = await discover(baseUrl, apiKey, AbortSignal.timeout(3_000));
  pi.registerProvider(createProvider({
    id: "mere-run-computer-use",
    name: "mere.run Computer Use",
    baseUrl,
    auth: { apiKey: {
      name: "mere.run local API key",
      async resolve() { return { auth: { apiKey }, source: "mere.run local" }; },
    } },
    models,
    async fetchModels(context) { return discover(baseUrl, apiKey, context.signal); },
    api: openAICompletionsApi(),
  }));
}
