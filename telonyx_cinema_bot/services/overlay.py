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
Style: TitleBlock,DejaVu Sans,48,&H00F6F2EA,&H000000FF,&HAA000000,&H00000000,-1,0,0,0,100,100,0,0,1,1,0.4,7,0,0,0,1
Style: Axis,DejaVu Sans,16,&H66EED322,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
"""


def ass_time_to_ms(t: str) -> float:
    parts = t.split(":")
    h, m, s_cs = int(parts[0]), int(parts[1]), parts[2]
    s, cs = s_cs.split(".")
    return (h * 3600 + m * 60 + int(s)) * 1000 + int(cs) * 10


def generate_title_ass(movie_title: str, movie_year: str, movie_genre: str, duration: float) -> str:
    title = str(movie_title).strip().upper() or "MOVIE"
    year = str(movie_year).strip() or "YEAR"
    genre = str(movie_genre).strip().split(",")[0].strip() if movie_genre else ""

    hold_end = max(3.0, duration * 0.8)
    slide_in_dur = 0.76
    exit_start = max(hold_end - 0.85, 4.0)
    axis_y = 1507
    title_y = 1504

    genre_line = f"\\N{{\\fs26\\fsp2.8\\c&H00EED322&\\bord0.75}}{genre}" if genre else ""

    t0 = ass_time(0)
    t_hold = ass_time(hold_end)

    exit_ms = int(exit_start * 1000)
    hold_end_ms = int(hold_end * 1000)

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
    ]

    # axis line
    lines.append(
        f"Dialogue: 1,{t0},{t_hold},Axis,,0,0,0,,"
        f"{{\\move(-120,{axis_y},74,{axis_y},0,{int(slide_in_dur*1000)})"
        f"\\t({exit_ms},{hold_end_ms},\\move(74,{axis_y},-120,{axis_y}))"
        f"\\fad(120,160)}}{{\\p1}}m 0 0 l 4 0 l 4 116 l 0 116{{\\p0}}"
    )

    # title block
    lines.append(
        f"Dialogue: 3,{t0},{t_hold},TitleBlock,,0,0,0,,"
        f"{{\\an7\\move(-920,{title_y},96,{title_y},0,{int(slide_in_dur*1000)})"
        f"\\t({exit_ms},{hold_end_ms},\\move(96,{title_y},-920,{title_y}))"
        f"\\blur0.08\\fad(120,{int((duration-hold_end+2)*1000)})}}"
        f"{{\\fs18\\fsp2.4\\c&H9CFFFFFF&\\bord0.35}}TELONYX.APP"
        f"\\N{{\\fs58\\fsp0.25\\c&H00F6F2EA&\\bord1.65}}{title}"
        f"\\N{{\\fs30\\fsp3.4\\c&H00EED322&\\bord0.85}}{year}{genre_line}"
    )

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
    movie_title: str,
    movie_year: str,
    movie_genre: str,
) -> None:
    duration = await probe_duration(ffprobe_bin, input_path)
    ass_path = work_dir / "title.ass"
    ass_path.write_text(generate_title_ass(movie_title, movie_year, movie_genre, duration), encoding="utf-8")

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
