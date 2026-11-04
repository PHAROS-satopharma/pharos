// telegram-webhook — Telegram calls this for every message to the bot.
// Only requests carrying the secret token set with setWebhook are accepted (header
// X-Telegram-Bot-Api-Secret-Token). `/start <code>` links the chat to the person who created the code
// (create_link_token RPC); a reused, expired or unknown code is politely refused; anything else gets the help
// text. Replies go back in the webhook response itself, so this function never holds the bot token, and no
// reply ever contains internal data (names, issues, comments).
import { serviceClient } from "../_shared/supabase.ts";

const enc = new TextEncoder();

const TEXT = {
  linked:
    "Your Telegram is now linked to PHAROS. Safety notices for the ingredients you follow will arrive in this chat.",
  alreadyLinked: "This Telegram chat is already linked to your PHAROS account. Nothing else to do.",
  otherPerson:
    "This Telegram chat is already linked to another PHAROS account. Ask your administrator to move it.",
  refused:
    "This link code cannot be used. It may have been used already or be more than 24 hours old. Open PHAROS and create a new Telegram link.",
  help:
    "This is the PHAROS bot. To link your account, open PHAROS, choose Link Telegram, and press Start here. The bot does not answer questions.",
};

function safeEqual(a: string, b: string): boolean {
  const x = enc.encode(a);
  const y = enc.encode(b);
  if (x.length !== y.length || x.length === 0) return false;
  let diff = 0;
  for (let i = 0; i < x.length; i++) diff |= x[i] ^ y[i];
  return diff === 0;
}

async function sha256Hex(s: string): Promise<string> {
  const d = await crypto.subtle.digest("SHA-256", enc.encode(s));
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function reply(chatId: number, text: string): Response {
  return new Response(JSON.stringify({ method: "sendMessage", chat_id: chatId, text }), {
    headers: { "Content-Type": "application/json" },
  });
}

const ok = () => new Response("ok");

interface Update {
  message?: { chat?: { id?: number; type?: string }; text?: string };
}

async function linkChat(chatId: number, code: string): Promise<string> {
  if (!/^[A-Za-z0-9_-]{24}$/.test(code)) return TEXT.refused;
  const svc = serviceClient();
  const hash = await sha256Hex(code);
  const nowIso = new Date().toISOString();

  const { data: token } = await svc
    .from("link_token")
    .select("person_id")
    .eq("token_hash", hash)
    .is("used_at", null)
    .gt("expires_at", nowIso)
    .maybeSingle();
  if (!token) return TEXT.refused;

  const { data: person } = await svc
    .from("person")
    .select("id, active")
    .eq("id", token.person_id)
    .maybeSingle();
  if (!person?.active) return TEXT.refused;

  const { data: holder } = await svc.from("person").select("id").eq("telegram_chat_id", chatId).maybeSingle();
  if (holder && holder.id !== person.id) return TEXT.otherPerson;

  // Consume the code atomically: only one request can flip used_at from null.
  const { data: used } = await svc
    .from("link_token")
    .update({ used_at: nowIso })
    .eq("token_hash", hash)
    .is("used_at", null)
    .gt("expires_at", nowIso)
    .select("person_id");
  if (!used || used.length !== 1) return TEXT.refused;

  if (holder) return TEXT.alreadyLinked;

  const { error } = await svc
    .from("person")
    .update({ telegram_chat_id: chatId, telegram_linked_at: nowIso })
    .eq("id", person.id);
  if (error) {
    console.error("link person", error.code, error.message);
    return error.code === "23505" ? TEXT.otherPerson : TEXT.refused;
  }
  return TEXT.linked;
}

Deno.serve(async (req) => {
  if (req.method !== "POST") return new Response("Method not allowed", { status: 405 });

  const expected = Deno.env.get("TELEGRAM_WEBHOOK_SECRET") ?? "";
  const got = req.headers.get("X-Telegram-Bot-Api-Secret-Token") ?? "";
  if (!safeEqual(got, expected)) return new Response("Unauthorized", { status: 401 });

  let update: Update;
  try {
    update = await req.json();
  } catch {
    return ok();
  }

  const chat = update.message?.chat;
  const text = (update.message?.text ?? "").trim();
  // Private chats only; group messages, edits, channel posts and button callbacks are ignored.
  if (!chat?.id || chat.type !== "private" || !text) return ok();

  const m = text.match(/^\/start(?:@\w+)?(?:\s+(\S+))?\s*$/);
  if (m && m[1]) {
    try {
      return reply(chat.id, await linkChat(chat.id, m[1]));
    } catch (e) {
      console.error(e);
      return reply(chat.id, TEXT.refused);
    }
  }
  return reply(chat.id, TEXT.help);
});
