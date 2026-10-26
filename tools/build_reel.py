#!/usr/bin/env python3
"""Сборка ролика «On time»: фон (1+ клипов), голос, музыка, текст по фразам (Lora курсив).

Использование: build_reel.py spec.json
spec: {
  "out": "reel.mp4", "voice": "voice.wav", "words": "words.json",   # [[слово, start_ms, end_ms], ...]
  "music": "track.mp3", "music_offset": 5, "music_volume": 0.2,
  "clips": ["a.mp4", "b.mp4"], "phrases": ["Запомни...", "..."],
  "font_dir": "fonts/",
  "align": 2, "marginv": 620,         # необязательно: 8 = текст сверху, если низ кадра светлый
  "style": "words",                   # необязательно: слова появляются по одному (гротеск, строчные, по центру)
  "letterbox": true                   # необязательно: кадр 16:9 полосой на тёмном фоне
}
Фразы сопоставляются со словами озвучки по количеству слов (токены без букв не считаются).
"""
import json, re, subprocess, sys, os, tempfile

W, H, FPS = 1080, 1920, 30
XFADE = 0.8
TAIL = 1.5
OUTRO = 1.6  # чёрная заставка «On time» в конце, как в нарезках


def dur(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                   "-of", "csv=p=0", path])
    return float(out)


def tokens(s):
    return [t for t in s.split() if re.search(r"\w", t)]


def wrap(text, width=18):
    lines, cur = [], ""
    for w in text.split():
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    lines.append(cur)
    # не оставлять в последней строке одно короткое слово вроде «2».»
    if len(lines) > 1 and len(lines[-1]) <= 4 and " " in lines[-2]:
        head, last = lines[-2].rsplit(" ", 1)
        lines[-2], lines[-1] = head, last + " " + lines[-1]
    return r"\N".join(lines)


def ts(t):
    t = max(t, 0)
    h, r = divmod(t, 3600)
    m, s = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def clean(word):
    return re.sub(r"[^\w\-]", "", word.lower()).strip("-")


def word_line(phrase, ws, st):
    """Фраза, где каждое слово проявляется в момент произнесения."""
    parts = []
    for tok, (_, ws_ms, _) in zip(tokens(phrase), ws):
        t0 = max(0, int(ws_ms - st * 1000))
        parts.append(f"{{\\alpha&HFF&\\t({t0},{t0 + 300},\\alpha&H00&)}}{clean(tok)}")
    lines, cur, cur_toks, n = [], [], [], 0
    for part, tok in zip(parts, tokens(phrase)):
        if cur and n + 1 + len(clean(tok)) > 21:
            # предлог или союз в одну-две буквы переносим вместе со следующим словом
            carry = [cur.pop()] if len(cur) > 1 and len(clean(cur_toks[-1])) <= 2 else []
            lines.append(" ".join(cur))
            cur = carry
            n = len(clean(cur_toks[-1])) if carry else 0
        cur_toks.append(tok)
        cur.append(part)
        n += len(clean(tok)) + (1 if n else 0)
    lines.append(" ".join(cur))
    return r"\N".join(lines)


def make_ass(phrases, words, total, path, align=2, marginv=620, style="phrases", outro=0):
    words = [w for w in words if re.search(r"\w", w[0])]
    counts = [len(tokens(p)) for p in phrases]
    if sum(counts) != len(words):
        sys.exit(f"слов во фразах {sum(counts)}, в озвучке {len(words)}")
    spans, i = [], 0
    for c in counts:
        spans.append((words[i][1] / 1000, words[i + c - 1][2] / 1000))
        i += c
    events, i = [], 0
    for k, (p, (st, en)) in enumerate(zip(phrases, spans)):
        ws = words[i:i + counts[k]]
        i += counts[k]
        if k + 1 < len(spans):
            nxt = spans[k + 1][0]
            end = nxt - 0.05 if nxt - en < 1.0 else en + 0.4
        else:
            end = total
        if style == "words":
            events.append(f"Dialogue: 0,{ts(st)},{ts(end)},Words,,0,0,0,,{{\\fad(0,150)\\blur3}}{word_line(p, ws, st)}")
        else:
            events.append(f"Dialogue: 0,{ts(st - 0.08)},{ts(end)},Main,,0,0,0,,{{\\fad(150,100)\\blur4}}{wrap(p)}")
    if outro:
        events.append(f"Dialogue: 0,{ts(total)},{ts(total + outro)},Brand,,0,0,0,,{{\\fad(400,0)}}On time")
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,Lora,96,&H00FFFFFF,&H00FFFFFF,&H50000000,&H96000000,0,1,0,0,100,100,0,0,1,6,3,{align},80,80,{marginv},1
Style: Brand,Lora,130,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,1,0,0,100,100,0,0,1,0,0,5,60,60,0,1
Style: Words,Montserrat,64,&H00FFFFFF,&H00FFFFFF,&H64000000,&H00000000,0,0,0,0,100,100,4,0,1,3,0,5,90,90,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(head + "\n".join(events) + "\n")


def main(spec_path):
    spec = json.load(open(spec_path, encoding="utf-8"))
    base = os.path.dirname(os.path.abspath(spec_path))
    p = lambda x: x if os.path.isabs(x) else os.path.join(base, x)
    voice, clips = p(spec["voice"]), [p(c) for c in spec["clips"]]
    total = dur(voice) + TAIL
    outro = OUTRO if spec.get("outro", True) else 0
    n = len(clips)
    raw = sum(dur(c) for c in clips) - XFADE * (n - 1)
    slow = max(1.0, (total + 0.2) / raw)

    tmp = tempfile.mkdtemp()
    ass = os.path.join(tmp, "subs.ass")
    make_ass(spec["phrases"], json.load(open(p(spec["words"]), encoding="utf-8")), total, ass,
             spec.get("align", 2), spec.get("marginv", 620), spec.get("style", "phrases"), outro)
    lb = spec.get("letterbox", False)
    fit = (f"scale={W}:{W * 9 // 16}:force_original_aspect_ratio=increase,crop={W}:{W * 9 // 16},"
           f"pad={W}:{H}:0:(oh-ih)/2:color=0x141414" if lb else
           f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}")

    inputs, filt = [], []
    for k, c in enumerate(clips):
        inputs += ["-i", c]
        filt.append(f"[{k}:v]setpts={slow:.4f}*(PTS-STARTPTS),fps={FPS},"
                    f"{fit},setsar=1,format=yuv420p[c{k}]")
    last, offset = "c0", 0.0
    for k in range(1, n):
        offset += dur(clips[k - 1]) * slow - XFADE
        filt.append(f"[{last}][c{k}]xfade=transition=fade:duration={XFADE}:offset={offset:.3f}[x{k}]")
        last = f"x{k}"
    fd = p(spec.get("font_dir", "fonts"))
    filt.append(f"[{last}]trim=0:{total:.3f},eq=brightness={-0.15 if lb else -0.08}:saturation={0.8 if lb else 1},vignette=PI/5,"
                f"fade=t=out:st={total - 0.6:.3f}:d=0.6,tpad=stop_mode=add:stop_duration={outro}:color=black,"
                f"subtitles='{ass}':fontsdir='{fd}'[v]")
    vi = n
    mi = n + 1
    inputs += ["-i", voice, "-ss", str(spec.get("music_offset", 0)), "-i", p(spec["music"])]
    vol = spec.get("music_volume", 0.2)
    filt.append(f"[{mi}:a]atrim=0:{total + outro:.3f},asetpts=PTS-STARTPTS,volume={vol},"
                f"afade=t=in:d=1,afade=t=out:st={total + outro - 2:.3f}:d=2[m]")
    filt.append(f"[{vi}:a]aresample=48000,adelay=0|0[vo]")
    filt.append("[vo][m]amix=inputs=2:duration=longest:normalize=0,aresample=48000[a]")
    cmd = ["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(filt),
           "-map", "[v]", "-map", "[a]", "-t", f"{total + outro:.3f}",
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-movflags", "+faststart", p(spec["out"])]
    subprocess.run(cmd, check=True)
    print(f"{spec['out']}: {total + outro:.1f} c, замедление фона x{slow:.2f}")


if __name__ == "__main__":
    main(sys.argv[1])
