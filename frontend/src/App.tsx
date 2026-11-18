import { useEffect, useRef, useState, useCallback } from 'react';
import { HelperRenderer } from './alisa/renderer';
import { BridgeClient, BotStatus, HistoryItem } from './alisa/bridge';
import './app.css';

const VOICES = [
  { id: 'ru-RU-SvetlanaNeural', label: 'Светлана — мягкая' },
  { id: 'ru-RU-DariyaNeural', label: 'Дарья — живая' },
];

const STATUS_LABEL: Record<BotStatus, string> = {
  idle: 'на связи',
  listening: 'слушаю',
  thinking: 'думаю',
  speaking: 'отвечаю',
  stopped: 'на паузе',
};

type Bg = 'transparent' | 'dark' | 'cozy';

interface Toast {
  id: number;
  text: string;
}

let toastSeq = 1;

export default function App() {
  const canvasHostRef = useRef<HTMLDivElement>(null);
  const visualizerRef = useRef<HTMLCanvasElement>(null);
  const rendererRef = useRef<HelperRenderer | null>(null);
  const bridgeRef = useRef<BridgeClient | null>(null);

  const [connected, setConnected] = useState(false);
  const [status, setStatus] = useState<BotStatus>('idle');
  const [subtitles, setSubtitles] = useState(true);
  const [answerText, setAnswerText] = useState('');
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [voice, setVoice] = useState(VOICES[0].id);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [bg, setBg] = useState<Bg>('dark');
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [questions, setQuestions] = useState(0);

  const pushToast = useCallback((text: string) => {
    const id = toastSeq++;
    setToasts((t) => [...t.slice(-2), { id, text }]);
    window.setTimeout(() => {
      setToasts((t) => t.filter((x) => x.id !== id));
    }, 2600);
  }, []);

  // ------------------------------------------------------------------ setup
  useEffect(() => {
    // guard against duplicate canvases (HMR / double effect)
    const host = canvasHostRef.current!;
    host.innerHTML = '';
    const canvas = document.createElement('canvas');
    canvas.className = 'alisa-canvas';
    host.appendChild(canvas);
    const renderer = new HelperRenderer(canvas);
    rendererRef.current = renderer;
    renderer.load().then(() => renderer.start()).catch(console.error);

    const bridge = new BridgeClient({
      onState: (p) => {
        setStatus(p.status);
        setHistory(p.history ?? []);
        setQuestions((p.history ?? []).filter((h) => h.role === 'user').length);
        if (p.voice) setVoice(p.voice);
      },
      onStatus: setStatus,
      onAnswerStart: (p) => {
        setAnswerText(p.text);
        renderer.setEmotion(p.emotion);
      },
      onWords: (words) => renderer.startSpeech(words),
      onAnswerEnd: () => {
        renderer.endSpeech();
        renderer.setEmotion('neutral');
      },
      onStop: () => {
        renderer.endSpeech();
        renderer.setEmotion('neutral');
        setAnswerText('');
        pushToast('⏹ остановлено');
      },
      onEmotion: (e) => renderer.setEmotion(e),
      onHistory: (items) => {
        setHistory(items);
        setQuestions(items.filter((h) => h.role === 'user').length);
      },
      onVoice: (v) => setVoice(v),
    });
    bridgeRef.current = bridge;
    bridge.connect();

    const iv = window.setInterval(() => {
      setConnected(bridge['ws']?.readyState === WebSocket.OPEN);
    }, 1000);

    return () => {
      window.clearInterval(iv);
      bridge.close();
      host.innerHTML = '';
    };
  }, [pushToast]);

  // ------------------------------------------------- audio visualizer
  useEffect(() => {
    const cv = visualizerRef.current;
    if (!cv) return;
    const ctx = cv.getContext('2d')!;
    const BARS = 36;
    let raf = 0;
    const levels = new Array(BARS).fill(0);

    const loop = (t: number) => {
      const r = rendererRef.current;
      const level = r ? Math.min(1, r.getMouthLevel() * 1.15) : 0;
      const speaking = r?.isSpeaking() ?? false;

      const w = (cv.width = cv.clientWidth * 2);
      const h = (cv.height = cv.clientHeight * 2);
      ctx.clearRect(0, 0, w, h);

      const bw = w / BARS;
      for (let i = 0; i < BARS; i++) {
        const centerBias = 1 - Math.abs(i - BARS / 2) / (BARS / 2);
        const wobble =
          0.5 + 0.5 * Math.sin(t / 120 + i * 0.7) * Math.sin(t / 310 + i * 0.23);
        const target = speaking
          ? Math.max(0.06, level * (0.35 + 0.65 * centerBias) * (0.4 + 0.6 * wobble))
          : 0.05 + 0.04 * wobble * centerBias;
        levels[i] += (target - levels[i]) * 0.35;
        const bh = Math.max(3, levels[i] * h);
        const x = i * bw + bw * 0.25;
        const y = (h - bh) / 2;
        ctx.fillStyle = speaking ? 'rgba(122,162,247,0.85)' : 'rgba(124,131,152,0.4)';
        ctx.beginPath();
        ctx.roundRect(x, y, bw * 0.5, bh, bw * 0.25);
        ctx.fill();
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, []);

  // -------------------------------------------------------- hotkeys
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement) return;
      if (e.code === 'Space') {
        e.preventDefault();
        doStop();
      } else if (e.key.toLowerCase() === 'h') {
        setHistoryOpen((v) => !v);
      } else if (e.key.toLowerCase() === 's') {
        setSubtitles((v) => !v);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  // -------------------------------------------------------- touch zones
  const pettingRef = useRef(false);
  const pokeCountRef = useRef({ n: 0, last: 0 });
  const petDistRef = useRef(0);
  const lastPosRef = useRef<{ x: number; y: number } | null>(null);

  const onPointerDown = (e: React.PointerEvent) => {
    pettingRef.current = true;
    lastPosRef.current = { x: e.clientX, y: e.clientY };
  };
  const onPointerUp = () => {
    pettingRef.current = false;
    lastPosRef.current = null;
  };
  const onPointerMove = (e: React.PointerEvent) => {
    const last = lastPosRef.current;
    lastPosRef.current = { x: e.clientX, y: e.clientY };
    if (!pettingRef.current || !last) return;
    if (hitZone(e) !== 'hair') return;
    petDistRef.current += Math.abs(e.clientX - last.x) + Math.abs(e.clientY - last.y);
    if (petDistRef.current > 90) {
      petDistRef.current = 0;
      rendererRef.current?.pokeReaction(Math.random() < 0.5 ? 'joy' : 'laugh', 1800);
      pushToast(MOOD_LINES[Math.floor(Math.random() * MOOD_LINES.length)]);
    }
  };
  const onPointerClick = (e: React.MouseEvent) => {
    const zone = hitZone(e);
    const now = performance.now();
    if (zone === 'face') {
      const c = pokeCountRef.current;
      c.n = now - c.last < 1500 ? c.n + 1 : 1;
      c.last = now;
      if (c.n >= 3) {
        rendererRef.current?.pokeReaction('angry', 2000);
        pushToast(POKE_LINES_ANGRY[Math.floor(Math.random() * POKE_LINES_ANGRY.length)]);
      } else {
        rendererRef.current?.pokeReaction('embarrassed', 1600);
        pushToast(POKE_LINES[Math.floor(Math.random() * POKE_LINES.length)]);
      }
    } else if (zone === 'hair') {
      rendererRef.current?.pokeReaction('joy', 1400);
      pushToast(MOOD_LINES[Math.floor(Math.random() * MOOD_LINES.length)]);
    }
  };
  const hitZone = (e: { clientX: number; clientY: number }): 'hair' | 'face' | 'none' => {
    const host = canvasHostRef.current;
    if (!host) return 'none';
    const r = host.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width;
    const y = (e.clientY - r.top) / r.height;
    if (x < 0.2 || x > 0.8) return 'none';
    if (y < 0.34) return 'hair';
    if (y < 0.72) return 'face';
    return 'none';
  };

  // ------------------------------------------------------------- actions
  const doStop = useCallback(() => {
    bridgeRef.current?.stop();
    rendererRef.current?.endSpeech();
    rendererRef.current?.setEmotion('neutral');
    setAnswerText('');
  }, []);

  const changeVoice = (v: string) => {
    setVoice(v);
    bridgeRef.current?.setVoice(v);
    const label = VOICES.find((x) => x.id === v)?.label ?? v;
    pushToast(`голос: ${label}`);
  };

  return (
    <div className={`app bg-${bg}`}>
      <div className="bg-vignette" />
      <div className="bg-grid" />

      {/* status bar */}
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">H</span>
          <div className="brand-text">
            <span className="brand-name">Helper AI</span>
            <span className="brand-sub">голосовой ассистент</span>
          </div>
        </div>

        <span className={`badge st-${status}`}>
          <i className={`dot ${connected ? 'on' : 'off'}`} />
          {STATUS_LABEL[status]}
        </span>

        <div className="spacer" />

        <span className="stat" title="Вопросов отвечено">{questions} ♥</span>
        <button className="btn ghost" onClick={() => setHistoryOpen(true)} title="H">история</button>
        <button className="btn ghost" onClick={() => setSettingsOpen(true)}>настройки</button>
      </header>

      {/* model stage + touch zones */}
      <main className="stage-wrap">
        <div className="stage-side left">
          <div className="hint">
            <span className="hint-key">голос · в канале</span>
            <span>«helper» + вопрос → бот ответит здесь</span>
          </div>
          <div className="hint">
            <span className="hint-key">стоп</span>
            <span>голосом в канале / в чат / Space тут</span>
          </div>
          <div className="hint">
            <span className="hint-key">моделька</span>
            <span>гладь волосы, тычь в щёки</span>
          </div>
        </div>

        <div
          className="stage"
          ref={canvasHostRef}
          onPointerDown={onPointerDown}
          onPointerUp={onPointerUp}
          onPointerLeave={onPointerUp}
          onPointerMove={onPointerMove}
          onClick={onPointerClick}
        />

        <div className="stage-side right">
          <canvas ref={visualizerRef} className="visualizer" />
          <span className="visualizer-label">голос</span>
        </div>

        {/* subtitles */}
        {subtitles && answerText && (
          <div className="subtitles">{answerText}</div>
        )}

        {/* toasts */}
        <div className="toasts">
          {toasts.map((t) => (
            <div key={t.id} className="toast">{t.text}</div>
          ))}
        </div>
      </main>

      {/* control dock */}
      <footer className="dock">
        <button className="btn" onClick={() => setSubtitles((s) => !s)} title="S">
          <i className={`ico ${subtitles ? 'on' : ''}`}>▭</i> субтитры
          <span className="state">{subtitles ? 'вкл' : 'выкл'}</span>
        </button>
        <button className="btn danger" onClick={doStop} title="Space">
          <i className="ico">■</i> стоп
        </button>
        <div className="vol">
          <span>🔉</span>
          <input
            type="range" min={0} max={100} defaultValue={80}
            onChange={(e) => {
              const v = Number(e.target.value);
              document.documentElement.style.setProperty(
                '--stage-dim', String(1 - v / 250)
              );
              bridgeRef.current?.send({ type: 'set_volume', value: v });
            }}
          />
          <span className="vol-pct">80%</span>
        </div>
      </footer>

      {/* history drawer */}
      {historyOpen && (
        <div className="drawer-mask" onClick={() => setHistoryOpen(false)}>
          <aside className="drawer" onClick={(e) => e.stopPropagation()}>
            <h3>история диалога</h3>
            <button className="close" onClick={() => setHistoryOpen(false)}>×</button>
            <div className="history-list">
              {history.length === 0 && <p className="muted">Пока пусто — скажи «helper» и спроси что-нибудь.</p>}
              {history.slice().reverse().map((h, i) => (
                <div key={i} className={`msg ${h.role}`}>
                  <span className="who">{h.role === 'user' ? 'ты' : 'хелпер'}</span>
                  {h.text}
                </div>
              ))}
            </div>
          </aside>
        </div>
      )}

      {/* settings */}
      {settingsOpen && (
        <div className="drawer-mask" onClick={() => setSettingsOpen(false)}>
          <aside className="drawer" onClick={(e) => e.stopPropagation()}>
            <h3>настройки</h3>
            <button className="close" onClick={() => setSettingsOpen(false)}>×</button>

            <label className="field">
              голос
              <select value={voice} onChange={(e) => changeVoice(e.target.value)}>
                {VOICES.map((v) => (
                  <option key={v.id} value={v.id}>{v.label}</option>
                ))}
              </select>
            </label>

            <label className="field">
              фон
              <select value={bg} onChange={(e) => setBg(e.target.value as Bg)}>
                <option value="transparent">прозрачный</option>
                <option value="dark">тёмный</option>
                <option value="cozy">уютная комната</option>
              </select>
            </label>

            <div className="kbd-list">
              <div><kbd>Space</kbd> остановить ответ</div>
              <div><kbd>S</kbd> субтитры вкл/выкл</div>
              <div><kbd>H</kbd> история</div>
            </div>

            <button
              className="btn ghost wide"
              onClick={() => {
                bridgeRef.current?.send({ type: 'clear_memory' });
                pushToast('память очищена');
              }}
            >
              очистить память диалога
            </button>
          </aside>
        </div>
      )}
    </div>
  );
}

const MOOD_LINES = [
  'мур~ как приятно',
  'хелпер довольна',
  'ещё погладь',
  'ня~ продолжай',
];

const POKE_LINES = [
  'эй! не тыкай',
  'что такое?',
  'щекотно же!',
];

const POKE_LINES_ANGRY = [
  'всё, я обиделась',
  'хватит тыкать!',
  'я не игрушка!',
];
