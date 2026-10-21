#!/usr/bin/env python3
"""Сборка нарезки из фильма «On time»: сцена с оригинальным звуком, вертикальный кадр,
заголовок-крючок сверху, русские субтитры под кадром, название фильма, заставка «On time».

Использование: build_clip.py spec.json
spec: {
  "out": "clip.mp4", "src": "scene.mp4", "start": 31.5, "end": 101.5,
  "hook": "Лучший комплимент в истории кино",
  "title": "«Лучше не бывает», 1997",
  "subs": [[32.0, 34.8, "Мой врач..."], ...],   # время в секундах исходника
  "zoom": 1.0,           # >1 — увеличить кадр и обрезать края
  "delogo": [x, y, w, h],  # необязательно: замазать водяной знак (координаты исходника)
  "crop": [w, h, x, y],    # необязательно: срезать чёрные полосы (см. ffmpeg cropdetect)
  "font_dir": "fonts/",
  "voice": ["vo/01.wav", ...],  # необязательно: закадровый перевод, по файлу на каждую строку subs;
  "voice_lag": 0.15,            # фраза стартует чуть позже английской и укладывается до следующей
  "orig_volume": 0.25           # громкость оригинала под голосом
}
"""
import json, subprocess, sys, os, tempfile

W, H, FPS = 1080, 1920, 30
TAIL = 1.6


def probe(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0",
                                   "-show_entries", "stream=width,height", "-of", "csv=p=0", path])
    w, h = out.decode().strip().split(",")[:2]
    return int(w), int(h)


def ts(t):
    t = max(t, 0)
    h, r = divmod(t, 3600)
    m, s = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def wrap(text, width):
    lines, cur = [], ""
    for w in text.split():
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    lines.append(cur)
    return r"\N".join(lines)


def make_ass(spec, length, box_top, box_bottom, path):
    start = spec["start"]
    ev = []
    ev.append(f"Dialogue: 0,{ts(0)},{ts(length)},Hook,,0,0,0,,{{\\fad(300,300)}}{wrap(spec['hook'], 24)}")
    ev.append(f"Dialogue: 0,{ts(0)},{ts(length)},Title,,0,0,0,,{{\\fad(300,300)}}{spec['title']}")
    for a, b, text in spec["subs"]:
        a, b = max(a - start, 0), min(b - start, length)
        if b > a:
            ev.append(f"Dialogue: 0,{ts(a)},{ts(b)},Sub,,0,0,0,,{wrap(text, 34)}")
    ev.append(f"Dialogue: 0,{ts(length)},{ts(length + TAIL)},Brand,,0,0,0,,{{\\fad(400,0)}}On time")
    hook_mv = max(box_top - 330, 120)
    sub_mv = box_bottom + 50
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,Lora,70,&H00FFFFFF,&H00FFFFFF,&H64000000,&H96000000,0,1,0,0,100,100,0,0,1,4,2,8,70,70,{hook_mv},1
Style: Sub,Lora,56,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,0,1,0,0,100,100,0,0,1,4,2,8,60,60,{sub_mv},1
Style: Title,Lora,40,&H00C8C8C8,&H00FFFFFF,&H64000000,&H96000000,0,1,0,0,100,100,0,0,1,2,1,2,60,60,170,1
Style: Brand,Lora,130,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,1,0,0,100,100,0,0,1,0,0,5,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(head + "\n".join(ev) + "\n")


def dur(path):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                          "-of", "csv=p=0", path]))


def build_voice(spec, p, tmp, length):
    """Каждую фразу обрезаем по тишине, при нужде ускоряем (до 1.3x), чтобы она уложилась
    в окно своей английской реплики, и ставим на место через adelay."""
    lag = spec.get("voice_lag", 0.15)
    subs, start = spec["subs"], spec["start"]
    parts = []
    for k, (f, (a, b, _)) in enumerate(zip(spec["voice"], subs)):
        nxt = subs[k + 1][0] if k + 1 < len(subs) else spec["end"]
        window = max(nxt - a - lag - 0.05, 0.5)
        trimmed = os.path.join(tmp, f"v{k:02d}.wav")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", p(f), "-af",
                        "silenceremove=start_periods=1:start_threshold=-45dB,areverse,"
                        "silenceremove=start_periods=1:start_threshold=-45dB,areverse",
                        "-ar", "48000", "-ac", "1", trimmed], check=True)
        d = dur(trimmed)
        tempo = min(max(d / window, 1.0), 1.3)
        if d / tempo > window + 0.05:
            print(f"фраза {k + 1} длиннее окна: {d / tempo:.2f} с > {window:.2f} с", file=sys.stderr)
        parts.append((trimmed, a - start + lag, tempo))
    ins, chains = [], []
    for i, (f, at, tempo) in enumerate(parts):
        ins += ["-i", f]
        ms = int(max(at, 0) * 1000)
        chains.append(f"[{i}:a]atempo={tempo:.3f},adelay={ms}|{ms}[p{i}]")
    mix = "".join(f"[p{i}]" for i in range(len(parts)))
    out = os.path.join(tmp, "voice.wav")
    fc = ";".join(chains) + f";{mix}amix=inputs={len(parts)}:normalize=0,loudnorm=I=-14:TP=-1.5[o]"
    subprocess.run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", fc, "-map", "[o]",
                    "-ar", "48000", "-t", str(length), out], check=True)
    return out


def main():
    spec = json.load(open(sys.argv[1], encoding="utf-8"))
    base = os.path.dirname(os.path.abspath(sys.argv[1]))
    p = lambda x: x if os.path.isabs(x) else os.path.join(base, x)
    src, out = p(spec["src"]), p(spec["out"])
    font_dir = p(spec.get("font_dir", "fonts/"))
    zoom = spec.get("zoom", 1.0)
    length = spec["end"] - spec["start"]

    sw, sh = spec["crop"][:2] if spec.get("crop") else probe(src)
    vw = int(round(W * zoom / 2) * 2)
    vh = int(round(vw * sh / sw / 2) * 2)
    box_top = (H - vh) // 2 - 60
    box_bottom = box_top + vh

    tmp = tempfile.mkdtemp()
    ass = os.path.join(tmp, "subs.ass")
    make_ass(spec, length, box_top, box_bottom, ass)

    voice = build_voice(spec, p, tmp, length) if spec.get("voice") else None

    pre = ""
    if spec.get("delogo"):
        x, y, w, h = spec["delogo"]
        pre = f"delogo=x={x}:y={y}:w={w}:h={h},"
    if spec.get("crop"):
        cw, ch, cx, cy = spec["crop"]
        pre += f"crop={cw}:{ch}:{cx}:{cy},"
    fc = (
        f"[0:v]setpts=PTS-STARTPTS,{pre}fps={FPS},split[a][b];"
        f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=30:3,eq=brightness=-0.32[bg];"
        f"[b]scale={vw}:{vh},crop={min(vw, W)}:{vh}[fg];"
        f"[bg][fg]overlay=(W-w)/2:{box_top},"
        f"tpad=stop_mode=add:stop_duration={TAIL}:color=black,"
        f"fade=t=out:st={length - 0.4}:d=0.4,"
        f"ass={ass}:fontsdir={font_dir},format=yuv420p[v];"
        f"[0:a]asetpts=PTS-STARTPTS,afade=t=in:d=0.3,afade=t=out:st={length - 0.6}:d=0.6,"
        f"loudnorm=I=-15:TP=-1.5"
    )
    if voice:
        fc += (f",volume={spec.get('orig_volume', 0.25)}[orig];"
               f"[1:a]apad[vo];[orig][vo]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95")
    fc += f",apad=pad_dur={TAIL}[au]"
    cmd = ["ffmpeg", "-v", "error", "-y", "-ss", str(spec["start"]), "-t", str(length), "-i", src,
           *(["-i", voice] if voice else []),
           "-filter_complex", fc, "-map", "[v]", "-map", "[au]",
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-r", str(FPS),
           "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart",
           "-t", str(length + TAIL), out]
    subprocess.run(cmd, check=True)
    print(out)


if __name__ == "__main__":
    main()
