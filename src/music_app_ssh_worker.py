import base64
import json
import logging
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import paramiko

_OSX_SCRIPTS_DIR = Path(__file__).parent / "osx" / "scripts"
_RECOVER_AIRPLAY_PLAYBACK_SCRIPT_PATH = _OSX_SCRIPTS_DIR / "recover_airplay_playback.js"
_GET_NOW_PLAYING_SCRIPT_PATH = _OSX_SCRIPTS_DIR / "get_now_playing.js"
_GET_PLAYLIST_TRACKS_SCRIPT_PATH = _OSX_SCRIPTS_DIR / "get_playlist_tracks.js"
# Include the surrounding quotes from the .js file's dummy string literals
# (e.g. `"__AIRPLAY_DEVICE_NAME__"`) so the whole literal -- quotes and all
# -- gets replaced by json.dumps(...)'s own quoting, rather than nesting one
# inside the other.
_AIRPLAY_DEVICE_NAME_PLACEHOLDER = '"__AIRPLAY_DEVICE_NAME__"'
_PLAYLIST_NAME_PLACEHOLDER = '"__PLAYLIST_NAME__"'


def default_airplay_device_name() -> str:
    """Matches shairport-sync's own default AirPlay device name: with
    general.name left unset in shairport-sync.conf, its default is "%H" --
    documented (shairport-sync.conf.sample) as "the machine's hostname
    with the first letter capitalised (ASCII only)". A plain
    socket.gethostname() does NOT capitalise, so relying on that alone to
    match "%H" fails silently -- confirmed on jukebox0: AirPlay recovery
    couldn't find "jukebox0" because the real advertised name was
    "Jukebox0". Only the first letter changes case here, not
    str.capitalize(), which would also lowercase the rest of the
    hostname (irrelevant for an all-lowercase hostname like "jukebox0",
    but wrong in general)."""
    hostname = socket.gethostname()
    return hostname[:1].upper() + hostname[1:]


@dataclass(frozen=True)
class CommandResult:
    exit_status: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_status == 0


class MusicAppSSHWorker:
    """Maintains a persistent SSH connection (authenticated via a private
    key, never a password) to the machine running the macOS "Music"
    application, so the jukebox can run commands there that shairport-sync's
    own MQTT metadata has no equivalent for -- recover_airplay_playback(),
    get_now_playing(), get_playlist_tracks() -- all JavaScript for
    Automation/`osascript` automation of the Music app itself, piped in
    over the connection rather than run from a file on the remote machine.

    Mirrors ShairportSyncMQTTSource's connection-lifecycle shape: a
    background thread holds one connection at a time, a keepalive keeps it
    (and any NAT/firewall state in between) alive and lets a dead connection
    be noticed quickly, and a dropped connection is retried after a fixed
    delay, indefinitely, until stop() is called.
    """

    def __init__(
        self,
        host: str,
        username: str,
        key_path: str,
        port: int = 22,
        keepalive_interval_s: float = 30.0,
        reconnect_delay_s: float = 5.0,
        connect_timeout_s: float = 10.0,
        strict_host_key_checking: bool = False,
        airplay_device_name: Optional[str] = None,
        playlist_name: str = "Jukebox",
        on_connection_lost: Optional[Callable[[], None]] = None,
        on_connection_established: Optional[Callable[[], None]] = None,
    ) -> None:
        self._logger = logging.getLogger(self.__class__.__name__)
        self._host = host
        self._port = port
        self._username = username
        self._key_path = key_path
        self._keepalive_interval_s = keepalive_interval_s
        self._reconnect_delay_s = reconnect_delay_s
        self._connect_timeout_s = connect_timeout_s
        self._strict_host_key_checking = strict_host_key_checking
        # Name of the AirPlay device recover_airplay_playback() should
        # select. Defaults to this machine's (the Pi's) own hostname with
        # the first letter capitalised (see default_airplay_device_name())
        # -- that's what shairport-sync itself advertises unless configured
        # otherwise -- unrelated to playlist_name below, which is a
        # separately-chosen Music.app playlist to start playing when
        # nothing is already playing. Both vary per jukebox install, so
        # they're substituted into the script text rather than hardcoded
        # there. The script itself is read once, at construction (not
        # per-call), so a missing/unreadable file fails fast at startup
        # instead of hours into runtime, the first time recovery is needed.
        self._airplay_device_name = airplay_device_name or default_airplay_device_name()
        self._playlist_name = playlist_name
        self._recover_airplay_playback_script_template = _RECOVER_AIRPLAY_PLAYBACK_SCRIPT_PATH.read_text()
        self._get_now_playing_script_template = _GET_NOW_PLAYING_SCRIPT_PATH.read_text()
        self._get_playlist_tracks_script_template = _GET_PLAYLIST_TRACKS_SCRIPT_PATH.read_text()
        self._on_connection_lost = on_connection_lost
        self._on_connection_established = on_connection_established

        self._client: Optional[paramiko.SSHClient] = None
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._connect_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        with self._lock:
            self._disconnect_locked()

    def is_connected(self) -> bool:
        with self._lock:
            return self._is_connected_locked()

    def execute(self, command: str, timeout_s: Optional[float] = None) -> CommandResult:
        """Run `command` on the remote machine and block for its result.

        Raises ConnectionError if the SSH session is not currently up
        (e.g. mid-reconnect) rather than blocking until one appears --
        callers that need to wait should retry at their own discretion.
        """
        with self._lock:
            if not self._is_connected_locked():
                raise ConnectionError(f"Not connected to {self._host}")
            client = self._client

        _, stdout, stderr = client.exec_command(command, timeout=timeout_s)
        exit_status = stdout.channel.recv_exit_status()
        return CommandResult(
            exit_status=exit_status,
            stdout=stdout.read().decode("utf-8", errors="replace"),
            stderr=stderr.read().decode("utf-8", errors="replace"),
        )

    def recover_airplay_playback(self, timeout_s: Optional[float] = 30.0) -> CommandResult:
        """Run src/osx/scripts/recover_airplay_playback.js on the remote
        machine (as JavaScript for Automation, via osascript) to re-select
        airplay_device_name's AirPlay device in the Music app and, if
        nothing is already playing, start playlist_name. Intended as the
        fallback for when ShairportSyncMQTTSource's
        on_remote_command_unresponsive fires.

        The script never touches disk on the remote machine: it's read from
        this codebase, has the device/playlist names substituted in, and is
        base64-piped directly into `osascript -l JavaScript`'s stdin over
        the existing SSH connection -- so there's nothing to separately
        deploy to the Mac.

        Raises ConnectionError (via execute()) if the SSH session is not
        currently up."""
        script = self._recover_airplay_playback_script_template.replace(
            _AIRPLAY_DEVICE_NAME_PLACEHOLDER, json.dumps(self._airplay_device_name)
        ).replace(
            _PLAYLIST_NAME_PLACEHOLDER, json.dumps(self._playlist_name)
        )
        encoded = base64.b64encode(script.encode()).decode()
        command = f"echo {encoded} | base64 -d | osascript -l JavaScript"
        return self.execute(command, timeout_s=timeout_s)

    def get_now_playing(self, timeout_s: Optional[float] = 15.0) -> CommandResult:
        """Run src/osx/scripts/get_now_playing.js on the remote machine (as
        JavaScript for Automation, via osascript) to read Music.app's
        currently loaded track, if any -- a read-only counterpart to
        recover_airplay_playback(), for when this process needs to know
        what's already playing rather than to make something play.

        stdout is JSON on success -- {"playerState": ..., "airplaySelected":
        bool} alone, or with "name"/"artist"/"album"/"persistentID" added if
        a track is loaded (see the script for exact shape); parsing it is
        left to the caller. airplaySelected reflects airplay_device_name
        specifically -- playerState "playing" alone does not mean this Pi
        is actually the AirPlay target; Music.app could be playing to a
        completely different output. Raises ConnectionError (via execute())
        if the SSH session is not currently up."""
        script = self._get_now_playing_script_template.replace(
            _AIRPLAY_DEVICE_NAME_PLACEHOLDER, json.dumps(self._airplay_device_name)
        )
        encoded = base64.b64encode(script.encode()).decode()
        command = f"echo {encoded} | base64 -d | osascript -l JavaScript"
        return self.execute(command, timeout_s=timeout_s)

    def get_playlist_tracks(self, timeout_s: Optional[float] = 60.0) -> CommandResult:
        """Run src/osx/scripts/get_playlist_tracks.js on the remote machine
        (as JavaScript for Automation, via osascript) to enumerate
        playlist_name's tracks in the Music app -- the live replacement for
        a bundled, manually-maintained playlist file (see Playlist in
        playlist.py).

        stdout is a JSON array of {"Name", "Index", "Artist",
        "PersistentID"} objects on success, one per track in playlist
        order, and can be passed straight to Playlist(). Longer default
        timeout than the other scripts here since this enumerates every
        track in the playlist rather than doing a single lookup. Raises ConnectionError
        (via execute()) if the SSH session is not currently up."""
        script = self._get_playlist_tracks_script_template.replace(
            _PLAYLIST_NAME_PLACEHOLDER, json.dumps(self._playlist_name)
        )
        encoded = base64.b64encode(script.encode()).decode()
        command = f"echo {encoded} | base64 -d | osascript -l JavaScript"
        return self.execute(command, timeout_s=timeout_s)

    def _is_connected_locked(self) -> bool:
        transport = self._client.get_transport() if self._client else None
        return transport is not None and transport.is_active()

    def _disconnect_locked(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

    def _connect_loop(self) -> None:
        while self._running:
            connected = self._try_connect()
            if connected:
                if self._on_connection_established:
                    self._on_connection_established()
                self._wait_while_connected()
                if self._on_connection_lost:
                    self._on_connection_lost()
            if self._running:
                self._logger.info("Reconnecting in %.0fs...", self._reconnect_delay_s)
                time.sleep(self._reconnect_delay_s)

    def _try_connect(self) -> bool:
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(
            paramiko.AutoAddPolicy() if not self._strict_host_key_checking else paramiko.RejectPolicy()
        )
        try:
            self._logger.info("Connecting to %s@%s:%d ...", self._username, self._host, self._port)
            client.connect(
                hostname=self._host,
                port=self._port,
                username=self._username,
                key_filename=self._key_path,
                timeout=self._connect_timeout_s,
                allow_agent=False,
                look_for_keys=False,
            )
            client.get_transport().set_keepalive(int(self._keepalive_interval_s))
        except Exception as e:
            self._logger.error("SSH connection error: %s", e)
            try:
                client.close()
            except Exception:
                pass
            return False

        self._logger.info("SSH connected")
        with self._lock:
            self._client = client
        return True

    def _wait_while_connected(self) -> None:
        # Polls rather than blocking on a paramiko event so stop() (which
        # flips _running) is noticed promptly instead of only after the
        # transport itself dies.
        while self._running:
            with self._lock:
                if not self._is_connected_locked():
                    self._disconnect_locked()
                    return
            time.sleep(min(1.0, self._keepalive_interval_s))
        with self._lock:
            self._disconnect_locked()
