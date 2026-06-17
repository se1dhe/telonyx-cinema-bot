from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

BADGE_SIZE = 34
BADGE_APPEAR = 0.8
TEXT_APPEAR = 1.8
FADE_IN = 500
FADE_OUT = 300
BADGE_Y_OFFSET = 190
TEXT_MARGIN_V = 130


def ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs >= 100:
        s += 1
        cs = 0
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_escape_path(path: Path) -> str:
    return str(path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def generate_watermark_ass(duration: float) -> str:
    t0 = ass_time(TEXT_APPEAR)
    tend = ass_time(duration)

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Watermark,DejaVu Sans,40,&H00FFFFFF,&H000000FF,&H00CC8800,&H40000000,1,0,0,0,100,100,2,0,1,2.5,1.5,2,0,0,{TEXT_MARGIN_V},1",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        f"Dialogue: 0,{t0},{tend},Watermark,,0,0,0,,{{\\an2\\fad({FADE_IN},{FADE_OUT})}}@telonyx_cinema",
    ]

    return "\n".join(lines)


def generate_badge_png(path: Path, size: int = BADGE_SIZE) -> None:
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    cx, cy = size // 2, size // 2
    r = size // 2 - 2

    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill="#2AABEE")

    p1 = (cx - r * 0.38, cy - r * 0.05)
    p2 = (cx - r * 0.08, cy + r * 0.32)
    p3 = (cx + r * 0.42, cy - r * 0.28)

    lw = max(3, size // 10)
    draw.line([p1, p2, p3], fill="white", width=lw, joint="curve")

    img.save(path, "PNG")


async def render_with_overlay(
    ffmpeg_bin: str,
    ffprobe_bin: str,
    input_path: Path,
    output_path: Path,
    work_dir: Path,
) -> None:
    import asyncio

    loop = asyncio.get_running_loop()

    duration = await loop.run_in_executor(None, _probe_duration, ffprobe_bin, input_path)

    ass_path = work_dir / "watermark.ass"
    ass_path.write_text(generate_watermark_ass(duration), encoding="utf-8")

    badge_path = work_dir / "badge.png"
    await loop.run_in_executor(None, generate_badge_png, badge_path)

    ass_esc = _ass_escape_path(ass_path)
    badge_x = f"W/2-{BADGE_SIZE//2}"
    badge_y = f"H-{BADGE_Y_OFFSET}"

    cmd = [
        ffmpeg_bin, "-y",
        "-i", str(input_path),
        "-loop", "1",
        "-i", str(badge_path),
        "-filter_complex", (
            f"[0:v]eq=contrast=1.07:saturation=1.08:brightness=-0.018,"
            f"unsharp=5:5:0.55:3:3:0.25,"
            f"subtitles='{ass_esc}'[v];"
            f"[1:v]format=rgba,setpts=PTS+{BADGE_APPEAR}/TB[badge];"
            f"[v][badge]overlay=x={badge_x}:y={badge_y}:shortest=1[out]"
        ),
        "-map", "[out]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "256k", "-ac", "2",
        "-af", "loudnorm=I=-15:TP=-1.5:LRA=11",
        "-movflags", "+faststart", "-pix_fmt", "yuv420p",
        str(output_path),
    ]

    logger.info("Rendering: %s", " ".join(cmd))
    await _run_ffmpeg(cmd)
    logger.info("Render complete: %s", output_path)


async def _run_ffmpeg(cmd: list[str]) -> None:
    import asyncio

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg failed:\n{stderr.decode()[-2000:]}")


def _probe_duration(ffprobe_bin: str, path: Path) -> float:
    import subprocess

    result = subprocess.run(
        [ffprobe_bin, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr[-1000:]}")
    try:
        return max(0.1, float(result.stdout.strip()))
    except ValueError:
        return 0.1
