"""Optional CMYK conversion via Ghostscript (spec Part 7, step 5).

Both colour paths are supported so losing either printer capability doesn't
strand production: RGB is the canonical, byte-deterministic artifact; when
RENDER_COLOR_MODE=cmyk, the RGB PDF is converted at this boundary using the
printer's ICC profile. Conversion output is NOT byte-deterministic
(Ghostscript stamps timestamps) — determinism guarantees apply to the RGB
artifact only.
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.render.compose import RenderError

GS_TIMEOUT_S = 300


def ghostscript_available() -> bool:
    return shutil.which("gs") is not None


def convert_pdf_to_cmyk(pdf_bytes: bytes, icc_profile_path: str | None = None) -> bytes:
    if not ghostscript_available():
        raise RenderError("ghostscript is not installed but RENDER_COLOR_MODE=cmyk")

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.pdf"
        dst = Path(tmp) / "out.pdf"
        src.write_bytes(pdf_bytes)

        cmd = [
            "gs", "-dSAFER", "-dBATCH", "-dNOPAUSE", "-dQUIET",
            "-sDEVICE=pdfwrite",
            "-dCompatibilityLevel=1.6",
            "-sColorConversionStrategy=CMYK",
            "-dProcessColorModel=/DeviceCMYK",
        ]
        if icc_profile_path:
            cmd.append(f"-sOutputICCProfile={icc_profile_path}")
        cmd += [f"-sOutputFile={dst}", str(src)]

        result = subprocess.run(cmd, capture_output=True, timeout=GS_TIMEOUT_S,
                                check=False)
        if result.returncode != 0 or not dst.exists():
            raise RenderError(
                f"ghostscript CMYK conversion failed: {result.stderr.decode()[:500]}"
            )
        return dst.read_bytes()
