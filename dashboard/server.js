/**
 * SIGEA — servidor de notificaciones por mail.
 * POST /mail  { destinatario, tipo, recinto, funcionario }
 *
 * Envío vía API de Gmail con OAuth2 (HTTPS puerto 443 — no bloqueado por
 * Railway). Historia: SMTP crudo (nodemailer) hacía timeout porque Railway
 * bloquea 587/465; Resend exigía verificar un dominio propio. Gmail API
 * envía desde la cuenta @gmail.com del Director sin ninguna de esas trabas.
 * La lógica de envío vive en ./mailer_gmail.js.
 *
 * Variables de entorno (configurar en Railway) — ver mailer_gmail.js:
 *   GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN, GMAIL_SENDER.
 *
 * Sin credenciales Gmail configuradas: simula el envío (log + evento con
 * enviado:false), sin romper el flujo de entrega. Todo fallo de envío
 * registra su causa en el campo "nota" del evento de bitácora.
 *
 * REGLA: el cuerpo del mail nunca lleva RUTs, coordenadas ni direcciones.
 * Solo metadata de proceso (recinto, funcionario, tipo de evento).
 */

const http = require("http");
const https = require("https");
const fs = require("fs");
const path = require("path");

const { enviarGmail, credencialesOk: gmailListo, GMAIL_SENDER } =
  require("./mailer_gmail");

const PORT = process.env.PORT || 3001;

// Repo GitHub donde viven estado.json / bitacora.json / qgis/ / sige/
// Variable: SIGEA_REPO=SebaGeoZ92/sigea_estado  (owner/repo, sin slash final)
// El servidor inyecta esta URL en el HTML al servir index.html.
const SIGEA_REPO = process.env.SIGEA_REPO || "direccionregionalix-star/sigea_estado";
const GH_RAW_BASE = `https://raw.githubusercontent.com/${SIGEA_REPO}/main`;

// Mapa funcionario → email (configurable por variable de entorno JSON)
// SIGEA_MAILS='{"igarrido":"i.garrido@servel.cl", ...}'
let MAILS_FUNCIONARIOS = {};
try {
  if (process.env.SIGEA_MAILS) {
    MAILS_FUNCIONARIOS = JSON.parse(process.env.SIGEA_MAILS);
  }
} catch (_) {}

// ─── Plantillas de mensaje ────────────────────────────────────────────────────

const ASUNTOS = {
  asignacion: (r, f) => `[SIGEA] Se te asignó el recinto ${r}`,
  entrega:    (r, f) => `[SIGEA] Recinto ${r} entregado por ${f} — pendiente QA`,
  qa_ok:      (r, f) => `[SIGEA] QA aprobado: recinto ${r} (${f})`,
  qa_obs:     (r, f) => `[SIGEA] QA observado: recinto ${r} (${f})`,
  cierre:     (r, f) => `[SIGEA] Recinto ${r} cerrado formalmente`,
};

const CUERPOS = {
  asignacion: (r, f) =>
    `Hola ${f},\n\nSe te asignó el recinto ${r} para rectificación.\n` +
    `Puedes ver tu asignación en el plugin QGIS.\n\nSIGEA DR Araucanía`,
  entrega: (r, f) =>
    `El funcionario ${f} entregó el recinto ${r}.\n` +
    `El recinto quedó pendiente de QA por parte del supervisor.\n\nSIGEA DR Araucanía`,
  qa_ok: (r, f) =>
    `El recinto ${r} del funcionario ${f} fue aprobado en QA.\n\nSIGEA DR Araucanía`,
  qa_obs: (r, f) =>
    `El recinto ${r} del funcionario ${f} fue observado en QA.\n` +
    `Revisa los comentarios con tu supervisor.\n\nSIGEA DR Araucanía`,
  cierre: (r, f) =>
    `El recinto ${r} fue cerrado formalmente.\n\nSIGEA DR Araucanía`,
};

// El envío real vive en ./mailer_gmail.js (enviarGmail), con el mismo
// contrato que usaba enviarResend: nunca lanza, resuelve
// { enviado, simulado, nota }.

// ─── Escritura a bitácora en GitHub ──────────────────────────────────────────
// Reutiliza el mecanismo del plugin: lee _r, _t, _b del estado.json publicado.

const ESTADO_URL = process.env.SIGEA_ESTADO_URL || "";

async function fetchEstado() {
  if (!ESTADO_URL) return null;
  return new Promise((resolve, reject) => {
    const mod = ESTADO_URL.startsWith("https") ? https : http;
    mod.get(ESTADO_URL, res => {
      let raw = "";
      res.on("data", d => raw += d);
      res.on("end", () => {
        try { resolve(JSON.parse(raw)); } catch (e) { reject(e); }
      });
    }).on("error", reject);
  });
}

function deofuscar(b64, key = "SIGEA2026araucania") {
  const buf = Buffer.from(b64, "base64");
  const keyBuf = Buffer.from(key);
  return buf.map((b, i) => b ^ keyBuf[i % keyBuf.length]).toString();
}

async function registrarEventoMail(recinto, funcionario, destinatario, asunto, enviado, nota) {
  try {
    const estado = await fetchEstado();
    if (!estado) return;
    const token = deofuscar(estado._t);
    const repo  = estado._r;
    const branch = estado._b || "main";

    const path = "bitacora.json";
    const apiUrl = `https://api.github.com/repos/${repo}/contents/${path}`;

    // GET
    const getResp = await new Promise((resolve, reject) => {
      const req = https.get(apiUrl + `?ref=${branch}`, {
        headers: {
          Authorization: `Bearer ${token}`,
          Accept: "application/vnd.github+json",
          "User-Agent": "SIGEA-MailServer",
        },
      }, res => {
        let raw = "";
        res.on("data", d => raw += d);
        res.on("end", () => resolve({ status: res.statusCode, body: raw }));
      });
      req.on("error", reject);
    });

    let bitacora = { eventos: [] }, sha = null;
    if (getResp.status === 200) {
      const parsed = JSON.parse(getResp.body);
      sha = parsed.sha;
      bitacora = JSON.parse(Buffer.from(parsed.content, "base64").toString());
    }

    bitacora.eventos.push({
      ts: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
      tipo: "mail",
      recinto, funcionario,
      detalle: { destinatario, asunto, enviado, nota: nota || "" },
    });

    const contenidoB64 = Buffer.from(JSON.stringify(bitacora, null, 1)).toString("base64");
    const payload = JSON.stringify({
      message: `bitacora mail ${funcionario} ${recinto}`,
      content: contenidoB64,
      branch,
      ...(sha ? { sha } : {}),
    });

    await new Promise((resolve, reject) => {
      const url = new URL(apiUrl);
      const req = https.request({
        hostname: url.hostname, path: url.pathname,
        method: "PUT", headers: {
          Authorization: `Bearer ${token}`,
          Accept: "application/vnd.github+json",
          "Content-Type": "application/json",
          "User-Agent": "SIGEA-MailServer",
          "Content-Length": Buffer.byteLength(payload),
        },
      }, res => {
        res.resume();
        resolve(res.statusCode);
      });
      req.on("error", reject);
      req.write(payload);
      req.end();
    });
  } catch (e) {
    console.error("[bitacora]", e.message);
  }
}

// ─── Servidor HTTP ────────────────────────────────────────────────────────────

const server = http.createServer(async (req, res) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");

  if (req.method === "OPTIONS") {
    res.writeHead(204); res.end(); return;
  }

  // --- NUEVA RUTA: Proxy para estado.json (Anti-caché) ---
  if (req.method === "GET" && req.url === "/estado.json") {
    // Agregamos un timestamp a la URL de GitHub para obligarlo a dar la versión más reciente
    const noCacheUrl = `${GH_RAW_BASE}/estado.json?t=${Date.now()}`;
    
    https.get(noCacheUrl, (githubRes) => {
      let rawData = "";
      githubRes.on("data", (chunk) => rawData += chunk);
      githubRes.on("end", () => {
        res.writeHead(githubRes.statusCode, { 
          "Content-Type": "application/json; charset=utf-8",
          "Access-Control-Allow-Origin": "*" 
        });
        res.end(rawData);
      });
    }).on("error", (e) => {
      res.writeHead(500, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: "Fallo de conexión a GitHub", detalle: e.message }));
    });
    return;
  }
  // --- FIN NUEVA RUTA ---

  if (req.method === "POST" && (req.url === "/mail" || req.url === "//mail")) {
    let body = "";
    req.on("data", d => body += d);
    req.on("end", async () => {
      let payload;
      try { payload = JSON.parse(body); } catch (_) {
        res.writeHead(400, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ error: "JSON inválido" })); return;
      }

      const { destinatario: destKey, tipo, recinto, funcionario } = payload;

      // Resolver email desde mapa o usar el campo directamente si es email
      const emailDest = MAILS_FUNCIONARIOS[destKey] || (
        destKey && destKey.includes("@") ? destKey : null);

      if (!emailDest || !tipo || !recinto) {
        res.writeHead(400, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ error: "Faltan campos: destinatario, tipo, recinto" }));
        return;
      }

      const buildAsunto = ASUNTOS[tipo];
      const buildCuerpo = CUERPOS[tipo];
      if (!buildAsunto) {
        res.writeHead(400, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ error: `Tipo desconocido: ${tipo}` })); return;
      }

      const asunto = buildAsunto(recinto, funcionario || "");
      const cuerpo = buildCuerpo(recinto, funcionario || "");

      // enviarGmail nunca rechaza: siempre { enviado, simulado, nota }
      const info = await enviarGmail(emailDest, asunto, cuerpo);
      if (info.enviado) {
        console.log(`[mail enviado] → ${emailDest} | ${asunto}`);
      } else if (info.simulado) {
        console.log(`[mail simulado] → ${emailDest} | ${asunto} | ${info.nota}`);
      } else {
        console.error(`[mail error] → ${emailDest} | ${asunto} | ${info.nota}`);
      }

      // Registrar en bitácora con la causa del fallo si lo hubo
      // (async, no bloquea la respuesta)
      registrarEventoMail(recinto, funcionario || "", destKey, asunto,
                          info.enviado, info.nota)
        .catch(e => console.error("[bitacora mail]", e.message));

      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ ok: true, enviado: info.enviado,
                               simulado: !!info.simulado, nota: info.nota }));
    });
    return;
  }

  // Servir index.html para GET / y GET /dashboard
  // Reemplaza el placeholder __GH_RAW_BASE__ con la URL real del repo.
  if (req.method === "GET" && (req.url === "/" || req.url === "/dashboard" || req.url === "/index.html")) {
    const htmlPath = path.join(__dirname, "index.html");
    fs.readFile(htmlPath, "utf8", (err, html) => {
      if (err) { res.writeHead(404); res.end("Not found"); return; }
      const out = html.replace("__GH_RAW_BASE__", GH_RAW_BASE);
      res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
      res.end(out);
    });
    return;
  }

  res.writeHead(404); res.end();
});

server.listen(PORT, () => {
  console.log(`SIGEA mail server en :${PORT}`);
  console.log(gmailListo()
    ? `Mail: API Gmail (remitente: ${GMAIL_SENDER || "cuenta del refresh token"})`
    : "Credenciales Gmail no configuradas — modo simulación");
});
