// Lipsync timeline builder: converts edge-tts word timings into a per-letter
// mouth-target timeline over the 48-slide viseme space.

import {
  resolveClosestSlide48,
  VisemeSlide,
  VISEME_SLIDES_48,
} from './sprites';

export interface WordTiming {
  offset_ms: number;
  duration_ms: number;
  word: string;
}

export interface MouthKeyframe {
  t_ms: number;      // absolute time from speech start
  openY: number;
  form: number;
}

/** Cyrillic letter -> (openY, form) mouth target. */
const LETTER_TARGETS: Record<string, [number, number]> = {
  // vowels
  'а': [0.92, 0.62], 'я': [0.80, 0.60],
  'о': [0.78, -0.45], 'ё': [0.72, -0.40],
  'у': [0.46, -0.70], 'ю': [0.42, -0.62],
  'и': [0.38, 0.95], 'й': [0.30, 0.80],
  'э': [0.62, 0.75], 'е': [0.55, 0.78], 'ы': [0.50, 0.60],
  // closed lips
  'м': [0.02, 0.40], 'б': [0.06, 0.40], 'п': [0.04, 0.40],
  // rounded-ish
  'в': [0.25, -0.30], 'ф': [0.22, -0.30], 'ш': [0.30, -0.35],
  'ж': [0.32, -0.30], 'щ': [0.28, -0.30], 'ч': [0.30, 0.35], 'ц': [0.28, 0.45],
  // dental/alveolar: slightly open, neutral-wide
  'т': [0.20, 0.55], 'д': [0.28, 0.55], 'н': [0.20, 0.50], 'л': [0.30, 0.55],
  'с': [0.20, 0.70], 'з': [0.24, 0.68], 'р': [0.34, 0.50],
  'к': [0.26, 0.50], 'г': [0.28, 0.50], 'х': [0.34, 0.55],
  // latin fallback (for rare english words)
  'a': [0.92, 0.62], 'o': [0.78, -0.45], 'u': [0.46, -0.70],
  'i': [0.38, 0.95], 'e': [0.62, 0.75], 'y': [0.50, 0.60],
};

const CLOSED: [number, number] = [0.02, 0.40];

const VOWELS = new Set('аяоёуюиэеыaoiue'.split(''));

function letterWeight(ch: string): number {
  if (VOWELS.has(ch)) return 1.9; // vowels are held longer
  if ('мбп'.includes(ch)) return 0.7; // quick lip closures
  return 1.0;
}

/**
 * Build a mouth keyframe timeline from word timings.
 * Word duration is distributed across letters proportional to letter weight;
 * each letter eases toward its target then the next takes over.
 */
export function buildMouthTimeline(words: WordTiming[]): MouthKeyframe[] {
  const frames: MouthKeyframe[] = [];
  for (const w of words) {
    const letters = Array.from(w.word.toLowerCase()).filter((c) => /[a-zа-яё]/.test(c));
    if (letters.length === 0) continue;

    const totalWeight = letters.reduce((acc, c) => acc + letterWeight(c), 0);
    let t = w.offset_ms;
    const dur = Math.max(40, w.duration_ms);

    for (const ch of letters) {
      const share = (letterWeight(ch) / totalWeight) * dur;
      const target = LETTER_TARGETS[ch] ?? CLOSED;
      // peak at ~55% into the letter, then release toward next
      frames.push({ t_ms: Math.round(t), openY: target[0], form: target[1] });
      frames.push({
        t_ms: Math.round(t + share * 0.9),
        openY: target[0] * 0.72 + CLOSED[0] * 0.28,
        form: target[1] * 0.85 + CLOSED[1] * 0.15,
      });
      t += share;
    }
  }
  frames.sort((a, b) => a.t_ms - b.t_ms);
  return frames;
}

/** Smooth (lerp) evaluation of the timeline at time t with attack/release time constant. */
export function sampleMouth(
  frames: MouthKeyframe[],
  t_ms: number,
  prev: { openY: number; form: number },
  dt_ms: number,
  smoothing_ms = 40
): { openY: number; form: number } {
  if (frames.length === 0) return prev;
  // find surrounding keyframes
  let target = frames[frames.length - 1];
  for (let i = 0; i < frames.length; i++) {
    if (frames[i].t_ms >= t_ms) {
      target = frames[i];
      break;
    }
  }
  const alpha = clamp01(dt_ms / Math.max(1, smoothing_ms));
  return {
    openY: prev.openY + (target.openY - prev.openY) * alpha,
    form: prev.form + (target.form - prev.form) * alpha,
  };
}

function clamp01(v: number): number {
  return Math.max(0, Math.min(1, v));
}

export function slideIndexFor(openY: number, form: number): number {
  return resolveClosestSlide48(openY, form);
}

export function slideByIndex(i: number): VisemeSlide {
  return VISEME_SLIDES_48[i] ?? { index: 0, openY: 0.02, form: 0.4 };
}
