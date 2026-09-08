# Motion Monitor

A simple Mac motion detector. Watches the built-in camera, and when it
detects motion:

- Saves a photo locally
- Records a short video clip with audio, locally
- Optionally sends both to a Telegram chat, so you get an alert on your
  phone almost instantly

You can also pause, resume, or shut down the monitor remotely by sending
a message to your Telegram bot — handy if you're about to walk into its
field of view and don't want to trigger it.

Runs entirely on your Mac — nothing is streamed or uploaded
continuously, only the photo/clip from an actual motion event.

## Requirements

- macOS (uses AVFoundation for camera/mic access and `caffeinate` to
  prevent system sleep)
- Python 3.9+
- [ffmpeg](https://ffmpeg.org/) (for video+audio recording)
  ```bash
  brew install ffmpeg
  ```

### Don't have Homebrew?

If you don't have [Homebrew](https://brew.sh/) installed, you can install it through Terminal:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

After Homebrew is installed, run:

```bash
brew install ffmpeg
```

Or, you can download and install ffmpeg directly from the [official ffmpeg website](https://ffmpeg.org/download.html).

## Setup

```bash
git clone <this-repo-url> motion_monitor
cd motion_monitor
./setup.sh
```

`setup.sh` will:
1. Create a Python virtual environment in `./venv`
2. Install dependencies from `requirements.txt`
3. Copy `config/config.example.json` → `config/config.json`

Then edit `config/config.json` and fill in your Telegram bot token and
chat id (see below for how to get these).

## Running

```bash
./run.sh
```

This activates the virtual environment for you and starts the monitor.
Press `Ctrl+C` to stop.

On startup, the program waits `startup_delay_seconds` (30s by default)
before opening the camera and establishing its baseline — this is your
window to get out of frame. If you're still visible when the baseline is
captured, leaving afterward will itself register as motion. A live
countdown prints to the terminal during this wait.

```bash
./run.sh --calibrate 
```
This activates the virtual environment and starts the monitor in calibration mode: Only data on actual pixel differences and % of frame change will be printed to the terminal. No images, video or audio will be saved. 

## Remote control via Telegram

If Telegram is configured (see below), you can control the monitor by
sending it messages from your phone — no need to be at the Mac:

| Command              | Effect                                                         |
|-----------------------|------------------------------------------------------------------|
| `pause`                | Stops evaluating motion. Camera stays open, nothing triggers.   |
| `resume`               | Re-establishes the baseline, then resumes normal monitoring.    |
| `shutdown` or `stop`   | Cleanly stops the program.                                       |

Commands are case-insensitive (`PAUSE`, `Pause`, `pause` all work), and
the `/` prefix is optional (`/pause` also works). Misspelled or
unrecognized commands are currently ignored without a reply — if you
don't see a confirmation, double-check your spelling.

Each command gets a confirmation reply in Telegram, and is also logged
to the terminal. For security, only messages from the `chat_id`
configured in `config.json` are honored — anyone else who messages your
bot is silently ignored, since this project is open source and the bot
itself could otherwise be discovered and controlled by a stranger.

Set `telegram.listen_for_commands` to `false` in `config.json` if you
want outbound notifications (photo/video alerts) without this inbound
control feature.

## Configuration

All tunable settings live in `config/config.json`. This file is
git-ignored since it holds your Telegram credentials — only
`config/config.example.json` (a safe template with no real secrets) is
committed to the repo.

| Section     | Key                       | Meaning                                                    |
|-------------|----------------------------|-------------------------------------------------------------|
| top-level   | `camera_index`             | Which camera to use (`0` is usually the built-in camera)   |
| top-level   | `startup_delay_seconds`    | Wait time before the camera opens, so you can get out of frame (default 30) |
| top-level   | `media_dir`                | Where photos/clips are saved locally                        |
| `detection` | `pixel_change_threshold`   | Lower = more sensitive to per-pixel change                  |
| `detection` | `motion_percent_threshold` | % of frame that must change to count as motion              |
| `detection` | `cooldown_seconds`         | Minimum gap between motion triggers                         |
| `detection` | `warmup_frames`            | Frames used to establish the initial background             |
| `photo`     | `jpeg_quality`              | JPEG quality, 0–100                                          |
| `video`     | `enabled`                  | Set `false` to disable video recording                      |
| `video`     | `record_seconds`           | Length of each recorded clip                                 |
| `video`     | `ffmpeg_video_device`      | Camera device index for ffmpeg (see below)                  |
| `video`     | `ffmpeg_audio_device`      | Legacy microphone index for ffmpeg; use `audio.input_device` instead when possible |
| `video`     | `ffmpeg_framerate`         | Recording framerate                                          |
| `video`     | `ffmpeg_resolution`        | Recording resolution                                         |
| `audio`     | `enabled`                  | Set `false` to disable audio recording                       |
| `audio`     | `input_device`             | Exact AVFoundation microphone name; resolves to its current index at startup |
| `telegram`  | `enabled`                  | Set `false` to disable Telegram entirely and stay fully local |
| `telegram`  | `bot_token`                | Your bot's token from BotFather                              |
| `telegram`  | `chat_id`                  | Your personal chat id                                        |
| `telegram`  | `listen_for_commands`      | Set `false` to disable remote pause/resume/shutdown (default `true`) |

If `config/config.json` is missing entirely, the program prints setup
instructions and exits rather than failing with a confusing error.

If Telegram credentials are missing or still set to the placeholder
values, the program keeps working and saves everything locally — it
just skips the Telegram upload step and logs that it did so.

### Choosing an audio input device

For audio, prefer a human-readable device name rather than a numeric
AVFoundation index. Numeric indexes can change when microphones, displays,
docks, or other hardware are added or removed.

List the names currently seen by ffmpeg:

```bash
ffmpeg -f avfoundation -list_devices true -i ""
```

The same command also lists numbered video devices.
`video.ffmpeg_video_device` remains a numeric ffmpeg index.

Copy the desired name exactly into `audio.input_device` in
`config/config.json`:

```json
"audio": {
  "enabled": true,
  "input_device": "MacBook Pro Microphone"
}
```

On every startup, Motion Monitor discovers the current AVFoundation devices
and resolves that name to its current numeric index before it records. It logs
both the requested name and the resolved index. If the name is missing or
matches more than one device, the monitor stops with a list of available
devices rather than recording from an unintended microphone.

`audio.input_device` is optional for compatibility with existing
configurations. If it is omitted or `null`, the monitor uses the legacy
`video.ffmpeg_audio_device` numeric index and prints a warning. The video
camera setting, `video.ffmpeg_video_device`, remains a numeric ffmpeg index.

### Setting up the Telegram bot

This project uses an optional Telegram bot to send notifications to your phone.

#### 1. Install Telegram

First, install the official Telegram app for your device.

- **[iPhone / iPad — App Store](https://apps.apple.com/app/telegram-messenger/id686449807)**
- **[Android — Google Play](https://play.google.com/store/apps/details?id=org.telegram.messenger)**
- **[Mac / Windows / Linux — Telegram Desktop](https://desktop.telegram.org/)**

Make sure you're downloading the official Telegram app — the links above go directly to Telegram's official listings.

Create a Telegram account, or log into your existing one.

#### 2. Create a Telegram bot

Open Telegram and search for:

```text
@BotFather
```

Make sure you're talking to the official, verified BotFather account — it has a blue checkmark badge.

Send:

```text
/newbot
```

BotFather will ask for two things:

- **Bot name** — the display name for your bot, e.g. `My Security Monitor`
- **Bot username** — must be unique and end in `bot`, e.g. `my_security_monitor_bot`

BotFather will then give you an API token that looks something like:

```text
123456789:AAExampleTokenHere123456789
```

#### 3. Keep your bot token private

Your bot token is essentially the password that allows programs to control your bot.

- Do not post your bot token on GitHub or include it directly in your source code.
- Store it in your local `config/config.json` instead (which is git-ignored).

#### 4. Start your bot

Search Telegram for the username you gave your bot, e.g. `@my_security_monitor_bot`.

Open the bot and press **Start**, or send:

```text
/start
```

#### 5. Get your Telegram chat ID

Now that you've started a conversation with your bot, you can retrieve your chat ID.

Open the following URL in your browser, replacing `YOUR_BOT_TOKEN` with the token BotFather gave you:

```text
https://api.telegram.org/botYOUR_BOT_TOKEN/getUpdates
```

You should get back a JSON response containing information about your recent message. Look for:

```json
"chat": {
    "id": 123456789,
    ...
}
```

The number after `"id"` is your chat ID.

You'll need both values for the program:

```text
BOT_TOKEN = your bot token
CHAT_ID   = your chat ID
```

#### 6. Configure the program

Add your bot token and chat ID to `config/config.json` as described above.

If you ever accidentally expose your token, immediately go back to BotFather and revoke/regenerate it.

## Permissions

The first time you run this, macOS will prompt for:
- **Camera** access (System Settings → Privacy & Security → Camera)
- **Microphone** access, separately (System Settings → Privacy &
  Security → Microphone)

Grant both to whatever terminal/editor you're running the script from.

## Project structure

```
motion_monitor/
├── config/
│   ├── config.example.json      # safe template, committed to git
│   └── config.json              # your real settings, git-ignored
├── src/
│   ├── motion_monitor.py        # main program / entry point
│   ├── config.py                # loads and exposes config.json as a Config object
│   ├── telegram_control.py      # inbound Telegram commands (pause/resume/shutdown)
│   └── detection/
│       ├── base.py              # MotionDetector interface
│       └── frame_difference.py  # the current (only) detection algorithm
├── requirements.txt
├── setup.sh                     # one-time setup
├── run.sh                       # start the monitor
├── .gitignore
└── README.md
```
