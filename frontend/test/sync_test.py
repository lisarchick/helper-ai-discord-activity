# Sync test (Python): real edge-tts synthesis of Russian phrases ->
# word timings -> frontend mouth timeline logic (ported 1:1) -> slide indices.
# Verifies the avatar's mouth would track the audio correctly.
# Run: uv run --with edge-tts python test/sync_test.py

import asyncio
import sys

import edge_tts

PHRASES = [
    "Привет! Меня зовут Алиса, и я очень рада тебя видеть.",
    "Стоп. Сейчас я отвечу на твой вопрос подробно и с выражением.",
    "Оу, это удивительно! Расскажи мне больше об этом, пожалуйста.",
]

# --- frontend logic ported for test (mirror of src/alisa/sprites.ts + visemes.ts) ---
VISEME_SLIDES_48 = [
    (0.02,0.40),(0.14,0.44),(0.28,0.48),(0.42,0.52),(0.56,0.55),(0.70,0.58),
    (0.82,0.60),(0.92,0.62),(0.89,0.40),(0.86,0.18),(0.83,-0.05),(0.80,-0.26),
    (0.78,-0.45),(0.72,-0.50),(0.65,-0.55),(0.58,-0.60),(0.52,-0.65),(0.46,-0.70),
    (0.36,-0.45),(0.25,-0.15),(0.12,0.15),(0.12,0.55),(0.22,0.70),(0.30,0.84),
    (0.38,0.95),(0.46,0.88),(0.55,0.81),(0.62,0.75),(0.72,0.70),(0.82,0.66),
    (0.56,0.22),(0.70,0.14),(0.08,0.42),(0.21,0.46),(0.35,0.50),(0.49,0.54),
    (0.63,0.57),(0.76,0.59),(0.87,0.29),(0.81,-0.16),(0.68,-0.52),(0.55,-0.63),
    (0.17,0.63),(0.26,0.77),(0.50,0.84),(0.77,0.68),(0.04,0.58),(0.01,0.25),
]

def resolve_closest_slide48(open_y, form):
    best, best_d = 0, float("inf")
    for i, (o, f) in enumerate(VISEME_SLIDES_48):
        d = (o - open_y) ** 2 + 0.6 * (f - form) ** 2
        if d < best_d:
            best_d, best = d, i
    return best

LETTER_TARGETS = {
    'а':(0.92,0.62),'я':(0.80,0.60),'о':(0.78,-0.45),'ё':(0.72,-0.40),
    'у':(0.46,-0.70),'ю':(0.42,-0.62),'и':(0.38,0.95),'й':(0.30,0.80),
    'э':(0.62,0.75),'е':(0.55,0.78),'ы':(0.50,0.60),
    'м':(0.02,0.40),'б':(0.06,0.40),'п':(0.04,0.40),
    'в':(0.25,-0.30),'ф':(0.22,-0.30),'ш':(0.30,-0.35),'ж':(0.32,-0.30),
    'щ':(0.28,-0.30),'ч':(0.30,0.35),'ц':(0.28,0.45),
    'т':(0.20,0.55),'д':(0.28,0.55),'н':(0.20,0.50),'л':(0.30,0.55),
    'с':(0.20,0.70),'з':(0.24,0.68),'р':(0.34,0.50),
    'к':(0.26,0.50),'г':(0.28,0.50),'х':(0.34,0.55),
    'a':(0.92,0.62),'o':(0.78,-0.45),'u':(0.46,-0.70),'i':(0.38,0.95),
    'e':(0.62,0.75),'y':(0.50,0.60),
}
CLOSED = (0.02, 0.40)
VOWELS = set("аяоёуюиэеыaoiue")

def weight(c):
    if c in VOWELS:
        return 1.9
    if c in "мбп":
        return 0.7
    return 1.0

def build_mouth_timeline(words):
    frames = []
    for w in words:
        letters = [c for c in w["word"].lower() if ('a' <= c <= 'z') or ('а' <= c <= 'ё')]
        if not letters:
            continue
        total = sum(weight(c) for c in letters)
        t = w["offset_ms"]
        dur = max(40, w["duration_ms"])
        for ch in letters:
            share = weight(ch) / total * dur
            o, f = LETTER_TARGETS.get(ch, CLOSED)
            frames.append((round(t), o, f))
            frames.append((round(t + share * 0.9), o*0.72 + CLOSED[0]*0.28, f*0.85 + CLOSED[1]*0.15))
            t += share
    frames.sort(key=lambda x: x[0])
    return frames

def sample_mouth(frames, t_ms, prev, dt_ms, smoothing=40.0):
    if not frames:
        return prev
    target = frames[-1]
    for f in frames:
        if f[0] >= t_ms:
            target = f
            break
    a = max(0.0, min(1.0, dt_ms / smoothing))
    return (
        prev[0] + (target[1] - prev[0]) * a,
        prev[1] + (target[2] - prev[1]) * a,
    )

def render_step(frames, t_ms, prev, dt_ms):
    """Faithful mirror of AlisaRenderer.tick: lipsync while speaking,
    ease to idle 400ms after the last keyframe."""
    last_t = frames[-1][0] if frames else 0
    if frames and t_ms <= last_t + 400:
        return sample_mouth(frames, t_ms, prev, dt_ms)
    idle = 0.03
    a = max(0.0, min(1.0, dt_ms / 120.0))
    return (prev[0] + (idle - prev[0]) * a, prev[1] + (0.4 - prev[1]) * a)
# --- end port ---

async def synth(phrase, voice):
    communicate = edge_tts.Communicate(text=phrase, voice=voice, rate="+4%", boundary="WordBoundary")
    chunks = []
    words = []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            chunks.append(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            words.append({
                "offset_ms": chunk["offset"] // 10_000,
                "duration_ms": chunk["duration"] // 10_000,
                "word": chunk["text"],
            })
    return b"".join(chunks), words

def mp3_duration_ms(buf):
    i = 0
    if buf[:3] == b"ID3":
        size = ((buf[6] & 0x7F) << 21) | ((buf[7] & 0x7F) << 14) | ((buf[8] & 0x7F) << 7) | (buf[9] & 0x7F)
        i = 10 + size
    brates_v1 = [0,32,40,48,56,64,80,96,112,128,160,192,224,256,320,0]
    brates_v2 = [0,8,16,24,32,40,48,56,64,80,96,112,128,144,160,0]  # MPEG-2 LSF
    srates_v1 = [44100,48000,32000,0]      # MPEG-1
    srates_v2 = [22050,24000,16000,0]      # MPEG-2 / 2.5 (edge-tts = 24kHz)
    total_samples = 0
    sr = 24000
    while i + 4 <= len(buf):
        if buf[i] == 0xFF and (buf[i+1] & 0xE0) == 0xE0:
            ver_bits = (buf[i+1] >> 3) & 0x3   # 3=MPEG-1, 2=MPEG-2, 0=MPEG-2.5
            mpeg1 = ver_bits == 3
            br = (brates_v1 if mpeg1 else brates_v2)[(buf[i+2] >> 4) & 0xF]
            sr = (srates_v1 if mpeg1 else srates_v2)[(buf[i+2] >> 2) & 0x3] or sr
            spf = 1152 if mpeg1 else 576
            fl = max(1, (144000 if mpeg1 else 72000) * br // sr) if br else 1
            total_samples += spf
            i += fl
        else:
            i += 1
    return round(total_samples * 1000 / sr) if total_samples else 0

failures = 0
def check(name, cond, detail=""):
    global failures
    print(f"{'PASS' if cond else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not cond:
        failures += 1

async def main():
    for phrase in PHRASES:
        print(f"\n--- «{phrase}»")
        mp3, words = await synth(phrase, "ru-RU-SvetlanaNeural")
        audio_ms = mp3_duration_ms(mp3)
        first_w, last_w = words[0], words[-1]
        last_end = last_w["offset_ms"] + last_w["duration_ms"]

        check("edge-tts выдал слово-тайминги", len(words) > 0, f"({len(words)} слов)")
        check("тайминги монотонны",
              all(words[i]["offset_ms"] >= words[i-1]["offset_ms"] for i in range(1, len(words))))
        check("тайминги покрывают аудио", last_end <= audio_ms and last_end > audio_ms * 0.7,
              f"речь {last_end}ms / аудио {audio_ms}ms")
        check("старт речи почти сразу (<300ms)", first_w["offset_ms"] < 300, f"{first_w['offset_ms']}ms")

        frames = build_mouth_timeline(words)
        check("таймлайн рта построен", len(frames) > 0, f"({len(frames)} ключей)")

        # simulate 60fps render loop
        mouth = (0.02, 0.4)
        slides = []
        t = 0.0
        while t <= audio_ms:
            mouth = render_step(frames, t, mouth, 16.7)
            slides.append(resolve_closest_slide48(*mouth))
            t += 16.7
        unique = len(set(slides))
        check("рот двигается (много форм)", unique >= 6, f"{unique} уникальных слайдов из 48")
        check("все индексы слайдов валидны (0..47)", all(0 <= s <= 47 for s in slides))

        # mouth opens at some point inside each word that has a vowel
        open_cnt, vowel_words = 0, 0
        for w in words:
            if not any(c in VOWELS for c in w["word"].lower()):
                continue
            vowel_words += 1
            m = (0.02, 0.4)
            tt = 0.0
            max_o = 0.0
            end = w["offset_ms"] + w["duration_ms"]
            while tt <= end:
                m = render_step(frames, tt, m, 16.7)
                if w["offset_ms"] <= tt:
                    max_o = max(max_o, m[0])
                tt += 16.7
            if max_o > 0.3:
                open_cnt += 1
        check("рот раскрывается в словах с гласными", open_cnt >= vowel_words * 0.85,
              f"{open_cnt}/{vowel_words} слов")

        # mouth closes near end of phrase
        m = (0.02, 0.4)
        tt = 0.0
        while tt <= audio_ms:
            m = render_step(frames, tt, m, 16.7)
            tt += 16.7
        check("рот закрывается к концу фразы", m[0] < 0.35, f"openY={m[0]:.2f}")

        # responsiveness: reach open mouth within ~120ms of vowel onset
        mid = round(first_w["offset_ms"] + first_w["duration_ms"] * 0.6)
        m = (0.02, 0.4)
        tt = max(0.0, mid - 120)
        while tt <= mid:
            m = sample_mouth(frames, tt, m, 16.7)
            tt += 16.7
        check("рот начинает открываться < 120ms от гласной", m[0] > 0.15, f"openY={m[0]:.2f} @t={mid}ms")

    print("\n=== ALL SYNC TESTS PASSED ===" if failures == 0 else f"\n=== {failures} FAILURES ===")
    sys.exit(0 if failures == 0 else 1)

asyncio.run(main())
