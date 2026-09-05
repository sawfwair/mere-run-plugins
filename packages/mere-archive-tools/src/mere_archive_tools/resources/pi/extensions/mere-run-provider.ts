import { createProvider, openAICompletionsApi, type Model } from "@earendil-works/pi-ai/compat";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

interface MereRunModel {
  id: string;
  name?: string;
  task?: string;
  reasoning?: boolean;
  tool_call?: boolean;
  modalities?: { input: string[]; output: string[] };
  limit?: { context: number; output: number };
  openai_compat?: {
    supports_store: boolean;
    supports_developer_role: boolean;
    supports_reasoning_effort: boolean;
    supports_usage_in_streaming: boolean;
    supports_finish_reason: boolean;
    max_tokens_field: "max_tokens" | "max_completion_tokens";
    supports_strict_mode: boolean;
    requires_reasoning_content_on_assistant_messages: boolean;
  };
}

function mapModel(model: MereRunModel, baseUrl: string): Model<"openai-completions"> {
  const compat = model.openai_compat;
  return {
    id: model.id,
    name: model.name ?? model.id,
    api: "openai-completions",
    provider: "mere-run-archive",
    baseUrl,
    reasoning: model.reasoning ?? false,
    input: (model.modalities?.input ?? ["text"]).filter(
      (value): value is "text" | "image" => value === "text" || value === "image",
    ),
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: model.limit?.context ?? 8_192,
    maxTokens: model.limit?.output ?? 2_048,
    compat: compat
      ? {
          supportsStore: compat.supports_store,
          supportsDeveloperRole: compat.supports_developer_role,
          supportsReasoningEffort: compat.supports_reasoning_effort,
          supportsUsageInStreaming: compat.supports_usage_in_streaming,
          supportsFinishReason: compat.supports_finish_reason,
          maxTokensField: compat.max_tokens_field,
          supportsStrictMode: compat.supports_strict_mode,
          requiresReasoningContentOnAssistantMessages:
            compat.requires_reasoning_content_on_assistant_messages,
        }
      : undefined,
  };
}

async function discoverModels(baseUrl: string, apiKey: string, signal: AbortSignal) {
  const response = await fetch(`${baseUrl}/models`, {
    headers: { Authorization: `Bearer ${apiKey}` },
    signal,
  });
  if (!response.ok) throw new Error(`mere.run model discovery failed: HTTP ${response.status}`);
  const payload = (await response.json()) as { data?: MereRunModel[] };
  return (payload.data ?? [])
    .filter((model) => model.task === "chat.completions" && model.tool_call === true)
    .map((model) => mapModel(model, baseUrl));
}

export default async function mereRunArchiveProvider(pi: ExtensionAPI) {
  const baseUrl = process.env.MERERUN_BASE_URL ?? "http://127.0.0.1:8080/v1";
  const apiKey = process.env.MERERUN_API_KEY ?? "mere-run";
  const models = await discoverModels(baseUrl, apiKey, AbortSignal.timeout(2_000));
  pi.registerProvider(
    createProvider({
      id: "mere-run-archive",
      name: "mere.run Archive",
      baseUrl,
      auth: {
        apiKey: {
          name: "mere.run local API key",
          async resolve() {
            return { auth: { apiKey }, source: "mere.run local" };
          },
        },
      },
      models,
      async fetchModels(context) {
        return discoverModels(baseUrl, apiKey, context.signal);
      },
      api: openAICompletionsApi(),
    }),
  );
}
