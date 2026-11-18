// Sprite data ported verbatim from the original rigging studio
// (conceptLogic.ts): 9-emotion 3x3 sheet + 48-slide viseme strip, 334px cells.

export const CELL_SIZE = 334;

export type EmotionId =
  | 'neutral' | 'joy' | 'laugh' | 'sad' | 'surprise'
  | 'angry' | 'thinking' | 'wink' | 'embarrassed';

export const EMOTIONS: EmotionId[] = [
  'neutral', 'joy', 'laugh', 'sad', 'surprise',
  'angry', 'thinking', 'wink', 'embarrassed',
];

export const EXPRESSION_SPRITE_MAP: Record<EmotionId, { col: number; row: number }> = {
  neutral:     { col: 0, row: 0 },
  joy:         { col: 1, row: 0 },
  laugh:       { col: 2, row: 0 },
  sad:         { col: 0, row: 1 },
  surprise:    { col: 1, row: 1 },
  angry:       { col: 2, row: 1 },
  thinking:    { col: 0, row: 2 },
  wink:        { col: 1, row: 2 },
  embarrassed: { col: 2, row: 2 },
};

export interface VisemeSlide {
  index: number;
  openY: number;
  form: number;
}

// 48-slide viseme strip: (openY, form) targets per slide (ported from
// CUTOUT_VISEME_SLIDES_48 / CUTOUT_VISEME_SLIDES_32 + extra slides).
const S = (index: number, openY: number, form: number): VisemeSlide => ({ index, openY, form });

export const VISEME_SLIDES_48: VisemeSlide[] = [
  S(0, 0.02, 0.40), S(1, 0.14, 0.44), S(2, 0.28, 0.48), S(3, 0.42, 0.52),
  S(4, 0.56, 0.55), S(5, 0.70, 0.58), S(6, 0.82, 0.60), S(7, 0.92, 0.62),
  S(8, 0.89, 0.40), S(9, 0.86, 0.18), S(10, 0.83, -0.05), S(11, 0.80, -0.26),
  S(12, 0.78, -0.45), S(13, 0.72, -0.50), S(14, 0.65, -0.55), S(15, 0.58, -0.60),
  S(16, 0.52, -0.65), S(17, 0.46, -0.70), S(18, 0.36, -0.45), S(19, 0.25, -0.15),
  S(20, 0.12, 0.15), S(21, 0.12, 0.55), S(22, 0.22, 0.70), S(23, 0.30, 0.84),
  S(24, 0.38, 0.95), S(25, 0.46, 0.88), S(26, 0.55, 0.81), S(27, 0.62, 0.75),
  S(28, 0.72, 0.70), S(29, 0.82, 0.66), S(30, 0.56, 0.22), S(31, 0.70, 0.14),
  S(32, 0.08, 0.42), S(33, 0.21, 0.46), S(34, 0.35, 0.50), S(35, 0.49, 0.54),
  S(36, 0.63, 0.57), S(37, 0.76, 0.59), S(38, 0.87, 0.29), S(39, 0.81, -0.16),
  S(40, 0.68, -0.52), S(41, 0.55, -0.63), S(42, 0.17, 0.63), S(43, 0.26, 0.77),
  S(44, 0.50, 0.84), S(45, 0.77, 0.68), S(46, 0.04, 0.58), S(47, 0.01, 0.25),
];

export function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

/** Closest of the 48 slides for continuous (openY, form) mouth state. */
export function resolveClosestSlide48(openY: number, form: number): number {
  let best = VISEME_SLIDES_48[0];
  let bestDist = Infinity;
  for (const slide of VISEME_SLIDES_48) {
    const dOpen = slide.openY - openY;
    const dForm = slide.form - form;
    // form weighted a bit lower: openness dominates perceived lipsync
    const dist = dOpen * dOpen + 0.6 * dForm * dForm;
    if (dist < bestDist) {
      bestDist = dist;
      best = slide;
    }
  }
  return best.index;
}
