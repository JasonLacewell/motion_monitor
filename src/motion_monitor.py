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

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "config.json"
CONFIG_EXAMPLE_PATH = PROJECT_ROOT / "config" / "config.example.json"


def load_config():
    """Load config/config.json, with a clear error if it's missing."""
    if not CONFIG_PATH.exists():
        print("No config/config.json found.")
        print(f"Copy {CONFIG_EXAMPLE_PATH.name} to config.json and edit it:")
        print(f"  cp {CONFIG_EXAMPLE_PATH} {CONFIG_PATH}")
        sys.exit(1)
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


CALIBRATE_MODE = "--calibrate" in sys.argv

CONFIG = load_config()

CAMERA_INDEX = CONFIG["camera_index"]
MEDIA_DIR = Path(CONFIG["media_dir"]).expanduser()
MEDIA_DIR.mkdir(parents=True, exist_ok=True)

JPEG_QUALITY = CONFIG["photo"]["jpeg_quality"]

VIDEO_ENABLED = CONFIG["video"].get("enabled", True)
RECORD_SECONDS = CONFIG["video"]["record_seconds"]
FFMPEG_VIDEO_DEVICE = CONFIG["video"]["ffmpeg_video_device"]
FFMPEG_AUDIO_DEVICE = CONFIG["video"]["ffmpeg_audio_device"]
FFMPEG_FRAMERATE = CONFIG["video"]["ffmpeg_framerate"]
FFMPEG_RESOLUTION = CONFIG["video"]["ffmpeg_resolution"]

AUDIO_ENABLED = CONFIG.get("audio", {}).get("enabled", True)

SEND_TELEGRAM = CONFIG["telegram"]["enabled"]
TELEGRAM_TOKEN = CONFIG["telegram"]["bot_token"]
TELEGRAM_CHAT_ID = CONFIG["telegram"]["chat_id"]

PIXEL_CHANGE_THRESHOLD = CONFIG["detection"]["pixel_change_threshold"]
MOTION_PERCENT_THRESHOLD = CONFIG["detection"]["motion_percent_threshold"]

if VIDEO_ENABLED:
    COOLDOWN_SECONDS = RECORD_SECONDS + 5
else:
    COOLDOWN_SECONDS = CONFIG["detection"]["cooldown_seconds"]

WARMUP_FRAMES = CONFIG["detection"]["warmup_frames"]

# ----------------------------
# Telegram
# ----------------------------

def telegram_is_configured():
    placeholder_values = {"", "PASTE_YOUR_BOT_TOKEN_HERE", "PASTE_YOUR_CHAT_ID_HERE"}
    if not SEND_TELEGRAM:
        return False
    if TELEGRAM_TOKEN in placeholder_values or TELEGRAM_CHAT_ID in placeholder_values:
        print("[telegram] Credentials missing/placeholder - skipping upload, saving locally only.")
        return False
    return True


def send_telegram_text(text: str):
    """Send a plain text status message to Telegram."""
    if not telegram_is_configured():
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=15)
    except requests.RequestException as e:
        print(f"[telegram] Failed to send text: {e}")


def send_telegram_photo(image_path: Path):
    """Send one snapshot to Telegram as a photo message."""
    if not telegram_is_configured():
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    caption = f"Motion detected - {datetime.now():%Y-%m-%d %H:%M:%S}"
    try:
        with open(image_path, "rb") as f:
            requests.post(
                url,
                data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption},
                files={"photo": f},
                timeout=30,
            )
    except requests.RequestException as e:
        print(f"[telegram] Failed to send photo: {e}")


def send_telegram_video(video_path: Path):
    """Send one motion clip to Telegram as a video message."""
    if not telegram_is_configured():
        return
    file_size_mb = video_path.stat().st_size / (1024 * 1024)
    if file_size_mb > 50:
        print(f"[telegram] Clip is {file_size_mb:.1f} MB, over Telegram's 50MB bot limit - skipping upload.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
    try:
        with open(video_path, "rb") as f:
            requests.post(
                url,
                data={"chat_id": TELEGRAM_CHAT_ID},
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


def preprocess(frame):
    """Convert a camera frame into a smaller grayscale image."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, (640, 480))
    gray = cv2.GaussianBlur(gray, (21, 21), 0)
    return gray


def detect_motion(previous, current):
    """
    Compare two frames.
    Returns:
        changed_percentage, threshold_image, diff_stats
    diff_stats is a dict with 'max_diff' and 'mean_diff', the raw
    per-pixel intensity differences before thresholding - useful for
    calibrating pixel_change_threshold.
    """
    difference = cv2.absdiff(previous, current)

    max_diff = int(difference.max())
    mean_diff = float(difference.mean())

    _, threshold = cv2.threshold(difference, PIXEL_CHANGE_THRESHOLD, 255, cv2.THRESH_BINARY)
    threshold = cv2.dilate(threshold, None, iterations=2)

    changed_pixels = cv2.countNonZero(threshold)
    total_pixels = threshold.shape[0] * threshold.shape[1]

    changed_percentage = (changed_pixels / total_pixels) * 100.0

    diff_stats = {"max_diff": max_diff, "mean_diff": mean_diff}
    return changed_percentage, threshold, diff_stats


def save_snapshot(frame):
    """Save a single JPEG snapshot from the current frame."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = MEDIA_DIR / f"motion_{timestamp}.jpg"

    success = cv2.imwrite(
        str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
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
    path = MEDIA_DIR / f"motion_{timestamp}.mp4"

    if AUDIO_ENABLED:
        device_string = f"{FFMPEG_VIDEO_DEVICE}:{FFMPEG_AUDIO_DEVICE}"
    else:
        device_string = f"{FFMPEG_VIDEO_DEVICE}:none"

    command = [
        "ffmpeg",
        "-y",
        "-f", "avfoundation",
        "-framerate", str(FFMPEG_FRAMERATE),
        "-video_size", FFMPEG_RESOLUTION,
        "-i", device_string,
        "-t", str(seconds),
        "-pix_fmt", "yuv420p",
    ]
    if not AUDIO_ENABLED:
        command += ["-an"]
    command.append(str(path))

    print(f"[video] Recording {seconds}s clip (audio={'on' if AUDIO_ENABLED else 'off'})...")
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        print("[video] ffmpeg failed:")
        print(result.stderr[-2000:])
        return None
    return path


def main():
    caffeinate_process = start_caffeinate()

    print("=== Motion Monitor starting ===")
    if CALIBRATE_MODE:
        print("  *** CALIBRATION MODE *** - no photos/video will be saved, nothing sent to Telegram")
        print(f"  video recording: {'ON' if VIDEO_ENABLED else 'OFF'}")
        print(f"  audio in clips:  {'ON' if AUDIO_ENABLED else 'OFF'}" + ("" if VIDEO_ENABLED else " (irrelevant, video is off)"))
        print(f"  pixel_change_threshold:   {PIXEL_CHANGE_THRESHOLD}")
        print(f"  motion_percent_threshold: {MOTION_PERCENT_THRESHOLD}%")
        print("Watch the [calibrate] line below to tune those two values in config/config.json.")
        print()

    camera = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_AVFOUNDATION)
    if not camera.isOpened():
        print("[camera] Could not open camera.")
        sys.exit(1)

    previous_frame = None
    print(f"[startup] Warming up for {WARMUP_FRAMES} frames to establish baseline...")
    for _ in range(WARMUP_FRAMES):
        ok, frame = camera.read()
        if not ok:
            continue
        processed = preprocess(frame)
        previous_frame = processed
    print("[startup] Warmup complete. Monitoring for motion...\n")

    last_motion_time = 0

    try:
        while True:
            ok, frame = camera.read()
            if not ok:
                print("[camera] Failed to read frame, retrying...")
                time.sleep(0.5)
                continue

            current_frame = preprocess(frame)

            if previous_frame is None:
                previous_frame = current_frame
                continue

            changed_percentage, _threshold_img, diff_stats = detect_motion(previous_frame, current_frame)

            # Live calibration printout - overwrites the same terminal line.
            if CALIBRATE_MODE:    
                print(
                    f"\r[calibrate] max_pixel_diff={diff_stats['max_diff']:>3} "
                    f"(pixel_change_threshold={PIXEL_CHANGE_THRESHOLD})  |  "
                    f"frame_changed={changed_percentage:6.2f}% "
                    f"(motion_percent_threshold={MOTION_PERCENT_THRESHOLD}%)   ",
                    end="",
                    flush=True,
                )

            now = time.time()

            if changed_percentage > MOTION_PERCENT_THRESHOLD and (now - last_motion_time) > COOLDOWN_SECONDS:
                last_motion_time = now
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                if CALIBRATE_MODE:
                    print(f"\n[motion] Would trigger at {timestamp} (frame_changed={changed_percentage:.2f}%) - calibration mode, nothing saved/sent.")
                    print()
                    previous_frame = current_frame
                    continue

                print(f"\n[motion] Motion detected at {timestamp} (frame_changed={changed_percentage:.2f}%)")

                photo = save_snapshot(frame)
                if photo:
                    print(f"[photo] Saved {photo}")
                    send_telegram_photo(photo)

                if VIDEO_ENABLED:
                    # ffmpeg needs exclusive access to the camera, so
                    # release OpenCV's handle first and reopen after.
                    camera.release()
                    clip = record_clip_with_audio(RECORD_SECONDS)
                    if clip:
                        print(f"[video] Saved {clip}")
                        send_telegram_video(clip)

                    camera = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_AVFOUNDATION)

                    # Re-warm: auto-exposure/white balance need a moment to settle,
                    # and the old previous_frame is stale. Comparing against it
                    # causes a false-positive trigger that loops forever.
                    print(f"[video] Re-warming camera for {WARMUP_FRAMES} frames after reopen...")
                    previous_frame = None
                    for _ in range(WARMUP_FRAMES):
                        ok, warm_frame = camera.read()
                        if not ok:
                            continue
                        previous_frame = preprocess(warm_frame)

                    # Reset cooldown so we don't instantly re-trigger either.
                    last_motion_time = time.time()

                print()  # blank line before calibration printout resumes
                print("[running] Monitoring for motion...\n")    


            previous_frame = current_frame

    except KeyboardInterrupt:
        print("\n[shutdown] Stopping Motion Monitor...")
    finally:
        camera.release()
        caffeinate_process.terminate()


if __name__ == "__main__":
    main()
