import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import paramiko


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
    own MQTT metadata has no equivalent for (e.g. AppleScript/`osascript`
    automation of the Music app itself).

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
