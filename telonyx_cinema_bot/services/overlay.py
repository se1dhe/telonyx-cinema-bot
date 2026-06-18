from __future__ import annotations

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

TEXT_APPEAR = 1.2
CHAR_TIME = 0.08

FONT_FILE = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
TEXT = "@telonyx_cinema"
FONT_SIZE = 28
TEXT_Y = "H-80"


def _build_typing_drawtext(text: str, start: float, char_time: float,
                           fontfile: str, fontsize: int,
                           x_expr: str, y_expr: str) -> str:
    filters = []
    for i in range(1, len(text) + 1):
        t1 = start + (i - 1) * char_time
        t2 = start + i * char_time
        part = text[:i]
        filters.append(
            f"drawtext=text='{part}':"
            f"fontfile={fontfile}:fontsize={fontsize}:"
            f"fontcolor=white@0.92:x={x_expr}:y={y_expr}:"
            f"enable='between(t,{t1},{t2})'"
        )
    t_full = start + len(text) * char_time
    filters.append(
        f"drawtext=text='{text}':"
        f"fontfile={fontfile}:fontsize={fontsize}:"
        f"fontcolor=white@0.92:x={x_expr}:y={y_expr}:"
        f"enable='gte(t,{t_full})'"
    )
    return ",".join(filters)


async def render_with_overlay(
    ffmpeg_bin: str,
    input_path: Path,
    output_path: Path,
    work_dir: Path,
) -> None:
    loop = asyncio.get_running_loop()
    del loop  # unused but kept for interface compatibility

    typing = _build_typing_drawtext(
        text=TEXT,
        start=TEXT_APPEAR,
        char_time=CHAR_TIME,
        fontfile=FONT_FILE,
        fontsize=FONT_SIZE,
        x_expr="(w-text_w)/2",
        y_expr=TEXT_Y,
    )

    cmd = [
        ffmpeg_bin, "-y",
        "-i", str(input_path),
        "-filter_complex", (
            f"[0:v]eq=contrast=1.07:saturation=1.08:brightness=-0.018,"
            f"unsharp=5:5:0.55:3:3:0.25,"
            f"format=rgba,"
            f"{typing}"
            f"[out]"
        ),
        "-map", "[out]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "256k", "-ac", "2",
        "-af", "loudnorm=I=-15:TP=-1.5:LRA=11",
        "-movflags", "+faststart", "-pix_fmt", "yuv420p",
        str(output_path),
    ]

    logger.info("Rendering: %s", " ".join(cmd))
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{stderr.decode()[-2000:]}")
    logger.info("Render complete: %s", output_path)
