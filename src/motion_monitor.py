#!/usr/bin/env python3
"""
Mac Motion Monitor
- Uses the Mac's built-in camera.
- Detects motion by comparing consecutive frames.
- On motion, saves a photo, and (if enabled) records a video clip, locally.
- Video recording can be toggled on/off, and audio within that video can be
  toggled on/off independently, via config/config.json.
- Optionally sends both to Telegram.
- Uses macOS caffeinate so the Mac can keep monitoring while the display sleeps.
- Prints live calibration values (per-pixel diff and % of frame changed) on
  every loop so you can tune pixel_change_threshold and
  motion_percent_threshold in config/config.json.
All tunable settings live in config/config.json (see config/config.example.json
for a template and config/README covered in the project README).
Run with:
  ./run.sh
or directly (with the virtual environment active):
  python3 src/motion_monitor.py

Calibration mode:
  Run with --calibrate to just watch the live diff/percentage numbers in
  the terminal, with NOTHING saved and NOTHING sent to Telegram. Use this
  to dial in pixel_change_threshold and motion_percent_threshold before
  running for real.
    ./run.sh --calibrate
  or
    python3 src/motion_monitor.py --calibrate
"""

import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
import requests

from config import Config
from audio_devices import AudioDeviceResolutionError, resolve_audio_device_name
from detection.frame_difference import FrameDifferenceDetector
from telegram_control import ControlState, TelegramCommandListener

PROJECT_ROOT = Path(__file__).resolve().parent.parent

CALIBRATE_MODE = "--calibrate" in sys.argv

CONFIG = Config.load(PROJECT_ROOT)


# ----------------------------
# Telegram
# ----------------------------

def send_telegram_text(text: str):
    """Send a plain text status message to Telegram."""
    if not CONFIG.telegram_is_configured():
        return
    url = f"https://api.telegram.org/bot{CONFIG.telegram_token}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CONFIG.telegram_chat_id, "text": text}, timeout=15)
    except requests.RequestException as e:
        print(f"[telegram] Failed to send text: {e}")


def send_telegram_photo(image_path: Path):
    """Send one snapshot to Telegram as a photo message."""
    if not CONFIG.telegram_is_configured():
        return
    url = f"https://api.telegram.org/bot{CONFIG.telegram_token}/sendPhoto"
    caption = f"Motion detected - {datetime.now():%Y-%m-%d %H:%M:%S}"
    try:
        with open(image_path, "rb") as f:
            requests.post(
                url,
                data={"chat_id": CONFIG.telegram_chat_id, "caption": caption},
                files={"photo": f},
                timeout=30,
            )
    except requests.RequestException as e:
        print(f"[telegram] Failed to send photo: {e}")


def send_telegram_video(video_path: Path):
    """Send one motion clip to Telegram as a video message."""
    if not CONFIG.telegram_is_configured():
        return
    file_size_mb = video_path.stat().st_size / (1024 * 1024)
    if file_size_mb > 50:
        print(f"[telegram] Clip is {file_size_mb:.1f} MB, over Telegram's 50MB bot limit - skipping upload.")
        return
    url = f"https://api.telegram.org/bot{CONFIG.telegram_token}/sendVideo"
    try:
        with open(video_path, "rb") as f:
            requests.post(
                url,
                data={"chat_id": CONFIG.telegram_chat_id},
                files={"video": f},
                timeout=120,
            )
    except requests.RequestException as e:
        print(f"[telegram] Failed to send video: {e}")


# ----------------------------
# Camera / system helpers
# ----------------------------

def start_caffeinate():
    """
    Keep macOS from entering system sleep while this program runs.
    The display is still allowed to sleep; this is primarily to keep
    the monitoring process and camera available.
    """
    process = subprocess.Popen(["caffeinate", "-i"])
    return process


def save_snapshot(frame):
    """Save a single JPEG snapshot from the current frame."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = CONFIG.media_dir / f"motion_{timestamp}.jpg"

    success = cv2.imwrite(
        str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, CONFIG.jpeg_quality]
    )
    if not success:
        print(f"[photo] Failed to write snapshot to {path}")
        return None
    return path


def record_clip_with_audio(seconds: int):
    """
    Record a fixed-length video clip using ffmpeg. Includes audio only if
    audio.enabled is true in config/config.json.
    This talks to the camera (and microphone, if enabled) directly through
    ffmpeg's avfoundation input, independent of OpenCV. The caller is
    responsible for releasing the OpenCV camera handle first, since macOS
    won't let two processes hold the camera open at once.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = CONFIG.media_dir / f"motion_{timestamp}.mp4"

    if CONFIG.audio_enabled:
        device_string = f"{CONFIG.ffmpeg_video_device}:{CONFIG.ffmpeg_audio_device}"
    else:
        device_string = f"{CONFIG.ffmpeg_video_device}:none"

    command = [
        "ffmpeg",
        "-y",
        "-f", "avfoundation",
        "-framerate", str(CONFIG.ffmpeg_framerate),
        "-video_size", CONFIG.ffmpeg_resolution,
        "-i", device_string,
        "-t", str(seconds),
        "-pix_fmt", "yuv420p",
    ]
    if not CONFIG.audio_enabled:
        command += ["-an"]
    command.append(str(path))

    print(f"[video] Recording {seconds}s clip (audio={'on' if CONFIG.audio_enabled else 'off'})...")
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        print("[video] ffmpeg failed:")
        print(result.stderr[-2000:])
        return None
    return path


def wait_before_starting(delay_seconds: int, control_state: ControlState) -> bool:
    """
    Block for delay_seconds before the camera baseline is ever captured,
    printing a live countdown. This must happen BEFORE camera warmup -
    if you're still in frame when warmup runs, you become part of the
    baseline, and leaving afterward would itself register as motion.

    Checks control_state each second so a SHUTDOWN command sent during the
    countdown is honored immediately instead of waiting out the full delay.
    Returns False if shutdown was requested during the wait.
    """
    if delay_seconds <= 0:
        return True
    print(f"[startup] Starting in {delay_seconds}s - move out of camera view now...")
    remaining = delay_seconds
    while remaining > 0:
        if control_state.is_shutdown_requested:
            print("\n[shutdown] Shutdown requested during startup delay.")
            return False
        print(f"\r[startup] {remaining}s remaining...   ", end="", flush=True)
        time.sleep(1)
        remaining -= 1
    print("\r[startup] Starting now.                       ")
    return True


def resolve_configured_audio_device() -> None:
    """Resolve a configured AVFoundation audio-device name at startup.

    The resolved index is kept only in memory, so every process launch obtains
    a fresh index from AVFoundation instead of persisting a stale one.
    """
    if not CONFIG.video_enabled or not CONFIG.audio_enabled:
        return

    if CONFIG.audio_input_device is None:
        print(
            "[audio] WARNING: Using legacy numeric video.ffmpeg_audio_device "
            f'index "{CONFIG.ffmpeg_audio_device}". AVFoundation indexes can change '
            "when hardware is added or removed. Set audio.input_device to an exact "
            "device name to resolve it at startup."
        )
        return

    device = resolve_audio_device_name(CONFIG.audio_input_device)
    CONFIG.ffmpeg_audio_device = device.index
    print(
        f'[audio] Requested device: "{CONFIG.audio_input_device}"\n'
        f'[audio] Resolved device: "{device.name}" (AVFoundation index {device.index})'
    )


def main():
    try:
        resolve_configured_audio_device()
    except AudioDeviceResolutionError as error:
        print(f"[audio] Startup failed: {error}")
        sys.exit(1)

    control_state = ControlState()
    listener = TelegramCommandListener(CONFIG, control_state)
    listener.start()

    caffeinate_process = start_caffeinate()

    detector = FrameDifferenceDetector(
        pixel_change_threshold=CONFIG.pixel_change_threshold,
        motion_percent_threshold=CONFIG.motion_percent_threshold,
    )

    print("=== Motion Monitor starting ===")
    if CALIBRATE_MODE:
        print("  *** CALIBRATION MODE *** - no photos/video will be saved, nothing sent to Telegram")
        print(f"  video recording: {'ON' if CONFIG.video_enabled else 'OFF'}")
        print(f"  audio in clips:  {'ON' if CONFIG.audio_enabled else 'OFF'}" + ("" if CONFIG.video_enabled else " (irrelevant, video is off)"))
        print(f"  detector: {detector.name}")
        print(f"  pixel_change_threshold:   {CONFIG.pixel_change_threshold}")
        print(f"  motion_percent_threshold: {CONFIG.motion_percent_threshold}%")
        print("Watch the [calibrate] line below to tune those two values in config/config.json.")
        print()

    if not wait_before_starting(CONFIG.startup_delay_seconds, control_state):
        listener.stop()
        caffeinate_process.terminate()
        return

    camera = cv2.VideoCapture(CONFIG.camera_index, cv2.CAP_AVFOUNDATION)
    if not camera.isOpened():
        print("[camera] Could not open camera.")
        sys.exit(1)

    print(f"[startup] Warming up for {CONFIG.warmup_frames} frames to establish baseline...")
    for _ in range(CONFIG.warmup_frames):
        if control_state.is_shutdown_requested:
            break
        ok, frame = camera.read()
        if not ok:
            continue
        detector.warm(frame)
    print("[startup] Warmup complete. Monitoring for motion...\n")

    last_motion_time = 0
    was_paused = False

    try:
        while True:
            if control_state.is_shutdown_requested:
                print("\n[shutdown] Shutdown requested via Telegram.")
                break

            if control_state.is_paused:
                if not was_paused:
                    print("\n[paused] Monitoring paused via Telegram. Send 'resume' to continue.\n")
                    was_paused = True
                # Keep reading frames so the camera buffer doesn't go stale
                # and OpenCV doesn't time out, but skip all detection logic.
                camera.read()
                time.sleep(0.5)
                continue

            if was_paused:
                # Coming back from a pause - the scene may have changed
                # while we weren't looking, so re-warm the baseline instead
                # of comparing against a stale pre-pause frame (same reason
                # this happens after video recording).
                print(f"[resumed] Monitoring resumed via Telegram. Re-warming for {CONFIG.warmup_frames} frames...")
                detector.reset()
                for _ in range(CONFIG.warmup_frames):
                    ok, warm_frame = camera.read()
                    if ok:
                        detector.warm(warm_frame)
                last_motion_time = time.time()
                was_paused = False
                print("[running] Monitoring for motion...\n")

            ok, frame = camera.read()
            if not ok:
                print("[camera] Failed to read frame, retrying...")
                time.sleep(0.5)
                continue

            result = detector.process(frame)

            # Live calibration printout - overwrites the same terminal line.
            # (result.max_diff is None only on a frame establishing a fresh
            # baseline, which shouldn't normally happen post-warmup.)
            if CALIBRATE_MODE and result.max_diff is not None:
                print(
                    f"\r[calibrate] max_pixel_diff={result.max_diff:>3} "
                    f"(pixel_change_threshold={CONFIG.pixel_change_threshold})  |  "
                    f"frame_changed={result.changed_percentage:6.2f}% "
                    f"(motion_percent_threshold={CONFIG.motion_percent_threshold}%)   ",
                    end="",
                    flush=True,
                )

            now = time.time()

            if result.motion_detected and (now - last_motion_time) > CONFIG.cooldown_seconds:
                last_motion_time = now
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                if CALIBRATE_MODE:
                    print(f"\n[motion] Would trigger at {timestamp} (frame_changed={result.changed_percentage:.2f}%) - calibration mode, nothing saved/sent.")
                    print()
                    continue

                print(f"\n[motion] Motion detected at {timestamp} (frame_changed={result.changed_percentage:.2f}%)")

                photo = save_snapshot(frame)
                if photo:
                    print(f"[photo] Saved {photo}")
                    send_telegram_photo(photo)

                if CONFIG.video_enabled:
                    # ffmpeg needs exclusive access to the camera, so
                    # release OpenCV's handle first and reopen after.
                    camera.release()
                    clip = record_clip_with_audio(CONFIG.record_seconds)
                    if clip:
                        print(f"[video] Saved {clip}")
                        send_telegram_video(clip)

                    camera = cv2.VideoCapture(CONFIG.camera_index, cv2.CAP_AVFOUNDATION)

                    # Re-warm: auto-exposure/white balance need a moment to settle,
                    # and the old baseline is stale. Comparing against it
                    # causes a false-positive trigger that loops forever.
                    print(f"[video] Re-warming camera for {CONFIG.warmup_frames} frames after reopen...")
                    detector.reset()
                    for _ in range(CONFIG.warmup_frames):
                        ok, warm_frame = camera.read()
                        if not ok:
                            continue
                        detector.warm(warm_frame)

                    # Reset cooldown so we don't instantly re-trigger either.
                    last_motion_time = time.time()

                print()  # blank line before calibration printout resumes
                print("[running] Monitoring for motion...\n")

    except KeyboardInterrupt:
        print("\n[shutdown] Stopping Motion Monitor...")
    finally:
        camera.release()
        caffeinate_process.terminate()
        listener.stop()


if __name__ == "__main__":
    main()
