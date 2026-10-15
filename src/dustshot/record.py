"""Screen recording backends.

Screen recording needs a capture daemon talking to the compositor. wf-recorder
and gpu-screen-recorder are both supported when present; the module never fails
hard on a missing tool, it reports which backend is usable so the UI can explain
what to install.
"""

from __future__ import annotations

import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .capture.base import Geometry

BACKENDS = ("wf-recorder", "gpu-screen-recorder")


class RecordError(RuntimeError):
    """Raised when recording cannot start or stop cleanly."""


@dataclass
class RecordingResult:
    path: Path
    duration: float
    backend: str
    started: float


def backend_path(name: str) -> str | None:
    return shutil.which(name)


def available_backends() -> list[str]:
    return [name for name in BACKENDS if backend_path(name)]


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def build_command(
    backend: str,
    output: Path,
    region: Geometry | None = None,
    fps: int = 30,
    audio: bool = False,
    include_cursor: bool = True,
) -> list[str]:
    """Build the record command line for a backend."""

    if backend == "wf-recorder":
        command = [backend_path("wf-recorder") or "wf-recorder"]
        if region is not None and not region.is_empty():
            command += ["-g", region.as_grim_geometry()]
        command += ["-f", str(output)]
        if fps:
            command += ["-r", str(int(fps))]
        if audio:
            command += ["--audio"]
    elif backend == "gpu-screen-recorder":
        command = [backend_path("gpu-screen-recorder") or "gpu-screen-recorder", "-w", "screen"]
        if region is not None and not region.is_empty():
            command[2:2] = ["-region", region.as_grim_geometry()]
        command += ["-f", str(int(fps)), "-o", str(output), "-c", "mp4"]
    else:
        raise RecordError(f"unsupported recording backend: {backend}")
    return command


class Recorder:
    """A running recording process."""

    def __init__(self, process: subprocess.Popen, output: Path, backend: str) -> None:
        self.process = process
        self.output = output
        self.backend = backend
        self.started = time.time()

    @classmethod
    def start(
        cls,
        output: str | Path,
        region: Geometry | None = None,
        fps: int = 30,
        backend: str | None = None,
        audio: bool = False,
    ) -> Recorder:
        chosen = backend or (available_backends() or [None])[0]
        if not chosen:
            raise RecordError("no recording backend found; install wf-recorder or gpu-screen-recorder")
        target = Path(output).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        command = build_command(chosen, target, region=region, fps=fps, audio=audio)
        try:
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        except OSError as exc:
            raise RecordError(f"could not start {chosen}: {exc}") from exc
        return cls(process=process, output=target, backend=chosen)

    @property
    def running(self) -> bool:
        return self.process.poll() is None

    def stop(self, timeout: float = 10.0) -> RecordingResult:
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGINT)
            try:
                self.process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=timeout)
                raise RecordError("recorder did not stop gracefully and was killed") from None
        duration = time.time() - self.started
        if not self.output.exists():
            raise RecordError("recorder stopped but produced no file")
        return RecordingResult(
            path=self.output,
            duration=duration,
            backend=self.backend,
            started=self.started,
        )

    def to_gif(self, fps: int = 15, width: int = 800, output: str | Path | None = None) -> Path:
        """Convert the recording to a GIF with ffmpeg."""

        ffmpeg = ffmpeg_path()
        if not ffmpeg:
            raise RecordError("ffmpeg is not installed")
        target = Path(output) if output else self.output.with_suffix(".gif")
        filters = (
            f"fps={int(fps)},scale={int(width)}:-1:flags=lanczos,"
            "split[a][b];[a]palettegen[p];[b][p]paletteuse"
        )
        command = [ffmpeg, "-y", "-i", str(self.output), "-vf", filters, str(target)]
        result = subprocess.run(command, capture_output=True, timeout=600, check=False)
        if result.returncode != 0:
            raise RecordError(result.stderr.decode("utf-8", "replace").strip() or "ffmpeg failed")
        return target
