"""
Configuration loading for Motion Monitor.

This module centralizes what used to be a set of module-level globals in
motion_monitor.py. Behavior is unchanged from before the refactor - this
just gives every setting one clear owner (a Config instance) instead of
scattering CONSTANT_NAMES across the top of the main script.
"""

import json
import sys
from pathlib import Path


class Config:
    def __init__(self, raw: dict, config_path: Path):
        self._raw = raw
        self.config_path = config_path

        self.camera_index = raw["camera_index"]

        self.media_dir = Path(raw["media_dir"]).expanduser()
        self.media_dir.mkdir(parents=True, exist_ok=True)

        self.jpeg_quality = raw["photo"]["jpeg_quality"]

        self.video_enabled = raw["video"].get("enabled", True)
        self.record_seconds = raw["video"]["record_seconds"]
        self.ffmpeg_video_device = raw["video"]["ffmpeg_video_device"]
        self.ffmpeg_audio_device = raw["video"]["ffmpeg_audio_device"]
        self.ffmpeg_framerate = raw["video"]["ffmpeg_framerate"]
        self.ffmpeg_resolution = raw["video"]["ffmpeg_resolution"]

        self.audio_enabled = raw.get("audio", {}).get("enabled", True)

        self.send_telegram = raw["telegram"]["enabled"]
        self.telegram_token = raw["telegram"]["bot_token"]
        self.telegram_chat_id = raw["telegram"]["chat_id"]

        self.pixel_change_threshold = raw["detection"]["pixel_change_threshold"]
        self.motion_percent_threshold = raw["detection"]["motion_percent_threshold"]

        # Same derived logic as the original module-level code: when video
        # recording is on, the clip length itself enforces a natural
        # cooldown (+5s buffer), so the configured cooldown_seconds is only
        # used when video is off.
        if self.video_enabled:
            self.cooldown_seconds = self.record_seconds + 5
        else:
            self.cooldown_seconds = raw["detection"]["cooldown_seconds"]

        self.warmup_frames = raw["detection"]["warmup_frames"]

    @classmethod
    def load(cls, project_root: Path) -> "Config":
        """Load config/config.json, with the same missing-file error/exit
        behavior as the original script."""
        config_path = project_root / "config" / "config.json"
        example_path = project_root / "config" / "config.example.json"

        if not config_path.exists():
            print("No config/config.json found.")
            print(f"Copy {example_path.name} to config.json and edit it:")
            print(f"  cp {example_path} {config_path}")
            sys.exit(1)

        with open(config_path, "r") as f:
            raw = json.load(f)

        return cls(raw, config_path)

    def telegram_is_configured(self) -> bool:
        """True only if Telegram is enabled AND credentials look real
        (not the placeholder values from config.example.json)."""
        placeholder_values = {"", "PASTE_YOUR_BOT_TOKEN_HERE", "PASTE_YOUR_CHAT_ID_HERE"}
        if not self.send_telegram:
            return False
        if self.telegram_token in placeholder_values or self.telegram_chat_id in placeholder_values:
            print("[telegram] Credentials missing/placeholder - skipping upload, saving locally only.")
            return False
        return True
