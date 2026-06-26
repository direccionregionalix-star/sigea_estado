/**
 * SIGEA — servidor de notificaciones por mail.
 * POST /mail  { destinatario, tipo, recinto, funcionario }
 *
 * Credenciales SMTP en variables de entorno:
 *   SIGEA_SMTP_HOST, SIGEA_SMTP_PORT, SIGEA_SMTP_USER, SIGEA_SMTP_PASS
 *   SIGEA_MAIL_FROM   (remitente, default: SIGEA_SMTP_USER)
 *
 * Sin SMTP configurado: simula el envío (log + evento con enviado:false).
 * Railway: agregar como proceso en Procfile o como start en package.json.
 *
 * REGLA: el cuerpo del mail nunca lleva RUTs, coordenadas ni direcciones.
 * Solo metadata de proceso (recinto, funcionario, tipo de evento).
 */

const http = require("http");
const https = require("https");

const PORT = process.env.PORT || 3001;
const SMTP_HOST = process.env.SIGEA_SMTP_HOST || "";
const SMTP_PORT = parseInt(process.env.SIGEA_SMTP_PORT || "587", 10);
const SMTP_USER = process.env.SIGEA_SMTP_USER || "";
const SMTP_PASS = process.env.SIGEA_SMTP_PASS || "";
const MAIL_FROM = process.env.SIGEA_MAIL_FROM || SMTP_USER;

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

// ─── Envío SMTP (sin dependencias externas — usa net/tls de Node) ─────────────

function enviarSMTP(destinatario, asunto, cuerpo) {
  return new Promise((resolve, reject) => {
    if (!SMTP_HOST || !SMTP_USER || !SMTP_PASS) {
      resolve({ simulado: true });
      return;
    }
    // Usamos nodemailer si está disponible, si no fallback a simulación
    try {
      const nodemailer = require("nodemailer");
      const transporter = nodemailer.createTransport({
        host: SMTP_HOST, port: SMTP_PORT,
        secure: SMTP_PORT === 465,
        auth: { user: SMTP_USER, pass: SMTP_PASS },
      });
      transporter.sendMail({
        from: MAIL_FROM, to: destinatario,
        subject: asunto, text: cuerpo,
      }, (err, info) => {
        if (err) reject(err);
        else resolve(info);
      });
    } catch (_) {
      // nodemailer no instalado — simular
      resolve({ simulado: true });
    }
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

async function registrarEventoMail(recinto, funcionario, destinatario, asunto, enviado) {
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
      detalle: { destinatario, asunto, enviado },
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

  if (req.method === "POST" && req.url === "/mail") {
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

      let enviado = false;
      let info = {};
      try {
        info = await enviarSMTP(emailDest, asunto, cuerpo);
        enviado = !info.simulado;
        if (info.simulado) {
          console.log(`[mail simulado] → ${emailDest} | ${asunto}`);
        } else {
          console.log(`[mail enviado] → ${emailDest} | ${asunto}`);
        }
      } catch (e) {
        console.error(`[mail error] ${e.message}`);
      }

      // Registrar en bitácora (async, no bloquea la respuesta)
      registrarEventoMail(recinto, funcionario || "", destKey, asunto, enviado)
        .catch(e => console.error("[bitacora mail]", e.message));

      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ ok: true, enviado, simulado: !!info.simulado }));
    });
    return;
  }

  res.writeHead(404); res.end();
});

server.listen(PORT, () => {
  const smtpOk = SMTP_HOST && SMTP_USER && SMTP_PASS;
  console.log(`SIGEA mail server en :${PORT}`);
  console.log(smtpOk
    ? `SMTP: ${SMTP_HOST}:${SMTP_PORT} (usuario: ${SMTP_USER})`
    : "SMTP no configurado — modo simulación");
});
