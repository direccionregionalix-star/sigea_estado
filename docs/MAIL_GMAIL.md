# Correo SIGEA vía Gmail API (OAuth2)

El servidor de notificaciones (`dashboard/server.js` → `dashboard/mailer_gmail.js`)
envía correo real usando la **API de Gmail** por HTTPS (puerto 443). Esto evita
el bloqueo de puertos SMTP de Railway (587/465) sin necesidad de verificar un
dominio propio (lo que exigía Resend).

## Variables de entorno (Railway) — nunca en el código

| Variable | Qué es |
|---|---|
| `GMAIL_CLIENT_ID` | Client ID de las credenciales OAuth2 de Google Cloud. |
| `GMAIL_CLIENT_SECRET` | Client Secret de esas credenciales. |
| `GMAIL_REFRESH_TOKEN` | Token de refresco de larga duración (se genera una vez, ver abajo). |
| `GMAIL_SENDER` | La dirección `@gmail.com` remitente (para el encabezado From). |

**Sin las tres primeras configuradas → modo simulación** (`enviado:false`), nunca
un error que rompa el flujo de entrega. **Cualquier fallo de envío** (token
expirado, error de la API, red) queda registrado con su causa exacta en el campo
`nota` del evento `mail` de `bitacora.json` — nunca falla en silencio.

Scope solicitado: `gmail.send` únicamente (enviar; sin lectura del buzón).

## Generar el GMAIL_REFRESH_TOKEN (una sola vez, el Director)

1. **Google Cloud Console** (console.cloud.google.com) → crear un proyecto
   nuevo, p. ej. "SIGEA Mail".
2. **APIs & Services → Library** → buscar **"Gmail API"** → **Enable**.
3. **APIs & Services → OAuth consent screen** → tipo **External**. Puede quedar
   en modo *Testing*; agrega tu propio correo como *usuario de prueba*
   (suficiente para este uso, no hace falta publicar la app).
4. **APIs & Services → Credentials → Create Credentials → OAuth client ID** →
   tipo **Desktop app** (recomendado: permite el redirect a `localhost`
   automáticamente). Copia el **Client ID** y el **Client Secret**.
   - Si eliges "Web application", agrega el redirect URI exacto
     `http://localhost:3000` (o el puerto que uses con `GMAIL_OAUTH_PORT`).
5. Corre el script **una vez** en tu máquina (con Node y `npm install googleapis`):
   ```
   GMAIL_CLIENT_ID=... GMAIL_CLIENT_SECRET=... node scripts/generar_refresh_token.js
   ```
   Abre la URL que imprime, inicia sesión con **tu Gmail**, acepta el permiso de
   "enviar correo". El script captura el código y te imprime el
   `GMAIL_REFRESH_TOKEN`.
6. Carga las **4 variables** en Railway (Variables del servicio) y redeploy.
   Prueba con el botón **"Recordatorio"** del dashboard (modo Admin).

> Si el script dice que Google no devolvió `refresh_token`: entra a
> https://myaccount.google.com/permissions, revoca el acceso de la app y vuelve
> a correrlo (Google solo entrega el refresh token en la primera autorización).
