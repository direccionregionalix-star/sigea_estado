/**
 * mailer_gmail.js — Envío de correo real vía la API de Gmail (OAuth2).
 *
 * Por qué Gmail API y no SMTP ni Resend:
 *   - Railway bloquea los puertos SMTP de salida (587/465): nodemailer nunca
 *     funcionó en producción.
 *   - Resend exige verificar un dominio propio; el Director no quiere comprar
 *     uno ni usar @servel.cl para esto.
 *   - La API de Gmail viaja por HTTPS (puerto 443, no bloqueado) y envía desde
 *     la cuenta @gmail.com del Director, autenticada con un refresh token
 *     OAuth2 de larga duración (no requiere re-autorizar en cada envío).
 *
 * Variables de entorno (Railway) — NUNCA hardcodear:
 *   GMAIL_CLIENT_ID      — Client ID de las credenciales OAuth2 (Google Cloud).
 *   GMAIL_CLIENT_SECRET  — Client Secret de esas credenciales.
 *   GMAIL_REFRESH_TOKEN  — token de refresco, generado UNA vez con
 *                          scripts/generar_refresh_token.js.
 *   GMAIL_SENDER         — dirección @gmail.com remitente (informativa, para el
 *                          encabezado From; Gmail envía desde la cuenta dueña
 *                          del refresh token igual).
 *
 * Contrato (idéntico al de la interfaz anterior enviarResend):
 *   enviarGmail(destinatario, asunto, cuerpo) -> Promise<{enviado, simulado, nota}>
 *   NUNCA rechaza. Sin credenciales → simulación. Cualquier fallo → la causa
 *   queda en `nota` (jamás un error silencioso ni un throw que rompa el flujo).
 *
 * REGLA: el cuerpo del correo solo lleva metadata de proceso (recinto,
 * funcionario, tipo de evento). Nunca RUTs, coordenadas ni direcciones.
 */

"use strict";

const GMAIL_CLIENT_ID     = process.env.GMAIL_CLIENT_ID || "";
const GMAIL_CLIENT_SECRET = process.env.GMAIL_CLIENT_SECRET || "";
const GMAIL_REFRESH_TOKEN = process.env.GMAIL_REFRESH_TOKEN || "";
const GMAIL_SENDER        = process.env.GMAIL_SENDER || "";

// Scope mínimo: solo ENVIAR. No pedimos lectura del buzón del Director.
const GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.send";

function credencialesOk() {
  return Boolean(GMAIL_CLIENT_ID && GMAIL_CLIENT_SECRET && GMAIL_REFRESH_TOKEN);
}

function escapeHtml(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
                  .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// Codifica un string a base64url (lo que exige gmail.users.messages.send).
function base64url(str) {
  return Buffer.from(str, "utf-8").toString("base64")
    .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

// Encabezado con caracteres no-ASCII (asuntos con tildes/ñ) → RFC 2047.
function encodeHeader(valor) {
  // eslint-disable-next-line no-control-regex
  if (/^[\x00-\x7F]*$/.test(valor)) return valor;
  return "=?UTF-8?B?" + Buffer.from(valor, "utf-8").toString("base64") + "?=";
}

// Extrae una causa legible de un error de googleapis / red / OAuth.
function causaDe(e) {
  try {
    if (e && e.response && e.response.data) {
      const d = e.response.data;
      if (d.error && d.error.message) return `${d.error.code || ""} ${d.error.message}`.trim();
      if (typeof d.error === "string") return `${d.error}${d.error_description ? ": " + d.error_description : ""}`;
      return JSON.stringify(d).slice(0, 300);
    }
    if (e && e.errors && e.errors.length) return e.errors.map(x => x.message).join("; ");
    return (e && e.message) || String(e);
  } catch (_) {
    return (e && e.message) || "error desconocido";
  }
}

/**
 * Envía un correo real vía Gmail API. Nunca lanza.
 * @param {string} destinatario  email de destino
 * @param {string} asunto        asunto en texto plano
 * @param {string} cuerpo        cuerpo en texto plano (se convierte a HTML)
 * @returns {Promise<{enviado:boolean, simulado:boolean, nota:string}>}
 */
async function enviarGmail(destinatario, asunto, cuerpo) {
  if (!credencialesOk()) {
    return { enviado: false, simulado: true,
             nota: "GMAIL_CLIENT_ID/SECRET/REFRESH_TOKEN no configuradas — envío simulado" };
  }

  // googleapis se carga de forma perezosa: si el paquete no está instalado,
  // se degrada a fallo con causa (no rompe el arranque del servidor).
  let google;
  try {
    ({ google } = require("googleapis"));
  } catch (e) {
    return { enviado: false, simulado: false,
             nota: "Paquete 'googleapis' no instalado (npm install googleapis): " + causaDe(e) };
  }

  try {
    const oauth2Client = new google.auth.OAuth2(GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET);
    oauth2Client.setCredentials({ refresh_token: GMAIL_REFRESH_TOKEN, scope: GMAIL_SCOPE });
    const gmail = google.gmail({ version: "v1", auth: oauth2Client });

    const html = escapeHtml(cuerpo).replace(/\n/g, "<br>\n");
    const headers = [
      `To: ${destinatario}`,
      ...(GMAIL_SENDER ? [`From: SIGEA DR Araucanía <${GMAIL_SENDER}>`] : []),
      `Subject: ${encodeHeader(asunto)}`,
      "MIME-Version: 1.0",
      "Content-Type: text/html; charset=utf-8",
      "",
      html,
    ];
    const raw = base64url(headers.join("\r\n"));

    await gmail.users.messages.send({ userId: "me", requestBody: { raw } });
    return { enviado: true, simulado: false, nota: "" };
  } catch (e) {
    return { enviado: false, simulado: false, nota: `Gmail API: ${causaDe(e)}` };
  }
}

module.exports = { enviarGmail, credencialesOk, GMAIL_SENDER };
