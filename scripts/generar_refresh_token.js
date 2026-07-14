#!/usr/bin/env node
/**
 * generar_refresh_token.js — SIGEA · uso ÚNICO del Director.
 *
 * Genera el GMAIL_REFRESH_TOKEN de larga duración que el servidor de correo
 * (dashboard/mailer_gmail.js) usa para enviar vía la API de Gmail. Se corre
 * UNA sola vez, en la máquina del Director, con su sesión de Gmail.
 *
 * Requisitos previos (ver el reporte / README de este encargo):
 *   1. Proyecto en Google Cloud con la "Gmail API" habilitada.
 *   2. Pantalla de consentimiento OAuth configurada (tipo External; el propio
 *      correo del Director agregado como usuario de prueba si queda en Testing).
 *   3. Credenciales OAuth2 tipo "Desktop app" (recomendado: permite el
 *      redirect a localhost automáticamente). Copiar su Client ID y Secret.
 *
 * Uso:
 *   GMAIL_CLIENT_ID=... GMAIL_CLIENT_SECRET=... node scripts/generar_refresh_token.js
 *   (o pasarlos como argumentos: node scripts/generar_refresh_token.js <CLIENT_ID> <CLIENT_SECRET>)
 *
 * El script:
 *   - Levanta un servidor local temporal en http://localhost:<puerto>.
 *   - Imprime una URL: el Director la abre, inicia sesión con SU Gmail y acepta
 *     el permiso de "enviar correo" (scope gmail.send, sin lectura del buzón).
 *   - Captura el código del redirect, lo intercambia por tokens e imprime el
 *     GMAIL_REFRESH_TOKEN listo para pegar en Railway.
 *
 * NADA se guarda en disco ni se sube a ningún lado: el token se imprime en la
 * terminal del Director y de ahí va directo a las variables de Railway.
 */

"use strict";

const http = require("http");
const { URL } = require("url");

let google;
try {
  ({ google } = require("googleapis"));
} catch (e) {
  console.error("\n✗ Falta el paquete 'googleapis'. Instálalo primero:\n" +
                "    npm install googleapis\n");
  process.exit(1);
}

const CLIENT_ID     = process.env.GMAIL_CLIENT_ID     || process.argv[2] || "";
const CLIENT_SECRET = process.env.GMAIL_CLIENT_SECRET || process.argv[3] || "";
const PORT          = parseInt(process.env.GMAIL_OAUTH_PORT || "3000", 10);
const REDIRECT_URI  = `http://localhost:${PORT}`;
const SCOPE         = "https://www.googleapis.com/auth/gmail.send";

if (!CLIENT_ID || !CLIENT_SECRET) {
  console.error("\n✗ Faltan credenciales. Entrégalas por variable de entorno o argumento:\n" +
    "    GMAIL_CLIENT_ID=... GMAIL_CLIENT_SECRET=... node scripts/generar_refresh_token.js\n" +
    "  o\n" +
    "    node scripts/generar_refresh_token.js <CLIENT_ID> <CLIENT_SECRET>\n\n" +
    "  Nota: en las credenciales OAuth de Google Cloud, agrega este redirect URI\n" +
    `  exacto si usaste tipo \"Web application\":  ${REDIRECT_URI}\n` +
    "  (con tipo \"Desktop app\" el redirect a localhost ya está permitido).\n");
  process.exit(1);
}

const oauth2Client = new google.auth.OAuth2(CLIENT_ID, CLIENT_SECRET, REDIRECT_URI);

const authUrl = oauth2Client.generateAuthUrl({
  access_type: "offline",       // imprescindible para recibir refresh_token
  prompt: "consent",            // fuerza refresh_token aunque ya haya autorizado antes
  scope: [SCOPE],
});

const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, REDIRECT_URI);
    if (!url.searchParams.has("code") && !url.searchParams.has("error")) {
      res.writeHead(204); res.end(); return;   // favicon u otros
    }
    const err = url.searchParams.get("error");
    if (err) {
      res.writeHead(400, { "Content-Type": "text/plain; charset=utf-8" });
      res.end("Autorización cancelada o rechazada: " + err);
      console.error("\n✗ Autorización cancelada/rechazada:", err, "\n");
      server.close(); process.exit(1);
    }

    const code = url.searchParams.get("code");
    const { tokens } = await oauth2Client.getToken(code);
    res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
    res.end("<h2>✓ Listo.</h2><p>Ya puedes cerrar esta pestaña y volver a la terminal.</p>");

    if (!tokens.refresh_token) {
      console.error("\n✗ Google no devolvió refresh_token. Suele pasar cuando ya " +
        "habías autorizado antes.\n  Solución: entra a https://myaccount.google.com/permissions, " +
        "revoca el acceso de esta app y vuelve a correr el script.\n");
      server.close(); process.exit(1);
    }

    console.log("\n" + "═".repeat(64));
    console.log("  ✓ GMAIL_REFRESH_TOKEN generado. Pégalo en Railway:");
    console.log("═".repeat(64));
    console.log("\nGMAIL_REFRESH_TOKEN=" + tokens.refresh_token + "\n");
    console.log("Recuerda cargar también en Railway:");
    console.log("  GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET y GMAIL_SENDER (tu @gmail.com).\n");
    server.close(); process.exit(0);
  } catch (e) {
    res.writeHead(500, { "Content-Type": "text/plain; charset=utf-8" });
    res.end("Error intercambiando el código: " + (e.message || e));
    console.error("\n✗ Error intercambiando el código por tokens:", e.message || e, "\n");
    server.close(); process.exit(1);
  }
});

server.listen(PORT, () => {
  console.log("\nSIGEA · Generador de refresh token de Gmail");
  console.log("──────────────────────────────────────────");
  console.log("1) Abre esta URL en tu navegador (con la sesión de tu Gmail):\n");
  console.log("   " + authUrl + "\n");
  console.log("2) Acepta el permiso de \"enviar correo\".");
  console.log(`3) Serás redirigido a ${REDIRECT_URI} y el token aparecerá aquí.\n`);
  console.log("(Esperando la autorización…)");
});
