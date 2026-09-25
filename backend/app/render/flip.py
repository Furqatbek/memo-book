"""The flip video's frames and their encoding — CR-003-5.

Every customer becomes a content producer without being asked for anything.
That only works if the file they get is one they can actually post, so the
format is not negotiable and is worth stating plainly:

    1080 x 1920, exactly     Instagram and Telegram re-crop anything else,
                             and a re-cropped book loses its edges.
    yuv420p                  the only pixel format every phone decodes.
                             yuv444p plays on a laptop and shows a black
                             rectangle on somebody's phone.
    bt709, tagged            untagged colour is interpreted differently by
                             different players, which on a PHOTO product
                             means the customer's own pictures come out a
                             different colour than their book.
    no audio                 people add their own.

`imageio_ffmpeg` is used for its bundled BINARY only. Its `write_frames`
helper silently rounds odd dimensions up to a multiple of 16 — 1080 becomes
1088 — and a video that is not exactly 1080 wide is the thing this file
exists to avoid. So the pipe is built here.

MEMORY: frames are generated and handed to ffmpeg one at a time through a
pipe, and nothing holds more than two of them. A 96-page book at this size
would otherwise be a gigabyte of RGB resident before a byte is encoded.
"""
import io
import subprocess

import structlog
from PIL import Image, ImageDraw, ImageFont

log = structlog.get_logger()

WIDTH = 1080
HEIGHT = 1920
FPS = 30

# Six to ten seconds, whatever the book's length — which means the hold has
# to be worked out from the page count rather than fixed. A fixed hold gives
# a 16-page book four seconds and a 96-page book fifteen, and fifteen is a
# video people scroll past.
TARGET_FRAMES = 8 * FPS   # aim for eight seconds
FADE_FRAMES = 6           # 0.2s crossing to the next page
MIN_HOLD_FRAMES = 6       # 0.2s — below this the pages strobe
MAX_HOLD_FRAMES = 45      # 1.5s — above this a short book drags
MAX_PAGES = 20            # the CR's cap; a 96-page book shows its first 20

# Paper white all round, so a vertical frame of a portrait page looks like a
# photograph of a book rather than a page floating in a void.
BACKDROP = (245, 243, 238)
MARGIN_PX = 64

WORDMARK = "rspixel.uz"
WORDMARK_ALPHA = 150      # subtle. A watermark across the image is a reason
                          # not to post it, which defeats the entire feature.


class FlipVideoError(RuntimeError):
    """Anything that stops a video being made. Never reaches an order."""


def frame_budget(page_count: int) -> int:
    """How many pages this video will show."""
    return min(page_count, MAX_PAGES)


def _font(size: int):
    """The same shipped typefaces the book is printed with. Falls back
    rather than raising: a missing font must not be the reason a customer
    gets no video."""
    try:
        from app.render.interior import family_ttf

        return ImageFont.truetype(str(family_ttf(None)), size)
    except Exception:  # noqa: BLE001 — any font failure, same answer
        try:
            return ImageFont.load_default(size)
        except TypeError:          # Pillow < 10.1 takes no size
            return ImageFont.load_default()


def _wordmark(canvas: Image.Image) -> None:
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    font = _font(28)
    box = draw.textbbox((0, 0), WORDMARK, font=font)
    x = canvas.width - (box[2] - box[0]) - 34
    y = canvas.height - (box[3] - box[1]) - 42
    draw.text((x, y), WORDMARK, font=font,
              fill=(60, 55, 50, WORDMARK_ALPHA))
    merged = Image.alpha_composite(canvas.convert("RGBA"), layer)
    canvas.paste(merged.convert("RGB"), (0, 0))


def compose_frame(page_jpeg: bytes) -> Image.Image:
    """One rendered page, centred on a vertical canvas, with the wordmark.

    Returns an RGB image of exactly WIDTH x HEIGHT.
    """
    canvas = Image.new("RGB", (WIDTH, HEIGHT), BACKDROP)
    page = Image.open(io.BytesIO(page_jpeg))
    page.load()
    if page.mode != "RGB":
        page = page.convert("RGB")
    budget = (WIDTH - 2 * MARGIN_PX, HEIGHT - 2 * MARGIN_PX)
    page.thumbnail(budget, Image.LANCZOS)
    canvas.paste(page, ((WIDTH - page.width) // 2, (HEIGHT - page.height) // 2))
    del page
    _wordmark(canvas)
    return canvas


def _blend(a: Image.Image, b: Image.Image, t: float) -> Image.Image:
    return Image.blend(a, b, t)


def hold_frames(image_count: int) -> int:
    """How long each page is held, so the whole video lands near eight
    seconds regardless of how long the book is.

    The last image is held twice, hence `n + 1` below rather than `n`.
    """
    n = max(1, image_count)
    ideal = (TARGET_FRAMES - (n - 1) * FADE_FRAMES) / (n + 1)
    return int(min(MAX_HOLD_FRAMES, max(MIN_HOLD_FRAMES, round(ideal))))


def total_frames(image_count: int) -> int:
    n = max(1, image_count)
    hold = hold_frames(n)
    return (n - 1) * (hold + FADE_FRAMES) + hold * 2


def frames(pages: list[bytes]):
    """Yield every frame of the video, in order, one at a time.

    A generator rather than a list on purpose: the caller pipes each frame
    straight into ffmpeg and drops it. Two pages' composites are alive at
    the crossfade and nothing more.
    """
    if not pages:
        raise FlipVideoError("a video needs at least one page")
    hold = hold_frames(len(pages))
    current = compose_frame(pages[0])
    for nxt in pages[1:]:
        for _ in range(hold):
            yield current
        following = compose_frame(nxt)
        for i in range(1, FADE_FRAMES + 1):
            yield _blend(current, following, i / (FADE_FRAMES + 1))
        current = following
    # The last page is held a beat longer — this is the frame the video
    # freezes on in a chat's preview thumbnail.
    for _ in range(hold * 2):
        yield current


def duration_s(image_count: int) -> float:
    return round(total_frames(image_count) / FPS, 2)


def _ffmpeg_exe() -> str:
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
    except ImportError as exc:  # noqa: F841
        raise FlipVideoError(
            "imageio-ffmpeg is not installed; no video can be made") from exc
    return get_ffmpeg_exe()


def encode(page_jpegs: list[bytes], crf: int = 24) -> bytes:
    """Stitch rendered pages into an MP4 and return its bytes.

    Everything below the `-pix_fmt` line is about the file playing the same
    way on a phone as it does here; none of it is a default worth trusting.
    """
    exe = _ffmpeg_exe()
    cmd = [
        exe, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS), "-i", "-",
        "-an",                                   # no audio track at all
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-color_primaries", "bt709", "-color_trc", "bt709",
        "-colorspace", "bt709",
        # The index at the FRONT, so a phone can start playing before the
        # whole file has arrived. Without it a 6MB video looks broken for
        # its first few seconds on a slow connection.
        "-movflags", "+faststart",
        "-f", "mp4", "pipe:1",
    ]
    # ffmpeg cannot seek a pipe, so the muxer needs a temporary file for the
    # faststart pass; giving it one explicitly beats letting it fail.
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".mp4") as out:
        cmd[-1] = out.name
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE)
        try:
            for frame in frames(page_jpegs):
                proc.stdin.write(frame.tobytes())
                del frame
            proc.stdin.close()
        except BrokenPipeError as exc:
            proc.kill()
            stderr = proc.stderr.read().decode("utf-8", "replace")[:500]
            raise FlipVideoError(f"ffmpeg stopped reading: {stderr}") from exc
        code = proc.wait()
        stderr = proc.stderr.read().decode("utf-8", "replace")[:500]
        if code != 0:
            raise FlipVideoError(f"ffmpeg exited {code}: {stderr}")
        out.seek(0)
        data = out.read()
    if not data:
        raise FlipVideoError("ffmpeg produced an empty file")
    return data
