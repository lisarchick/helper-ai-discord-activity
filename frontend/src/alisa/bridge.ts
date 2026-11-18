// WebSocket client for the backend Activity bridge.
// Exposes a small event-emitter style API; auto-reconnects.

import { WordTiming } from './visemes';

export type BotStatus = 'idle' | 'listening' | 'thinking' | 'speaking' | 'stopped';

export interface HistoryItem {
  role: 'user' | 'alisa';
  text: string;
  ts: number;
}

export interface BridgeEvents {
  onState?: (p: { status: BotStatus; voice: string | null; history: HistoryItem[] }) => void;
  onStatus?: (status: BotStatus) => void;
  onAnswerStart?: (p: { text: string; emotion: string; voice?: string }) => void;
  onWords?: (words: WordTiming[]) => void;
  onAnswerEnd?: () => void;
  onStop?: () => void;
  onEmotion?: (emotion: string) => void;
  onHistory?: (items: HistoryItem[]) => void;
  onVoice?: (voice: string) => void;
}

// Bridge URL resolution:
// 1. ?bridge=... query override (quick manual test)
// 2. VITE_BRIDGE_URL build/dev env (set to the wss:// cloudflared tunnel URL
//    when the Activity is served inside Discord — https pages cannot open
//    plain ws:// connections due to mixed-content rules)
// 3. local dev fallback ws://127.0.0.1:8765/ws
export function resolveBridgeUrl(): string {
  const params = new URLSearchParams(window.location.search);
  const explicit = params.get('bridge');
  if (explicit) return explicit;
  const fromEnv = import.meta.env.VITE_BRIDGE_URL as string | undefined;
  if (fromEnv) return fromEnv;
  return 'ws://127.0.0.1:8765/ws';
}

export class BridgeClient {
  private ws: WebSocket | null = null;
  private closedByUser = false;
  private reconnectTimer: number | null = null;

  constructor(private events: BridgeEvents = {}) {}

  connect(): void {
    this.closedByUser = false;
    this.open();
  }

  private open(): void {
    const url = resolveBridgeUrl();
    try {
      this.ws = new WebSocket(url);
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.ws.onopen = () => this.send({ type: 'request_state' });
    this.ws.onmessage = (ev) => this.handle(String(ev.data));
    this.ws.onclose = () => {
      if (!this.closedByUser) this.scheduleReconnect();
    };
    this.ws.onerror = () => {
      /* onclose follows */
    };
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer !== null || this.closedByUser) return;
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      this.open();
    }, 2000);
  }

  close(): void {
    this.closedByUser = true;
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.ws?.close();
  }

  send(msg: Record<string, unknown>): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
    }
  }

  stop(): void {
    this.send({ type: 'stop' });
  }

  setVoice(voice: string): void {
    this.send({ type: 'set_voice', value: voice });
  }

  private handle(raw: string): void {
    let msg: any;
    try {
      msg = JSON.parse(raw);
    } catch {
      return;
    }
    switch (msg.type) {
      case 'state':
        this.events.onState?.(msg);
        break;
      case 'status':
        this.events.onStatus?.(msg.value);
        break;
      case 'answer_start':
        this.events.onAnswerStart?.(msg);
        break;
      case 'words':
        this.events.onWords?.(msg.items ?? []);
        break;
      case 'answer_end':
        this.events.onAnswerEnd?.();
        break;
      case 'stop':
        this.events.onStop?.();
        break;
      case 'emotion':
        this.events.onEmotion?.(msg.value);
        break;
      case 'history':
        this.events.onHistory?.(msg.items ?? []);
        break;
      case 'voice':
        this.events.onVoice?.(msg.value);
        break;
    }
  }
}
