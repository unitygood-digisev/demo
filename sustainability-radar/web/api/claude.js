// GET  /api/claude -> { ok }：告訴頁面 AI 是否可用
// POST /api/claude { input, tier } -> { text, truncated } 或 { code, error }
import Anthropic from "@anthropic-ai/sdk";
const client = new Anthropic(); // 從 Vercel 環境變數讀取 ANTHROPIC_API_KEY
const MAX_CHARS = 16000;
const SYSTEM =
  "你是「永續情報雷達」的 AI 永續情報官，只處理台灣與國際永續、ESG、碳管理相關任務：解讀法規與新聞、" +
  "整理碳價與市場數據、撰寫週報、回答有引用來源的問題。一律使用繁體中文與台灣用語。" +
  "只能使用使用者提供的資料，不可編造數字；資料不足時要明說。與永續情報無關的請求，請簡短婉拒。";
function toMessages(input) {
  if (typeof input === "string") return input.trim() ? [{ role: "user", content: input }] : [];
  if (Array.isArray(input)) return input.filter(m => (m?.role === "user" || m?.role === "assistant") && typeof m.content === "string" && m.content).map(m => ({ role: m.role, content: m.content }));
  return [];
}
export default async function handler(req, res) {
  if (req.method === "GET") return res.status(200).json({ ok: Boolean(process.env.ANTHROPIC_API_KEY) });
  if (req.method !== "POST") return res.status(405).json({ code: "bad_request", error: "Use POST" });
  const messages = toMessages(req.body?.input);
  const size = messages.reduce((n, m) => n + m.content.length, 0);
  if (!messages.length || messages[0].role !== "user" || messages.at(-1).role !== "user" || size > MAX_CHARS)
    return res.status(400).json({ code: "bad_request", error: "Input must be 1-16000 chars and start and end on a user turn" });
  try {
    const msg = await client.beta.messages.create({
      model: "claude-opus-5-5", max_tokens: 8000,
      output_config: { effort: req.body?.tier === "quick" ? "low" : "medium" },
      betas: ["server-side-fallback-2026-07-01"], fallbacks: "default",
      system: SYSTEM, messages,
    });
    if (msg.stop_reason === "refusal") return res.status(422).json({ code: "refused", error: "Declined" });
    const text = msg.content.filter(b => b.type === "text").map(b => b.text).join("").trim();
    if (!text) return res.status(502).json({ code: "empty_completion", error: "No text returned" });
    return res.status(200).json({ text, truncated: msg.stop_reason === "max_tokens" });
  } catch (err) {
    if (err instanceof Anthropic.RateLimitError) return res.status(429).json({ code: "rate_limited", error: err.message });
    if (err instanceof Anthropic.BadRequestError) return res.status(400).json({ code: "bad_request", error: err.message });
    if (err instanceof Anthropic.AuthenticationError) return res.status(500).json({ code: "upstream_error", error: "API key is missing or invalid" });
    if (err instanceof Anthropic.APIError) return res.status(502).json({ code: "upstream_error", error: err.message });
    return res.status(500).json({ code: "upstream_error", error: String(err) });
  }
}
