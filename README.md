# Motion Monitor

A simple Mac motion detector. Watches the built-in camera, and when it
detects motion:

- Saves a photo locally
- Records a short video clip with audio, locally
- Optionally sends both to a Telegram chat, so you get an alert on your
  phone almost instantly

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

## Configuration

All tunable settings live in `config/config.json`. This file is
git-ignored since it holds your Telegram credentials — only
`config/config.example.json` (a safe template with no real secrets) is
committed to the repo.

| Section     | Key                       | Meaning                                                    |
|-------------|----------------------------|-------------------------------------------------------------|
| top-level   | `camera_index`             | Which camera to use (`0` is usually the built-in camera)   |
| top-level   | `media_dir`                | Where photos/clips are saved locally                        |
| `detection` | `pixel_change_threshold`   | Lower = more sensitive to per-pixel change                  |
| `detection` | `motion_percent_threshold` | % of frame that must change to count as motion              |
| `detection` | `cooldown_seconds`         | Minimum gap between motion triggers                         |
| `detection` | `warmup_frames`            | Frames used to establish the initial background             |
| `photo`     | `jpeg_quality`              | JPEG quality, 0–100                                          |
| `video`     | `record_seconds`           | Length of each recorded clip                                 |
| `video`     | `ffmpeg_video_device`      | Camera device index for ffmpeg (see below)                  |
| `video`     | `ffmpeg_audio_device`      | Microphone device index for ffmpeg (see below)               |
| `video`     | `ffmpeg_framerate`         | Recording framerate                                          |
| `video`     | `ffmpeg_resolution`        | Recording resolution                                         |
| `telegram`  | `enabled`                  | Set `false` to disable Telegram entirely and stay fully local |
| `telegram`  | `bot_token`                | Your bot's token from BotFather                              |
| `telegram`  | `chat_id`                  | Your personal chat id                                        |

If `config/config.json` is missing entirely, the program prints setup
instructions and exits rather than failing with a confusing error.

If Telegram credentials are missing or still set to the placeholder
values, the program keeps working and saves everything locally — it
just skips the Telegram upload step and logs that it did so.

### Finding your ffmpeg device indices

```bash
ffmpeg -f avfoundation -list_devices true -i ""
```

This prints numbered video devices and numbered audio devices. Match
the numbers to your Mac's built-in camera and microphone, and set
`ffmpeg_video_device` / `ffmpeg_audio_device` in `config/config.json`
accordingly.

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
│   ├── config.example.json   # safe template, committed to git
│   └── config.json           # your real settings, git-ignored
├── src/
│   └── motion_monitor.py     # main program
├── requirements.txt
├── setup.sh                  # one-time setup
├── run.sh                    # start the monitor
├── .gitignore
└── README.md
```
