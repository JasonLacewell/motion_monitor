"""Discovery and name-based selection of AVFoundation audio devices.

FFmpeg assigns AVFoundation device indexes at runtime.  This module resolves
the stable, user-facing configuration choice (a device name) to the current
index immediately before Motion Monitor starts using it.
"""

from dataclasses import dataclass
import re
import subprocess


class AudioDeviceResolutionError(RuntimeError):
    """The configured AVFoundation audio device could not be resolved."""


@dataclass(frozen=True)
class AVFoundationAudioDevice:
    """One audio input reported by ``ffmpeg -list_devices``."""

    index: str
    name: str


_DEVICE_LINE = re.compile(r"\[(\d+)\]\s+(.+)$")


def discover_audio_devices() -> list[AVFoundationAudioDevice]:
    """Return the audio inputs currently reported by FFmpeg/AVFoundation.

    FFmpeg writes this device listing to stderr on common builds, so combine
    both streams before parsing.  The listing command may return a nonzero
    status after printing devices; a usable parsed list is therefore the
    success condition.
    """
    command = ["ffmpeg", "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""]
    try:
        result = subprocess.run(command, capture_output=True, text=True)
    except FileNotFoundError as error:
        raise AudioDeviceResolutionError(
            "ffmpeg was not found. Install ffmpeg before using audio recording."
        ) from error

    devices: list[AVFoundationAudioDevice] = []
    in_audio_section = False
    for line in f"{result.stdout}\n{result.stderr}".splitlines():
        if "AVFoundation audio devices:" in line:
            in_audio_section = True
            continue
        if in_audio_section and "AVFoundation" in line and "devices:" in line:
            break
        if not in_audio_section:
            continue

        match = _DEVICE_LINE.search(line)
        if match:
            devices.append(
                AVFoundationAudioDevice(index=match.group(1), name=match.group(2).strip())
            )

    if devices:
        return devices

    detail = (result.stderr or result.stdout).strip()
    if detail:
        detail = detail[-1000:]
        raise AudioDeviceResolutionError(
            "FFmpeg/AVFoundation did not report any audio input devices.\n"
            f"ffmpeg output:\n{detail}"
        )
    raise AudioDeviceResolutionError(
        "FFmpeg/AVFoundation did not report any audio input devices."
    )


def resolve_audio_device_name(requested_name: str) -> AVFoundationAudioDevice:
    """Resolve one exact configured device name to its current index.

    Matching is deliberately exact and case-sensitive.  Choosing a different
    microphone when names are ambiguous would be more surprising than a clear
    startup failure.
    """
    devices = discover_audio_devices()
    matches = [device for device in devices if device.name == requested_name]

    if len(matches) == 1:
        return matches[0]

    available = "\n".join(f'  [{device.index}] {device.name}' for device in devices)
    if not matches:
        raise AudioDeviceResolutionError(
            f'Configured audio input device "{requested_name}" was not found.\n'
            f"Available AVFoundation audio devices:\n{available}"
        )

    matching = "\n".join(f'  [{device.index}] {device.name}' for device in matches)
    raise AudioDeviceResolutionError(
        f'Configured audio input device "{requested_name}" is ambiguous.\n'
        f"Matching AVFoundation audio devices:\n{matching}\n"
        "Choose a uniquely named input device."
    )
