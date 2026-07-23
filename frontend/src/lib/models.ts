// Curated budget-friendly chat models (OpenRouter slugs).
// Slugs and prices verified against https://openrouter.ai/api/v1/models on 2026-07-23;
// prices are USD per million input/output tokens and drift over time.
export interface ModelSuggestion {
  id: string;
  label: string;
}

export const MODEL_SUGGESTIONS: ModelSuggestion[] = [
  { id: "deepseek/deepseek-v4-flash", label: "DeepSeek V4 Flash — $0.10 in / $0.20 out" },
  { id: "google/gemini-3-flash-preview", label: "Gemini 3 Flash — $0.50 in / $3.00 out" },
  { id: "openai/gpt-5-mini", label: "GPT-5 Mini — $0.25 in / $2.00 out" },
  { id: "deepseek/deepseek-v4-pro", label: "DeepSeek V4 Pro — $0.44 in / $0.87 out" },
  { id: "z-ai/glm-5", label: "GLM-5 — $0.95 in / $2.55 out" },
  { id: "moonshotai/kimi-k2.5", label: "Kimi K2.5 — $0.57 in / $2.85 out" },
  { id: "minimax/minimax-m3", label: "MiniMax M3 — $0.30 in / $1.20 out" },
  { id: "meta-llama/llama-4-maverick", label: "Llama 4 Maverick — $0.20 in / $0.80 out" },
  { id: "qwen/qwen3-coder", label: "Qwen3 Coder — $0.30 in / $1.00 out" },
  { id: "openai/gpt-oss-120b", label: "GPT-OSS 120B — $0.04 in / $0.17 out" },
  { id: "mistralai/mistral-small-3.2-24b-instruct", label: "Mistral Small 3.2 — $0.10 in / $0.30 out" },
];

export const CUSTOM_MODEL = "__custom__";
