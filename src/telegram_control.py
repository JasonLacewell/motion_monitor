"""
Telegram inbound command listener.

Unlike the outbound notification helpers in motion_monitor.py (send photo/
video/text), this listens for incoming Telegram messages so the program
can be controlled remotely: pause, resume, shutdown.

This runs on its own background thread (Telegram long-polling blocks), and
communicates with the main monitoring loop only through ControlState, which
uses threading.Event so reads/writes are safe across threads without
needing explicit locks.

Security note: commands are only accepted from the chat_id configured in
config.json. Since this project is open source, anyone could message your
bot - without this check, a stranger who found the bot username could pause
or shut down your camera. Messages from any other chat are ignored.
"""

import threading
import time

import requests


class ControlState:
    """Thread-safe flags shared between the main loop and the listener thread."""

    def __init__(self):
        self._shutdown_requested = threading.Event()
        self._paused = threading.Event()

    def request_pause(self):
        self._paused.set()

    def request_resume(self):
        self._paused.clear()

    def request_shutdown(self):
        self._shutdown_requested.set()

    @property
    def is_paused(self) -> bool:
        return self._paused.is_set()

    @property
    def is_shutdown_requested(self) -> bool:
        return self._shutdown_requested.is_set()


class TelegramCommandListener:
    """Polls Telegram for new messages and translates recognized commands
    into ControlState changes. Runs on a daemon thread so it never blocks
    program shutdown."""

    RECOGNIZED_COMMANDS = {
        "pause": "pause",
        "/pause": "pause",
        "resume": "resume",
        "/resume": "resume",
        "shutdown": "shutdown",
        "/shutdown": "shutdown",
        "stop": "shutdown",
        "/stop": "shutdown",
    }

    def __init__(self, config, control_state: ControlState):
        self.config = config
        self.control_state = control_state
        self._offset = None
        self._stop_polling = threading.Event()
        self._thread = None

    def start(self):
        if not self.config.telegram_is_configured():
            print("[telegram] Command listener not started - Telegram not configured.")
            return
        if not self.config.telegram_listen_for_commands:
            print("[telegram] Command listener disabled in config.")
            return

        # Consume any backlog of messages sent while the program was offline,
        # WITHOUT acting on them - otherwise an old "shutdown" message sent
        # hours ago could kill a fresh start immediately.
        self._consume_backlog()

        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="telegram-listener")
        self._thread.start()
        print("[telegram] Command listener started (pause / resume / shutdown).")

    def stop(self):
        self._stop_polling.set()

    def _consume_backlog(self):
        url = f"https://api.telegram.org/bot{self.config.telegram_token}/getUpdates"
        try:
            resp = requests.get(url, params={"timeout": 0}, timeout=10)
            resp.raise_for_status()
            results = resp.json().get("result", [])
            if results:
                self._offset = results[-1]["update_id"] + 1
        except requests.RequestException as e:
            print(f"[telegram] Could not clear command backlog: {e}")

    def _poll_loop(self):
        url = f"https://api.telegram.org/bot{self.config.telegram_token}/getUpdates"
        while not self._stop_polling.is_set():
            params = {"timeout": 25}
            if self._offset is not None:
                params["offset"] = self._offset
            try:
                resp = requests.get(url, params=params, timeout=30)
                resp.raise_for_status()
                updates = resp.json().get("result", [])
            except requests.RequestException as e:
                print(f"[telegram] Command listener error: {e}")
                time.sleep(5)
                continue

            for update in updates:
                self._offset = update["update_id"] + 1
                self._handle_update(update)

    def _handle_update(self, update):
        message = update.get("message") or update.get("channel_post")
        if not message:
            return

        chat_id = str(message.get("chat", {}).get("id", ""))
        if chat_id != str(self.config.telegram_chat_id):
            # Not from the configured chat - ignore silently.
            return

        text = (message.get("text") or "").strip().lower()
        command = self.RECOGNIZED_COMMANDS.get(text)

        if command == "pause":
            self.control_state.request_pause()
            print("[telegram] Received PAUSE command.")
            self._reply("Motion Monitor paused.")
        elif command == "resume":
            self.control_state.request_resume()
            print("[telegram] Received RESUME command.")
            self._reply("Motion Monitor resumed.")
        elif command == "shutdown":
            # Send the confirmation BEFORE flipping the shutdown flag. The
            # main loop checks that flag on every frame and can shut the
            # whole process down within milliseconds - if the reply is
            # sent after, this daemon thread can get killed mid-request
            # before the message actually reaches Telegram's servers.
            print("[telegram] Received SHUTDOWN command - stopping Motion Monitor.")
            self._reply("Motion Monitor shutting down.")
            self.control_state.request_shutdown()

    def _reply(self, text: str):
        """Best-effort confirmation reply. Failure here should never crash
        the listener - it's a courtesy, not the source of truth (the
        terminal print is)."""
        url = f"https://api.telegram.org/bot{self.config.telegram_token}/sendMessage"
        try:
            requests.post(url, data={"chat_id": self.config.telegram_chat_id, "text": text}, timeout=15)
        except requests.RequestException:
            pass
