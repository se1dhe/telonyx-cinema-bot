from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


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


def _style_block() -> str:
    return """[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Watermark,DejaVu Sans,28,&H44F6F2EA,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
"""


def generate_watermark_ass(duration: float) -> str:
    t0 = ass_time(0)
    tend = ass_time(duration)

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "ScaledBorderAndShadow: yes",
        "",
        _style_block(),
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        f"Dialogue: 0,{t0},{tend},Watermark,,0,0,0,,{{\\an3\\fad(300,300)}}@telonyx_cinema",
    ]

    return "\n".join(lines)


def video_filter(title_ass_path: Path) -> str:
    path = _ass_escape_path(title_ass_path)
    return f"eq=contrast=1.07:saturation=1.08:brightness=-0.018,unsharp=5:5:0.55:3:3:0.25,subtitles='{path}'"


async def probe_duration(ffprobe_bin: str, path: Path) -> float:
    import asyncio

    proc = await asyncio.create_subprocess_exec(
        ffprobe_bin,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {stderr.decode()[-1000:]}")
    try:
        return max(0.1, float(stdout.decode().strip()))
    except ValueError:
        return 0.1


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


async def render_with_overlay(
    ffmpeg_bin: str,
    ffprobe_bin: str,
    input_path: Path,
    output_path: Path,
    work_dir: Path,
) -> None:
    duration = await probe_duration(ffprobe_bin, input_path)
    ass_path = work_dir / "watermark.ass"
    ass_path.write_text(generate_watermark_ass(duration), encoding="utf-8")

    cmd = [
        ffmpeg_bin, "-y",
        "-i", str(input_path),
        "-vf", video_filter(ass_path),
        "-map", "0:v:0", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "256k", "-ac", "2",
        "-af", "loudnorm=I=-15:TP=-1.5:LRA=11",
        "-movflags", "+faststart", "-pix_fmt", "yuv420p",
        str(output_path),
    ]

    logger.info("Rendering: %s", " ".join(cmd))
    await _run_ffmpeg(cmd)
    logger.info("Render complete: %s", output_path)
