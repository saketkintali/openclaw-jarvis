import { spawn } from "child_process";
import * as path from "path";

const handler = async (event: any) => {
  if (event.type !== "message" || event.action !== "received") return;
  if (event.context?.channelId !== "whatsapp") return;

  // Skip messages sent by the bot itself — prevents feedback loop where
  // bot responses trigger the hook again, creating a cascade of messages.
  if (event.message?.fromMe === true) return;
  if (event.context?.fromMe === true) return;
  if (event.context?.fromSelf === true) return;
  if (event.context?.direction === "outbound") return;

  const scriptPath = path.join(
    process.env["USERPROFILE"] ?? ".",
    ".openclaw",
    "workspace",
    "check_audio.py"
  );

  const child = spawn("python", [scriptPath], {
    detached: true,
    stdio: "ignore",
  });
  child.unref();
};

export default handler;
