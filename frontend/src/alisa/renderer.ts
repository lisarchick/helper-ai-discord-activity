// Canvas renderer: composites the 9-emotion sheet, the mouthless sheet and
// the 48-slide viseme strip exactly like the original OBS stage
// (expression cell -> mouthless cell @ crossfade -> viseme slide, scaled).

import {
  CELL_SIZE,
  EmotionId,
  EXPRESSION_SPRITE_MAP,
  resolveClosestSlide48,
  clamp,
  VISEME_SLIDES_48,
} from './sprites';
import { MouthKeyframe, sampleMouth, WordTiming, buildMouthTimeline } from './visemes';

const EXPRESSIONS_URL = 'assets/aistudio/alisa_expressions_cutout.png';
const MOUTHLESS_URL = 'assets/aistudio/alisa_expressions_mouthless_cutout.png';
const VISEMES_URL = 'assets/aistudio/alisa_visemes_48_cutout.png';

export interface TouchReaction {
  emotion: EmotionId;
  untilTs: number;
}

export class HelperRenderer {
  private ctx: CanvasRenderingContext2D;
  private expressions!: HTMLImageElement;
  private mouthless!: HTMLImageElement;
  private visemes48!: HTMLImageElement;
  private loaded = false;

  private emotion: EmotionId = 'neutral';
  private mouth = { openY: 0.02, form: 0.4 };
  private frames: MouthKeyframe[] = [];
  private speechStart = 0;      // performance.now() when words timeline started
  private speaking = false;
  private touchReaction: TouchReaction | null = null;

  // idle animation
  private lastT = 0;
  private blinkUntil = 0;
  private nextBlinkAt = 0;

  constructor(private canvas: HTMLCanvasElement) {
    this.ctx = canvas.getContext('2d')!;
    canvas.width = CELL_SIZE;
    canvas.height = CELL_SIZE;
  }

  async load(): Promise<void> {
    const [a, b, c] = await Promise.all([
      this.loadImage(EXPRESSIONS_URL),
      this.loadImage(MOUTHLESS_URL),
      this.loadImage(VISEMES_URL),
    ]);
    this.expressions = a;
    this.mouthless = b;
    this.visemes48 = c;
    this.loaded = true;
  }

  private loadImage(url: string): Promise<HTMLImageElement> {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error('Failed to load ' + url));
      img.src = url;
    });
  }

  // ------------------------------------------------------------ state input

  /** Current mouth openness 0..1 — drives the audio visualizer. */
  getMouthLevel(): number {
    return this.mouth.openY;
  }

  /** True while a lipsync timeline is playing. */
  isSpeaking(): boolean {
    return this.speaking;
  }

  setEmotion(emotion: string): void {
    this.emotion = (emotion as EmotionId) in EXPRESSION_SPRITE_MAP
      ? (emotion as EmotionId)
      : 'neutral';
  }

  startSpeech(words: WordTiming[]): void {
    this.frames = buildMouthTimeline(words);
    this.speechStart = performance.now();
    this.speaking = true;
  }

  endSpeech(): void {
    this.speaking = false;
    this.frames = [];
  }

  pokeReaction(emotion: EmotionId, ms: number): void {
    this.touchReaction = { emotion, untilTs: performance.now() + ms };
  }

  // ------------------------------------------------------------- render loop

  start(): void {
    const loop = (t: number) => {
      const dt = clamp(t - this.lastT, 4, 100);
      this.lastT = t;
      this.tick(t, dt);
      this.draw(t);
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  }

  private tick(t: number, dt: number): void {
    if (this.speaking && this.frames.length > 0) {
      const tMs = t - this.speechStart;
      this.mouth = sampleMouth(this.frames, tMs, this.mouth, dt);
      // end of timeline -> relax
      const last = this.frames[this.frames.length - 1];
      if (tMs > last.t_ms + 400) {
        this.speaking = false;
      }
    } else {
      // gentle idle breathing of the mouth
      const idle = 0.02 + 0.012 * (0.5 + 0.5 * Math.sin(t / 900));
      this.mouth.openY += (idle - this.mouth.openY) * (dt / 120);
      this.mouth.form += (0.4 - this.mouth.form) * (dt / 200);
    }

    // natural blinking schedule
    if (t > this.nextBlinkAt) {
      this.blinkUntil = t + 140;
      this.nextBlinkAt = t + 2200 + Math.random() * 2600;
    }
  }

  private draw(t: number): void {
    if (!this.loaded) return;
    const ctx = this.ctx;

    let emotion = this.emotion;
    if (this.touchReaction && t < this.touchReaction.untilTs) {
      emotion = this.touchReaction.emotion;
    } else {
      this.touchReaction = null;
    }
    const blink = t < this.blinkUntil && emotion !== 'laugh';
    if (blink && emotion !== 'wink') emotion = 'wink'; // wink cell has closed eyes

    const spec = EXPRESSION_SPRITE_MAP[emotion] ?? EXPRESSION_SPRITE_MAP.neutral;
    const srcX = spec.col * CELL_SIZE;
    const srcY = spec.row * CELL_SIZE;

    ctx.clearRect(0, 0, CELL_SIZE, CELL_SIZE);

    // closed-mouth: painted expression; open-mouth: crossfade to mouthless+viseme
    const mouthBlend = clamp((this.mouth.openY - 0.025) / 0.055, 0, 1);

    if (mouthBlend < 0.99) {
      ctx.globalAlpha = 1.0;
      ctx.drawImage(this.expressions, srcX, srcY, CELL_SIZE, CELL_SIZE, 0, 0, CELL_SIZE, CELL_SIZE);
    }

    if (mouthBlend > 0.01) {
      ctx.save();
      ctx.globalAlpha = mouthBlend;
      ctx.drawImage(this.mouthless, srcX, srcY, CELL_SIZE, CELL_SIZE, 0, 0, CELL_SIZE, CELL_SIZE);

      const slideIdx = Math.round(clamp(resolveClosestSlide48(this.mouth.openY, this.mouth.form), 0, 47));
      const slide = VISEME_SLIDES_48[slideIdx]!
      const scaleX = 1 + slide.form * 0.022;
      const scaleY = 0.98 + slide.openY * 0.04;

      ctx.translate(167, 211);
      ctx.scale(scaleX, scaleY);
      ctx.translate(-167, -211);
      ctx.drawImage(
        this.visemes48,
        slideIdx * CELL_SIZE, 0, CELL_SIZE, CELL_SIZE,
        0, 0, CELL_SIZE, CELL_SIZE
      );
      ctx.restore();
    }
  }
}
