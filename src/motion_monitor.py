#!/usr/bin/env python3
"""
Mac Motion Monitor

- Uses the Mac's built-in camera.
- Detects motion by comparing consecutive frames.
- On motion, saves a photo AND records a video clip with audio, locally.
- Optionally sends both to Telegram.
- Uses macOS caffeinate so the Mac can keep monitoring while the display sleeps.

All tunable settings live in config/config.json (see config/config.example.json
for a template and config/README covered in the project README).

Run with:
  ./run.sh
or directly (with the virtual environment active):
  python3 src/motion_monitor.py
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
        print("ERROR: config/config.json not found.")
        print()
        print("Set it up with:")
        print(f"  cp {CONFIG_EXAMPLE_PATH.relative_to(PROJECT_ROOT)} "
              f"{CONFIG_PATH.relative_to(PROJECT_ROOT)}")
        print("then edit config/config.json and fill in your own values")
        print("(especially the Telegram bot token and chat id).")
        sys.exit(1)

    with open(CONFIG_PATH) as f:
        return json.load(f)


CONFIG = load_config()

CAMERA_INDEX = CONFIG["camera_index"]
MEDIA_DIR = Path(CONFIG["media_dir"]).expanduser()

PIXEL_CHANGE_THRESHOLD = CONFIG["detection"]["pixel_change_threshold"]
MOTION_PERCENT_THRESHOLD = CONFIG["detection"]["motion_percent_threshold"]
COOLDOWN_SECONDS = CONFIG["detection"]["cooldown_seconds"]
WARMUP_FRAMES = CONFIG["detection"]["warmup_frames"]

JPEG_QUALITY = CONFIG["photo"]["jpeg_quality"]

RECORD_SECONDS = CONFIG["video"]["record_seconds"]
FFMPEG_VIDEO_DEVICE = CONFIG["video"]["ffmpeg_video_device"]
FFMPEG_AUDIO_DEVICE = CONFIG["video"]["ffmpeg_audio_device"]
FFMPEG_FRAMERATE = CONFIG["video"]["ffmpeg_framerate"]
FFMPEG_RESOLUTION = CONFIG["video"]["ffmpeg_resolution"]

SEND_TELEGRAM = CONFIG["telegram"]["enabled"]
TELEGRAM_TOKEN = CONFIG["telegram"]["bot_token"]
TELEGRAM_CHAT_ID = CONFIG["telegram"]["chat_id"]


# ----------------------------
# Telegram
# ----------------------------

def telegram_is_configured():
    placeholder_values = {"", "PASTE_YOUR_BOT_TOKEN_HERE", "PASTE_YOUR_CHAT_ID_HERE"}
    return bool(
        TELEGRAM_TOKEN and TELEGRAM_CHAT_ID
        and TELEGRAM_TOKEN not in placeholder_values
        and TELEGRAM_CHAT_ID not in placeholder_values
    )


def send_telegram_text(text: str):
    """Send a plain text status message to Telegram."""

    if not telegram_is_configured():
        print(f"Telegram is not configured; status message skipped: {text}")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    try:
        response = requests.post(
            url,
            data={"chat_id": TELEGRAM_CHAT_ID, "text": text},
            timeout=15,
        )

        if response.ok:
            return True
        else:
            print(f"Telegram status message failed: {response.status_code} {response.text}")
            return False

    except Exception as exc:
        print(f"Telegram status message failed: {exc}")
        return False


def send_telegram_photo(image_path: Path):
    """Send one snapshot to Telegram as a photo message."""

    if not telegram_is_configured():
        print("Telegram is not configured; photo was saved locally.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    caption = f"Motion detected - {datetime.now():%Y-%m-%d %H:%M:%S}"

    try:
        with open(image_path, "rb") as f:
            response = requests.post(
                url,
                data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption},
                files={"photo": f},
                timeout=30,
            )

        if response.ok:
            print("Telegram photo sent.")
            return True
        else:
            print(f"Telegram failed: {response.status_code} {response.text}")
            return False

    except Exception as exc:
        print(f"Telegram failed: {exc}")
        return False


def send_telegram_video(video_path: Path):
    """Send one motion clip to Telegram as a video message."""

    if not telegram_is_configured():
        print("Telegram is not configured; clip was saved locally.")
        return False

    file_size_mb = video_path.stat().st_size / (1024 * 1024)
    if file_size_mb > 50:
        print(
            f"Clip is {file_size_mb:.1f}MB, over Telegram's 50MB bot upload "
            f"limit. Skipping upload; clip is still saved locally."
        )
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
    caption = f"Motion detected - {datetime.now():%Y-%m-%d %H:%M:%S}"

    try:
        with open(video_path, "rb") as f:
            response = requests.post(
                url,
                data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption},
                files={"video": f},
                timeout=120,
            )

        if response.ok:
            print("Telegram video sent.")
            return True
        else:
            print(f"Telegram failed: {response.status_code} {response.text}")
            return False

    except Exception as exc:
        print(f"Telegram failed: {exc}")
        return False


# ----------------------------
# Camera / system helpers
# ----------------------------

def start_caffeinate():
    """
    Keep macOS from entering system sleep while this program runs.

    The display is still allowed to sleep; this is primarily to keep
    the monitoring process and camera available.
    """
    try:
        process = subprocess.Popen(
            ["caffeinate", "-i", "-s"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return process
    except Exception as exc:
        print(f"Could not start caffeinate: {exc}")
        return None


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
        changed_percentage, threshold_image
    """

    difference = cv2.absdiff(previous, current)

    _, threshold = cv2.threshold(
        difference,
        PIXEL_CHANGE_THRESHOLD,
        255,
        cv2.THRESH_BINARY,
    )

    threshold = cv2.dilate(threshold, None, iterations=2)

    changed_pixels = cv2.countNonZero(threshold)
    total_pixels = threshold.shape[0] * threshold.shape[1]

    changed_percentage = (changed_pixels / total_pixels) * 100.0

    return changed_percentage, threshold


def save_snapshot(frame):
    """Save a single JPEG snapshot from the current frame."""

    MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = MEDIA_DIR / f"motion_{timestamp}.jpg"

    success = cv2.imwrite(
        str(path),
        frame,
        [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY],
    )

    if not success:
        raise RuntimeError("Could not save snapshot.")

    return path


def record_clip_with_audio(seconds: int):
    """
    Record a fixed-length video clip WITH audio using ffmpeg.

    This talks to the camera and microphone directly through ffmpeg's
    avfoundation input, independent of OpenCV. The caller is responsible
    for releasing the OpenCV camera handle first, since macOS won't let
    two processes hold the camera open at once.
    """

    MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = MEDIA_DIR / f"motion_{timestamp}.mp4"

    device_string = f"{FFMPEG_VIDEO_DEVICE}:{FFMPEG_AUDIO_DEVICE}"

    command = [
        "ffmpeg",
        "-f", "avfoundation",
        "-framerate", str(FFMPEG_FRAMERATE),
        "-video_size", FFMPEG_RESOLUTION,
        "-i", device_string,
        "-t", str(seconds),
        "-vcodec", "libx264",
        "-preset", "ultrafast",
        "-acodec", "aac",
        "-y",
        str(path),
    ]

    result = subprocess.run(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=seconds + 30,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed (code {result.returncode}): "
            f"{result.stderr.decode(errors='replace')[-500:]}"
        )

    return path


def main():
    print()
    print("======================================")
    print("       MAC MOTION MONITOR")
    print("======================================")
    print()
    print(f"Media folder: {MEDIA_DIR}")
    print(f"Motion threshold: {MOTION_PERCENT_THRESHOLD}%")
    print(f"Cooldown: {COOLDOWN_SECONDS} seconds")
    print(f"Clip length: {RECORD_SECONDS} seconds")
    print()

    if SEND_TELEGRAM:
        if telegram_is_configured():
            print("Telegram: enabled")
        else:
            print("Telegram: NOT configured (check config/config.json)")
            print("Photos/clips will still be saved locally.")
    else:
        print("Telegram: disabled")

    print()

    MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    caffeinate_process = start_caffeinate()

    camera = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_AVFOUNDATION)

    if not camera.isOpened():
        print("ERROR: Could not open the Mac camera.")
        print()
        print("Make sure your terminal/editor has camera permission in:")
        print("System Settings → Privacy & Security → Camera")
        send_telegram_text(
            f"Motion monitor FAILED TO START (camera would not open) - "
            f"{datetime.now():%Y-%m-%d %H:%M:%S}"
        )
        return

    camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    print("Camera opened.")
    print()
    print("Warming up...")
    print("Move around normally while the background is established.")
    print()

    previous_frame = None

    for _ in range(WARMUP_FRAMES):
        success, frame = camera.read()

        if not success:
            print("ERROR: Could not read from camera.")
            send_telegram_text(
                f"Motion monitor FAILED TO START (camera read failed during "
                f"warmup) - {datetime.now():%Y-%m-%d %H:%M:%S}"
            )
            camera.release()
            if caffeinate_process:
                caffeinate_process.terminate()
            return

        processed = preprocess(frame)

        if previous_frame is None:
            previous_frame = processed

        time.sleep(0.05)

    print("Monitoring for motion.")
    print("Press Ctrl+C to stop.")
    print()

    send_telegram_text(
        f"Motion monitor started - {datetime.now():%Y-%m-%d %H:%M:%S}"
    )

    last_motion_time = 0

    try:
        while True:
            success, frame = camera.read()

            if not success:
                print("Warning: Could not read camera frame.")
                time.sleep(1)
                continue

            current_frame = preprocess(frame)

            changed_percentage, _ = detect_motion(
                previous_frame,
                current_frame,
            )

            previous_frame = current_frame

            now = time.time()

            if (
                changed_percentage >= MOTION_PERCENT_THRESHOLD
                and now - last_motion_time >= COOLDOWN_SECONDS
            ):
                last_motion_time = now

                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                print()
                print("--------------------------------------")
                print(f"MOTION DETECTED: {timestamp}")
                print(f"Changed area: {changed_percentage:.2f}%")

                try:
                    photo = save_snapshot(frame)
                    print(f"Photo saved: {photo}")

                    if SEND_TELEGRAM:
                        send_telegram_photo(photo)

                except Exception as exc:
                    print(f"Photo error: {exc}")

                try:
                    print(f"Recording {RECORD_SECONDS}s clip with audio...")

                    # ffmpeg needs exclusive access to the camera, so
                    # release OpenCV's handle first and reopen after.
                    camera.release()

                    clip = record_clip_with_audio(RECORD_SECONDS)
                    print(f"Clip saved: {clip}")

                    if SEND_TELEGRAM:
                        send_telegram_video(clip)

                except Exception as exc:
                    print(f"Recording error: {exc}")

                finally:
                    camera = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_AVFOUNDATION)
                    camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

                success, frame = camera.read()
                if success:
                    previous_frame = preprocess(frame)

                print("--------------------------------------")
                print()

            time.sleep(0.05)

    except KeyboardInterrupt:
        print()
        print("Stopping motion monitor...")
        send_telegram_text(
            f"Motion monitor stopped (manual) - {datetime.now():%Y-%m-%d %H:%M:%S}"
        )

    except Exception as exc:
        print()
        print(f"Motion monitor crashed: {exc}")
        send_telegram_text(
            f"Motion monitor CRASHED - {datetime.now():%Y-%m-%d %H:%M:%S}\n"
            f"Error: {exc}"
        )

    finally:
        camera.release()

        if caffeinate_process:
            caffeinate_process.terminate()

        print("Camera released.")
        print("Goodbye.")


if __name__ == "__main__":
    main()
