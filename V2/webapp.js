AWS.config.logger = console;

/*********** CONFIGURACIÓN — REEMPLAZA ESTOS VALORES ***********/
const REGION = "us-east-1";                        // Reemplaza con tu región
const IDENTITY_POOL_ID = "us-east-1:4c3eabb2-8fa4-4973-ad0e-f6066965290a"; // Identity Pool ID (acceso guest)
const BOT_ID = "DCOKIVRC7V";                       // Bot ID (~10 caracteres)
const BOT_ALIAS_ID = "HO9WEHV6MC";                 // Alias ID (como se ve en consola)
const LOCALE_ID = "es_419";                        // Español LatAM (coincide con tu bot)
const VOICE_ID = "Mia";                          // Voz LatAm (es-MX). Alternativas: "Andrés", "Lupe", etc.
/***************************************************************/

const chat = document.getElementById("chat");
const input = document.getElementById("userInput");
const sendBtn = document.getElementById("sendBtn");
const voiceToggle = document.getElementById("voice");
const resetBtn = document.getElementById("resetBtn");
const sessionPill = document.getElementById("sessionPill");

// === UI helpers ===
function addMsg(text, who = "bot") {
  const div = document.createElement("div");
  div.className = `msg ${who === "me" ? "me" : "bot"}`;
  div.textContent = text;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}
function setBusy(b) { sendBtn.disabled = b; input.disabled = b; }

// === SESSION: persistimos un sessionId por usuario ===
const SESSION_KEY = "lexSessionId";
let sessionId = localStorage.getItem(SESSION_KEY);
if (!sessionId) {
  sessionId = crypto.randomUUID();
  localStorage.setItem(SESSION_KEY, sessionId);
}
sessionPill.textContent = `session: ${sessionId.slice(0,8)}…`;

// === AWS SDK v2 — credenciales (Cognito guest) y clientes ===
AWS.config.region = REGION;
AWS.config.credentials = new AWS.CognitoIdentityCredentials({ IdentityPoolId: IDENTITY_POOL_ID });

// Log detallado a la consola (útil para depurar llamadas del SDK)
AWS.config.logger = console; // :contentReference[oaicite:4]{index=4}

const lex = new AWS.LexRuntimeV2({ region: REGION });
const polly = new AWS.Polly({ region: REGION });

// Helpers de credenciales
function clearCached() { AWS.config.credentials.clearCachedId?.(); }
function refreshCreds() {
  return new Promise((res, rej) => AWS.config.credentials.refresh(err => err ? rej(err) : res()));
}

// Llamada a Lex V2 — RecognizeText
async function sendToLex(text) {
  const params = {
    botAliasId: BOT_ALIAS_ID,
    botId: BOT_ID,
    localeId: LOCALE_ID,
    sessionId,                  // persistente para mantener memoria
    text
  };
  const resp = await lex.recognizeText(params).promise(); // :contentReference[oaicite:5]{index=5}
  const messages = (resp.messages || []).map(m => m.content);
  return messages.join(" ") || "No tengo respuesta por ahora.";
}

// Voz con Polly
async function speak(text) {
  if (!voiceToggle.checked) return;
  const p = {
    Text: text,
    OutputFormat: "mp3",
    VoiceId: VOICE_ID,
    Engine: "neural"            // asegúrate de que la voz soporte neural en tu región
  };
  const data = await polly.synthesizeSpeech(p).promise();  
  if (!data.AudioStream) return;
  const blob = new Blob([data.AudioStream], { type: "audio/mpeg" });
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  await audio.play();
}

// (Opcional) inspeccionar la sesión actual en Lex
async function debugGetSession() {
  try {
    const s = await lex.getSession({
      botAliasId: BOT_ALIAS_ID, botId: BOT_ID, localeId: LOCALE_ID, sessionId
    }).promise(); // :contentReference[oaicite:7]{index=7}
    console.log("Lex session state:", s.sessionState);
  } catch (e) {
    console.warn("GetSession failed:", e);
  }
}

// Eventos UI
sendBtn.addEventListener("click", async () => {
  const text = input.value.trim();
  if (!text) return;
  addMsg(text, "me");
  setBusy(true);
  try {
    await refreshCreds();
    const reply = await sendToLex(text);
    addMsg(reply, "bot");
    await speak(reply);
    // debugGetSession(); // descomenta si quieres ver estado en consola
  } catch (e) {
    console.error(e);
    addMsg("⚠️ Error: " + (e.message || "Fallo al llamar Lex/Polly"), "bot");
  } finally {
    setBusy(false);
    input.value = "";
    input.focus();
  }
});

resetBtn.addEventListener("click", () => {
  clearCached();
  localStorage.removeItem(SESSION_KEY);
  sessionId = crypto.randomUUID();
  localStorage.setItem(SESSION_KEY, sessionId);
  sessionPill.textContent = `session: ${sessionId.slice(0,8)}…`;
  addMsg("🔄 Nueva sesión iniciada.", "bot");
});

// Enfocar al iniciar
input.focus();
