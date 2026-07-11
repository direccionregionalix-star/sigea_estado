/**
 * SIGEA — servidor de notificaciones por mail.
 * POST /mail  { destinatario, tipo, recinto, funcionario }
 *
 * Envío vía API HTTP de Resend (https://resend.com) — puerto 443.
 * Railway bloquea los puertos SMTP (587/465); la versión anterior con
 * nodemailer hacía timeout en silencio y ningún correo salió jamás.
 *
 * Variables de entorno (configurar en Railway):
 *   RESEND_API_KEY   — API key de Resend. NUNCA en el código.
 *   SIGEA_MAIL_FROM  — remitente. Debe ser un dominio verificado en Resend,
 *                      o el remitente de prueba onboarding@resend.dev si aún
 *                      no hay dominio propio verificado.
 *                      Default: "SIGEA <onboarding@resend.dev>".
 *
 * Sin RESEND_API_KEY configurada: simula el envío (log + evento con
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

const PORT = process.env.PORT || 3001;
const RESEND_API_KEY = process.env.RESEND_API_KEY || "";
const MAIL_FROM = process.env.SIGEA_MAIL_FROM || "SIGEA <onboarding@resend.dev>";

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

// ─── Envío vía API de Resend (HTTPS puerto 443 — evade el bloqueo SMTP) ──────

function escapeHtml(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
                  .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// Nunca rechaza: resuelve siempre { enviado, simulado, nota }.
// nota = "" si el envío salió bien; causa del fallo en caso contrario.
function enviarResend(destinatario, asunto, cuerpo) {
  return new Promise((resolve) => {
    if (!RESEND_API_KEY) {
      resolve({ enviado: false, simulado: true,
                nota: "RESEND_API_KEY no configurada — envío simulado" });
      return;
    }
    const payload = JSON.stringify({
      from: MAIL_FROM,
      to: [destinatario],
      subject: asunto,
      html: escapeHtml(cuerpo).replace(/\n/g, "<br>\n"),
      text: cuerpo,
    });
    const req = https.request({
      hostname: "api.resend.com",
      path: "/emails",
      method: "POST",
      headers: {
        Authorization: `Bearer ${RESEND_API_KEY}`,
        "Content-Type": "application/json",
        "Content-Length": Buffer.byteLength(payload),
      },
      timeout: 15000,
    }, res => {
      let raw = "";
      res.on("data", d => raw += d);
      res.on("end", () => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve({ enviado: true, simulado: false, nota: "" });
        } else {
          let detalle = raw;
          try { detalle = JSON.parse(raw).message || raw; } catch (_) {}
          resolve({ enviado: false, simulado: false,
                    nota: `Resend HTTP ${res.statusCode}: ${String(detalle).slice(0, 300)}` });
        }
      });
    });
    req.on("timeout", () => {
      req.destroy(new Error("timeout de 15s"));
    });
    req.on("error", e => {
      resolve({ enviado: false, simulado: false,
                nota: `Error de red hacia Resend: ${e.message}` });
    });
    req.write(payload);
    req.end();
  });
}

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

      // enviarResend nunca rechaza: siempre { enviado, simulado, nota }
      const info = await enviarResend(emailDest, asunto, cuerpo);
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
  console.log(RESEND_API_KEY
    ? `Mail: API Resend (remitente: ${MAIL_FROM})`
    : "RESEND_API_KEY no configurada — modo simulación");
});
