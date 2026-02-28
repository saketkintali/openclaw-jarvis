import { spawn } from "child_process";
import * as path from "path";
import * as fs from "fs";

const LOG = path.join(
  process.env["USERPROFILE"] ?? ".",
  ".openclaw", "workspace", "text-handler.log"
);

const log = (msg: string) => {
  fs.appendFileSync(LOG, `[${new Date().toISOString()}] ${msg}\n`);
};

const handler = async (event: any) => {
  // Log every event to diagnose what's firing
  if (event.type === "message" && event.action === "received") {
    log(`EVENT keys=${Object.keys(event).join(",")}`);
    log(`EVENT.context=${JSON.stringify(event.context ?? {})}`);
    log(`EVENT.message=${JSON.stringify(event.message ?? {})}`);
    log(`EVENT.data=${JSON.stringify(event.data ?? {})}`);
  }

  if (event.type !== "message" || event.action !== "received") return;
  if (event.context?.channelId !== "whatsapp") return;

  // Skip messages sent by the bot itself
  if (event.message?.fromMe === true) return;
  if (event.context?.fromMe === true) return;
  if (event.context?.fromSelf === true) return;
  if (event.context?.direction === "outbound") return;

  // Text lives in event.context.content for WhatsApp messages
  const text: string = (
    event.context?.content ||
    event.message?.text ||
    event.message?.body ||
    ""
  ).toString().trim();

  log(`TEXT: "${text.slice(0, 80)}"`);

  if (!text) return;

  // Skip if it looks like a file path or media placeholder (audio hook territory)
  if (/\.(ogg|opus|oga|mp3|m4a|wav)$/i.test(text)) return;
  if (text.startsWith("<media:")) return;

  // Skip our own 🎙️ replies to avoid feedback loops
  if (text.startsWith("🎙️") || text.startsWith("[openclaw]")) return;

  const scriptPath = path.join(
    process.env["USERPROFILE"] ?? ".",
    ".openclaw",
    "workspace",
    "check_text.py"
  );

  log(`SPAWNING check_text.py with: "${text.slice(0, 80)}"`);

  await new Promise<void>((resolve) => {
    const child = spawn("python", [scriptPath, text], { stdio: "pipe" });

    child.stdout?.on("data", (d: Buffer) => log(`PY: ${d.toString().trim()}`));

    child.on("close", (code: number | null) => {
      log(`check_text.py exit=${code}`);
      if (code !== 0) {
        // Not a structured query — LLM is handling it, send ack
        const from: string = event.context?.from || "";
        if (from) {
          log(`Sending ack to ${from}`);
          try {
            const ack = spawn("openclaw.cmd", [
              "message", "send",
              "--channel", "whatsapp",
              "--target", from,
              "--message", "⏳ On it...",
            ], { shell: true, stdio: "ignore" });
            ack.unref();
          } catch (e) {
            log(`Ack send error: ${e}`);
          }
        }
      }
      resolve();
    });
  });
};

export default handler;
