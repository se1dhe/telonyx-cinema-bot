from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

BADGE_SIZE = 34
BADGE_APPEAR = 0.8
TEXT_APPEAR = 1.6

FONT_FILE = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
TEXT = "@telonyx_cinema"
FONT_SIZE = 40
TEXT_Y = "H-96"
BADGE_X = "W/2-200"
BADGE_Y = "H-96"


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
    input_path: Path,
    output_path: Path,
    work_dir: Path,
) -> None:
    import asyncio

    loop = asyncio.get_running_loop()

    badge_path = work_dir / "badge.png"
    await loop.run_in_executor(None, generate_badge_png, badge_path)

    alpha_expr = f"if(gte(t,{TEXT_APPEAR}),min(1,(t-{TEXT_APPEAR})/0.3),0)"

    cmd = [
        ffmpeg_bin, "-y",
        "-i", str(input_path),
        "-loop", "1",
        "-i", str(badge_path),
        "-filter_complex", (
            f"[0:v]eq=contrast=1.07:saturation=1.08:brightness=-0.018,"
            f"unsharp=5:5:0.55:3:3:0.25,"
            f"format=rgba[v];"
            f"[1:v]format=rgba,setpts=PTS+{BADGE_APPEAR}/TB[badge];"
            f"[v][badge]overlay=x={BADGE_X}:y={BADGE_Y}:shortest=1,"
            f"drawtext="
            f"text='{TEXT}':"
            f"x=(w-text_w)/2:"
            f"y={TEXT_Y}:"
            f"fontsize={FONT_SIZE}:"
            f"fontcolor=white:"
            f"borderw=2.5:"
            f"bordercolor=#0088CC:"
            f"shadowx=2:shadowy=2:"
            f"shadowcolor=black@0.4:"
            f"fontfile={FONT_FILE}:"
            f"enable='gte(t,{TEXT_APPEAR})':"
            f"alpha='{alpha_expr}'"
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
    
