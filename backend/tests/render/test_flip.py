"""CR-003-5 — the flip video's frames and encoding.

The format is not a matter of taste. A video that is 1088 pixels wide gets
re-cropped by Instagram; one encoded as yuv444p plays on a laptop and shows
a black rectangle on somebody's phone; one with no colour tags comes out a
different colour in every player, which on a PHOTO product means the
customer's own pictures are wrong. Each of those is one line in `encode`,
and each of them is asserted here against the actual file.
"""
import io
import subprocess

import pytest
from PIL import Image

from app.render import flip
from tests.render.helpers import fixture_photo_bytes

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def page(seed: int) -> bytes:
    return fixture_photo_bytes(874, 1225, seed)


def probe(data: bytes) -> str:
    """What ffmpeg says about the file we produced."""
    import tempfile

    from imageio_ffmpeg import get_ffmpeg_exe

    with tempfile.NamedTemporaryFile(suffix=".mp4") as f:
        f.write(data)
        f.flush()
        out = subprocess.run([get_ffmpeg_exe(), "-hide_banner", "-i", f.name],
                             capture_output=True, text=True)
    return out.stderr


class TestTheFrame:
    def test_it_is_exactly_the_vertical_format(self):
        """1080x1920, to the pixel. `imageio_ffmpeg`'s own writer rounds
        1080 up to 1088 to suit the encoder, which is the single reason
        this module drives ffmpeg itself."""
        frame = flip.compose_frame(page(1))
        assert frame.size == (flip.WIDTH, flip.HEIGHT)
        assert frame.mode == "RGB"

    def test_a_portrait_page_is_not_stretched(self):
        """The book is a rectangle with a known shape. A page squashed to
        fill a phone screen is a page that does not look like the thing
        being sold."""
        frame = flip.compose_frame(page(2))
        # The backdrop shows above and below a centred portrait page.
        top = frame.getpixel((flip.WIDTH // 2, 8))
        assert top == flip.BACKDROP

    def test_the_wordmark_is_present_and_subtle(self):
        """A watermark across the image is a reason not to post it, which
        would defeat the whole feature."""
        plain = Image.new("RGB", (flip.WIDTH, flip.HEIGHT), flip.BACKDROP)
        marked = plain.copy()
        flip._wordmark(marked)
        assert marked.tobytes() != plain.tobytes(), "no wordmark drawn"

        changed = sum(1 for a, b in zip(plain.getdata(), marked.getdata())
                      if a != b)
        share = changed / (flip.WIDTH * flip.HEIGHT)
        assert 0 < share < 0.01, f"the wordmark covers {share:.1%} of the frame"


class TestThePacing:
    @pytest.mark.parametrize("images", [17, 19, 21])
    def test_a_real_book_lands_between_six_and_ten_seconds(self, images):
        """The CR's window. A fixed hold gives a 16-page book four seconds
        and a 96-page book fifteen, and fifteen is a video people scroll
        past."""
        assert 6.0 <= flip.duration_s(images) <= 10.0

    def test_a_long_book_shows_its_first_twenty_pages(self):
        assert flip.frame_budget(96) == flip.MAX_PAGES
        assert flip.frame_budget(8) == 8

    def test_the_last_page_is_held_longest(self):
        """It is the frame a chat freezes on as the preview thumbnail."""
        pages = [page(i) for i in range(3)]
        rendered = list(flip.frames(pages))
        hold = flip.hold_frames(3)
        tail = rendered[-hold * 2:]
        assert all(f.tobytes() == tail[0].tobytes() for f in tail)

    def test_frames_are_generated_not_accumulated(self):
        """A generator, because a 21-frame book at this size is 125MB of
        RGB if the frames are kept."""
        import types

        assert isinstance(flip.frames([page(1), page(2)]), types.GeneratorType)


class TestEncoding:
    def test_it_produces_a_playable_mp4_of_the_right_shape(self):
        data = flip.encode([page(i) for i in range(4)])
        assert data[4:8] == b"ftyp", "not an MP4 container"
        info = probe(data)
        assert "1080x1920" in info, info[:400]

    def test_the_pixel_format_is_the_one_every_phone_decodes(self):
        info = probe(flip.encode([page(i) for i in range(3)]))
        assert "yuv420p" in info, info[:400]

    def test_the_colour_is_tagged(self):
        """Untagged colour is interpreted differently by different players.
        On a photo product that means the customer's own pictures come out
        a different colour than their book."""
        info = probe(flip.encode([page(i) for i in range(3)]))
        assert "bt709" in info, info[:400]

    def test_there_is_no_audio_track(self):
        """People add their own on Instagram and Telegram."""
        info = probe(flip.encode([page(i) for i in range(3)]))
        assert "Audio:" not in info, info[:400]

    def test_it_is_small_enough_to_send(self):
        """The CR's ceiling is 8MB. A video somebody cannot send over
        mobile data is one they do not send."""
        data = flip.encode([page(i) for i in range(21)])
        assert len(data) < 8 * 1024 * 1024, f"{len(data)} bytes"

    def test_an_empty_book_is_refused_rather_than_encoded(self):
        with pytest.raises(flip.FlipVideoError):
            flip.encode([])

    def test_a_file_that_is_not_an_image_raises_rather_than_hangs(self):
        with pytest.raises(Exception):
            flip.encode([b"not a jpeg"])

    def test_the_index_is_at_the_front(self):
        """Without `+faststart` a phone cannot begin playing until the whole
        file has arrived, and a 6MB video looks broken for several seconds
        on a slow connection."""
        data = flip.encode([page(i) for i in range(3)])
        head = data[:4096]
        assert b"moov" in head, "moov atom is not near the start"
        assert head.index(b"moov") < data.index(b"mdat")


class TestMemory:
    def test_one_frame_is_composed_at_a_time(self):
        """The discipline the print pipeline follows, for the same reason:
        twenty-one decoded frames at this size would be 125MB resident."""
        composed = []
        real = flip.compose_frame

        def counting(jpeg):
            composed.append(1)
            return real(jpeg)

        flip.compose_frame = counting
        try:
            pages = [page(i) for i in range(5)]
            consumed = 0
            for _ in flip.frames(pages):
                consumed += 1
            # One composite per page, not one per FRAME.
            assert len(composed) == 5
            assert consumed > 5
        finally:
            flip.compose_frame = real


def test_a_page_jpeg_that_is_the_wrong_size_is_still_fitted():
    """Share renders are 144dpi today; if that number ever moves, the
    video must still be exactly 1080x1920 rather than quietly become
    whatever the page happens to be."""
    odd = io.BytesIO()
    Image.new("RGB", (400, 400), (10, 20, 30)).save(odd, format="JPEG")
    frame = flip.compose_frame(odd.getvalue())
    assert frame.size == (flip.WIDTH, flip.HEIGHT)
