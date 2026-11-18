import { createRoot } from 'react-dom/client';
import App from './App';

// Show any runtime/boot errors on screen instead of a silent white canvas.
function showError(msg: string) {
  const pre = document.createElement('pre');
  pre.style.cssText =
    'position:fixed;left:12px;bottom:12px;z-index:9999;max-width:80vw;' +
    'padding:10px 14px;background:#2a1215;color:#f0a3a3;border:1px solid #d25f5f;' +
    'border-radius:8px;font:12px/1.5 Consolas,monospace;white-space:pre-wrap;';
  pre.textContent = msg;
  document.body.appendChild(pre);
}

window.addEventListener('error', (e) => showError('Ошибка: ' + e.message));
window.addEventListener('unhandledrejection', (e) =>
  showError('Ошибка (promise): ' + (e.reason?.message ?? String(e.reason)))
);

// Render the Activity UI IMMEDIATELY. The Discord SDK handshake runs in
// parallel and must never block rendering (a hanging sdk.ready() inside the
// Discord iframe was causing a blank white screen).
createRoot(document.getElementById('root')!).render(<App />);

(async () => {
  try {
    const { DiscordSDK } = await import('@discord/embedded-app-sdk');
    const clientId =
      new URLSearchParams(window.location.search).get('client_id') ??
      import.meta.env.VITE_DISCORD_CLIENT_ID ??
      '';
    if (!clientId) {
      console.info('Discord SDK: нет client_id — работаем как обычная страница');
      return;
    }
    const sdk = new DiscordSDK(clientId);
    await sdk.ready();
    (window as any).__discordSdk = sdk;
    console.info('Discord SDK готов');
  } catch (err) {
    console.info('Discord SDK недоступен, работаем standalone:', err);
  }
})();
