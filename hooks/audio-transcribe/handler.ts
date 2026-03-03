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

  // For text messages that request audio output ("say it aloud", "tell me out loud", etc.),
  // spawn check_speak.py which detects the keywords and sends a voice note via WhatsApp.
  const messageBody = event.context?.content ?? event.message?.body;
  if (messageBody && typeof messageBody === "string") {
    const speakScriptPath = path.join(
      process.env["USERPROFILE"] ?? ".",
      ".openclaw",
      "workspace",
      "check_speak.py"
    );
    const speakChild = spawn("python", [speakScriptPath, messageBody], {
      detached: true,
      stdio: "ignore",
    });
    speakChild.unref();
  }
};

export default handler;
