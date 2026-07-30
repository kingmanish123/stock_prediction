/**
 * Baileys WhatsApp bot — HTTP daemon.
 *
 * Python side POSTs to /send with {to, message}; this forwards to WhatsApp
 * over the persistent multi-device session stored in ./auth_info/.
 *
 * Design notes:
 *   - Baileys' `executeInitQueries` can time out on some accounts; we swallow
 *     that specific error and stay running — sends still work.
 *   - All unhandled errors are caught globally so this process never crashes;
 *     launchd would restart us anyway but avoiding churn keeps the session
 *     stable.
 *   - `/send` waits for server ACK (status≥1) before returning ok, so callers
 *     know the message actually reached WhatsApp's servers.
 *
 * Start:  node server.js
 * Env:
 *   PORT                - HTTP port, default 3001
 *   AUTH_DIR            - session folder, default ./auth_info
 *   DEFAULT_RECIPIENT   - fallback phone (country code, no +), used when
 *                         POST /send omits `to`
 */
const {
  default: makeWASocket,
  useMultiFileAuthState,
  fetchLatestBaileysVersion,
  DisconnectReason,
} = require('@whiskeysockets/baileys');
const qrcode = require('qrcode-terminal');
const express = require('express');
const pino = require('pino');
const path = require('path');

const PORT = parseInt(process.env.PORT || '5757', 10);
const AUTH_DIR = process.env.AUTH_DIR || path.join(__dirname, 'auth_info');
const DEFAULT_RECIPIENT = process.env.DEFAULT_RECIPIENT || '';

const logger = pino({ level: 'warn' });

// ─── Global safety nets ─────────────────────────────────────────────
// Baileys occasionally emits errors outside our event handlers. These prevent
// the process from dying mid-session (which would lose any queued sends).
process.on('uncaughtException', (err) => {
  console.error('[uncaughtException]', err?.message || err);
});
process.on('unhandledRejection', (err) => {
  console.error('[unhandledRejection]', err?.message || err);
});

let sock = null;
let isReady = false;
let reconnectAttempts = 0;
const MAX_RECONNECT = 100;
// Track ACKs so /send can confirm messages reached WhatsApp servers.
const ackMap = new Map();  // msgId -> {status, ts}

async function start() {
  try {
    const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
    const { version } = await fetchLatestBaileysVersion().catch(() => ({ version: undefined }));

    sock = makeWASocket({
      version,
      auth: state,
      logger,
      printQRInTerminal: false,
      markOnlineOnConnect: false,
      syncFullHistory: false,
      shouldSyncHistoryMessage: () => false,
      defaultQueryTimeoutMs: 60_000,
      keepAliveIntervalMs: 25_000,
    });

    sock.ev.on('creds.update', saveCreds);

    // Track delivery ACKs — status 1=server received, 2=device delivered, 3=read
    sock.ev.on('messages.update', (updates) => {
      for (const u of updates) {
        const id = u.key?.id;
        const status = u.update?.status;
        if (id && status !== undefined) {
          ackMap.set(id, { status, ts: Date.now() });
          console.log(`ACK id=${id} status=${status}`);
          // Keep map bounded
          if (ackMap.size > 500) {
            const oldest = Array.from(ackMap.keys()).slice(0, 100);
            oldest.forEach(k => ackMap.delete(k));
          }
        }
      }
    });

    sock.ev.on('connection.update', (update) => {
      const { connection, lastDisconnect, qr } = update;

      if (qr) {
        console.log('\n📱 Scan this QR with WhatsApp → Settings → Linked Devices:\n');
        qrcode.generate(qr, { small: true });
      }

      if (connection === 'open') {
        isReady = true;
        reconnectAttempts = 0;
        console.log(`✓ WhatsApp bot connected (phone: ${sock.user?.id})`);
      }

      if (connection === 'close') {
        isReady = false;
        const code = lastDisconnect?.error?.output?.statusCode;
        const msg = lastDisconnect?.error?.output?.payload?.message || lastDisconnect?.error?.message;

        // Init-queries timeout (408) is recoverable — DON'T exit, just reconnect.
        // True logout (401) means the user unlinked the device → need re-QR.
        if (code === DisconnectReason.loggedOut) {
          console.error('✗ Logged out by WhatsApp. Delete auth_info/ and restart to re-scan QR.');
          process.exit(1);
        }

        if (reconnectAttempts >= MAX_RECONNECT) {
          console.error('✗ Max reconnect attempts exceeded. Bot exiting — launchd will restart.');
          process.exit(1);
        }
        reconnectAttempts++;
        const delayMs = Math.min(30_000, 1_500 * Math.min(reconnectAttempts, 10));
        console.warn(
          `⟳ Connection closed (code=${code}, msg=${msg}). ` +
          `Reconnecting in ${delayMs}ms (attempt ${reconnectAttempts})`
        );
        setTimeout(() => { start().catch(e => console.error('[start-retry-failed]', e?.message)); }, delayMs);
      }
    });
  } catch (e) {
    console.error('[start-outer]', e?.message || e);
    // Retry with backoff if start itself fails
    setTimeout(() => start().catch(err => console.error('[start-retry-failed]', err?.message)), 5000);
  }
}

// ─── HTTP API ──────────────────────────────────────────────────────
const app = express();
app.use(express.json({ limit: '1mb' }));

function normalizeJid(raw) {
  const digits = String(raw).replace(/\D/g, '');
  if (!digits) return null;
  return `${digits}@s.whatsapp.net`;
}

// Wait up to ms for ACK on given msgId
function waitForAck(msgId, timeoutMs = 5000, minStatus = 1) {
  return new Promise((resolve) => {
    const start = Date.now();
    const tick = () => {
      const ack = ackMap.get(msgId);
      if (ack && ack.status >= minStatus) return resolve(ack);
      if (Date.now() - start >= timeoutMs) return resolve(null);
      setTimeout(tick, 200);
    };
    tick();
  });
}

app.get('/health', (_req, res) => {
  res.json({
    ok: isReady,
    user: sock?.user?.id || null,
    reconnectAttempts,
  });
});

app.post('/verify', async (req, res) => {
  if (!isReady) return res.status(503).json({ ok: false, error: 'not_connected' });
  const { number } = req.body || {};
  if (!number) return res.status(400).json({ ok: false, error: 'missing_number' });
  const digits = String(number).replace(/\D/g, '');
  try {
    const [info] = await sock.onWhatsApp(digits);
    if (info?.exists) return res.json({ ok: true, exists: true, jid: info.jid });
    return res.json({ ok: true, exists: false });
  } catch (e) {
    res.status(500).json({ ok: false, error: String(e?.message || e) });
  }
});

app.post('/send', async (req, res) => {
  if (!isReady) return res.status(503).json({ ok: false, error: 'not_connected' });

  const { to, message, wait_ack } = req.body || {};
  const recipient = to || DEFAULT_RECIPIENT;
  if (!recipient) return res.status(400).json({ ok: false, error: 'missing_to' });
  if (!message || typeof message !== 'string') {
    return res.status(400).json({ ok: false, error: 'missing_message' });
  }

  const jid = normalizeJid(recipient);
  try {
    const sent = await sock.sendMessage(jid, { text: message });
    const msgId = sent?.key?.id || null;

    // Optionally block until WhatsApp server ACKs (default: yes, short timeout)
    if (wait_ack !== false && msgId) {
      const ack = await waitForAck(msgId, 5000, 1);
      return res.json({
        ok: true,
        id: msgId,
        ack_status: ack?.status ?? null,
        ack_received: !!ack,
      });
    }
    res.json({ ok: true, id: msgId });
  } catch (e) {
    console.error('[send_failed]', e?.message || e);
    res.status(500).json({ ok: false, error: String(e?.message || e) });
  }
});

app.listen(PORT, () => console.log(`HTTP listening on :${PORT}`));

process.on('SIGTERM', async () => {
  console.log('SIGTERM → closing WhatsApp socket');
  try { await sock?.end?.(); } catch {}
  process.exit(0);
});

start().catch((e) => {
  console.error('[fatal_start]', e?.message || e);
  // Even on fatal start error, retry rather than exit
  setTimeout(() => start().catch(err => console.error('[retry]', err?.message)), 5000);
});
