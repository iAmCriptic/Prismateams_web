"""
Lock Manager für Single-Worker-Tasks
Stellt sicher, dass bestimmte Aufgaben nur von einem Gunicorn-Worker gleichzeitig ausgeführt werden.
Verwendet File-based Locking, das über Worker-Grenzen hinweg funktioniert.
"""

import os
import logging
import time
import threading
from contextlib import contextmanager
from pathlib import Path

try:
    from flask import current_app, has_app_context
except ImportError:  # pragma: no cover
    current_app = None
    has_app_context = lambda: False

import platform
IS_WINDOWS = platform.system() == 'Windows'

try:
    import fcntl  # Unix/Linux
    HAS_FCNTL = True
except ImportError:
    HAS_FCNTL = False

try:
    import msvcrt
    HAS_MSVCRT = True
except ImportError:
    HAS_MSVCRT = False

logger = logging.getLogger(__name__)

# Heartbeat älter als dieser Wert → Lock gilt als verwaist (Sekunden)
STALE_LOCK_SECONDS = 120


def _pid_is_alive(pid):
    """Prüft, ob ein Prozess mit gegebener PID noch läuft (plattformsicher)."""
    if not pid or pid <= 0:
        return False
    if IS_WINDOWS:
        import subprocess
        try:
            output = subprocess.check_output(
                ['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV', '/NH'],
                stderr=subprocess.DEVNULL,
                text=True,
                encoding='utf-8',
                errors='ignore',
            )
            # tasklist exit 0 auch ohne Treffer — Inhalt prüfen
            for line in output.splitlines():
                line = line.strip()
                if not line or line.upper().startswith('INFO:'):
                    continue
                # CSV: "name.exe","1234",...
                if f'"{pid}"' in line or f',{pid},' in line.replace('"', ''):
                    return True
            return False
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _read_lock_meta(lock_file_path):
    """Liest PID und Timestamp aus einer Lock-Datei."""
    pid = None
    timestamp = None
    try:
        with open(lock_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if line.startswith('PID:'):
                    try:
                        pid = int(line.split(':', 1)[1].strip())
                    except ValueError:
                        pass
                elif line.startswith('Timestamp:'):
                    try:
                        timestamp = float(line.split(':', 1)[1].strip())
                    except ValueError:
                        pass
    except OSError:
        pass
    return pid, timestamp


def _is_lock_stale(lock_file_path):
    """True wenn Lock-Datei verwaist ist (toter Prozess oder abgelaufener Heartbeat)."""
    if not lock_file_path.exists():
        return True
    pid, timestamp = _read_lock_meta(lock_file_path)
    now = time.time()
    try:
        file_age = now - lock_file_path.stat().st_mtime
    except OSError:
        return True
    heartbeat_age = (now - timestamp) if timestamp is not None else file_age
    if heartbeat_age >= STALE_LOCK_SECONDS:
        return True
    if pid is not None and not _pid_is_alive(pid):
        return True
    return False


class HeldLock:
    """Langlebiger Lock (z. B. Sync-Leader), muss explizit freigegeben werden."""

    def __init__(self, manager, lock_name, lock_file, lock_file_path):
        self._manager = manager
        self.lock_name = lock_name
        self._lock_file = lock_file
        self._lock_file_path = lock_file_path
        self._released = False

    def heartbeat(self):
        """Aktualisiert Timestamp/mtime, damit Stale-Detection nicht greift."""
        if self._released or not self._lock_file:
            return
        try:
            self._lock_file.seek(0)
            self._lock_file.truncate()
            self._lock_file.write(f"PID: {os.getpid()}\n")
            self._lock_file.write(f"Timestamp: {time.time()}\n")
            self._lock_file.flush()
            try:
                os.fsync(self._lock_file.fileno())
            except OSError:
                pass
            try:
                os.utime(self._lock_file_path, None)
            except OSError:
                pass
        except Exception as e:
            logger.debug("Heartbeat für Lock '%s' fehlgeschlagen: %s", self.lock_name, e)

    def release(self):
        if self._released:
            return
        self._released = True
        self._manager._release_lock_file(
            self.lock_name, self._lock_file, self._lock_file_path, unlink=True
        )
        self._lock_file = None


class LockManager:
    """Verwaltet File-based Locks für Single-Worker-Tasks."""

    def __init__(self, lock_dir=None):
        self.lock_dir = lock_dir
        self._locks = {}

    def _get_lock_dir(self):
        if self.lock_dir:
            path = Path(self.lock_dir)
            path.mkdir(parents=True, exist_ok=True)
            return path

        try:
            if has_app_context() and current_app:
                lock_dir = Path(current_app.instance_path) / 'locks'
                lock_dir.mkdir(parents=True, exist_ok=True)
                return lock_dir
        except Exception:
            pass

        import tempfile
        lock_dir = Path(tempfile.gettempdir()) / 'prismateams_locks'
        lock_dir.mkdir(parents=True, exist_ok=True)
        return lock_dir

    def _write_lock_meta(self, lock_file):
        lock_file.seek(0)
        lock_file.truncate()
        lock_file.write(f"PID: {os.getpid()}\n")
        lock_file.write(f"Timestamp: {time.time()}\n")
        lock_file.flush()

    def _try_acquire_once(self, lock_name):
        """
        Ein Versuch, den Lock zu nehmen.
        Returns: (lock_file, lock_file_path) oder (None, path)
        """
        lock_dir = self._get_lock_dir()
        lock_file_path = lock_dir / f"{lock_name}.lock"

        if HAS_FCNTL:
            lock_file = open(lock_file_path, 'a+', encoding='utf-8')
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._write_lock_meta(lock_file)
                logger.info("Lock '%s' erfolgreich erworben (PID: %s)", lock_name, os.getpid())
                return lock_file, lock_file_path
            except (IOError, OSError):
                lock_file.close()
                return None, lock_file_path

        # Windows / Fallback ohne fcntl
        if lock_file_path.exists() and _is_lock_stale(lock_file_path):
            try:
                lock_file_path.unlink()
                logger.info("Verwaiste Lock-Datei '%s' entfernt", lock_name)
            except OSError as e:
                logger.debug("Konnte verwaiste Lock-Datei nicht löschen: %s", e)

        try:
            # Exclusive create
            flags = os.O_CREAT | os.O_EXCL | os.O_RDWR
            if hasattr(os, 'O_BINARY'):
                flags |= os.O_BINARY
            fd = os.open(str(lock_file_path), flags)
            lock_file = os.fdopen(fd, 'r+', encoding='utf-8')
            if HAS_MSVCRT:
                try:
                    # Byte-Lock auf erstes Byte (zusätzliche Absicherung)
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError:
                    lock_file.close()
                    try:
                        lock_file_path.unlink()
                    except OSError:
                        pass
                    return None, lock_file_path
            self._write_lock_meta(lock_file)
            logger.info("Lock '%s' erfolgreich erworben (PID: %s)", lock_name, os.getpid())
            return lock_file, lock_file_path
        except FileExistsError:
            return None, lock_file_path
        except OSError:
            return None, lock_file_path

    def _release_lock_file(self, lock_name, lock_file, lock_file_path, unlink=True):
        if not lock_file:
            return
        try:
            if HAS_FCNTL:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                except Exception:
                    pass
            elif HAS_MSVCRT:
                try:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                except Exception:
                    pass
            try:
                lock_file.close()
            except Exception:
                pass
            if unlink and lock_file_path is not None:
                try:
                    if lock_file_path.exists():
                        lock_file_path.unlink()
                        logger.debug("Lock-Datei '%s' gelöscht", lock_file_path)
                except Exception as e:
                    logger.warning("Konnte Lock-Datei '%s' nicht löschen: %s", lock_file_path, e)
            logger.debug("Lock '%s' freigegeben", lock_name)
        except Exception as e:
            logger.error("Fehler beim Freigeben des Locks '%s': %s", lock_name, e)
            try:
                if unlink and lock_file_path and lock_file_path.exists():
                    lock_file_path.unlink()
            except Exception:
                pass

    @contextmanager
    def acquire_lock(self, lock_name, timeout=300, wait_interval=0.5):
        """
        Erwerbe einen Lock (Context Manager).

        timeout=0: ein Versuch, kein Warten.
        timeout>0: pollt bis Timeout.
        """
        lock_file = None
        lock_file_path = None
        acquired = False

        try:
            start_time = time.time()
            # timeout=0 → genau ein Versuch
            while True:
                lock_file, lock_file_path = self._try_acquire_once(lock_name)
                if lock_file is not None:
                    acquired = True
                    break

                if timeout <= 0:
                    break
                elapsed = time.time() - start_time
                if elapsed >= timeout:
                    break
                logger.debug(
                    "Lock '%s' nicht verfügbar, warte... (bereits %.1fs)",
                    lock_name, elapsed,
                )
                time.sleep(min(wait_interval, max(0.05, timeout - elapsed)))

            if not acquired:
                if timeout > 0:
                    logger.warning(
                        "Konnte Lock '%s' nicht innerhalb von %ss erwerben",
                        lock_name, timeout,
                    )
                else:
                    logger.debug("Lock '%s' nicht verfügbar (non-blocking)", lock_name)

            yield acquired
        except Exception as e:
            logger.error("Fehler beim Erwerben des Locks '%s': %s", lock_name, e, exc_info=True)
            yield False
        finally:
            if acquired and lock_file:
                self._release_lock_file(lock_name, lock_file, lock_file_path, unlink=True)

    def try_acquire_persistent(self, lock_name):
        """
        Nimmt Lock und hält ihn bis HeldLock.release() (Leader-Election).
        Returns HeldLock oder None.
        """
        lock_file, lock_file_path = self._try_acquire_once(lock_name)
        if lock_file is None:
            return None
        held = HeldLock(self, lock_name, lock_file, lock_file_path)
        self._locks[lock_name] = held
        return held

    def touch_lock(self, lock_name):
        """Heartbeat für einen aktiv gehaltenen Context-Lock (best effort via Datei)."""
        lock_dir = self._get_lock_dir()
        lock_file_path = lock_dir / f"{lock_name}.lock"
        held = self._locks.get(lock_name)
        if held:
            held.heartbeat()
            return
        if not lock_file_path.exists():
            return
        try:
            # Nur mtime anfassen wenn wir den Lock besitzen (PID match)
            pid, _ = _read_lock_meta(lock_file_path)
            if pid == os.getpid():
                with open(lock_file_path, 'r+', encoding='utf-8') as f:
                    self._write_lock_meta(f)
                os.utime(lock_file_path, None)
        except OSError as e:
            logger.debug("touch_lock('%s') fehlgeschlagen: %s", lock_name, e)

    def is_locked(self, lock_name):
        lock_dir = self._get_lock_dir()
        lock_file_path = lock_dir / f"{lock_name}.lock"

        if not lock_file_path.exists():
            return False

        if _is_lock_stale(lock_file_path):
            return False

        if HAS_FCNTL:
            try:
                with open(lock_file_path, 'r') as f:
                    try:
                        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                        return False
                    except (IOError, OSError):
                        return True
            except OSError:
                return False

        return True


_lock_manager = None
_email_sync_thread_lock = threading.Lock()


def get_lock_manager(lock_dir=None):
    """Hole die globale Lock-Manager-Instanz."""
    global _lock_manager
    if _lock_manager is None:
        _lock_manager = LockManager(lock_dir=lock_dir)
    elif lock_dir and _lock_manager.lock_dir is None:
        _lock_manager.lock_dir = lock_dir
    return _lock_manager


def acquire_email_sync_lock(timeout=0, wait_interval=0.5):
    """
    Context Manager für E-Mail-Synchronisierungs-Lock.
    Kombiniert threading.Lock (innerhalb eines Workers) und File-Lock (über Worker).
    Standard: non-blocking (timeout=0).
    """
    @contextmanager
    def _combined():
        if timeout <= 0:
            got_thread = _email_sync_thread_lock.acquire(blocking=False)
        else:
            got_thread = _email_sync_thread_lock.acquire(blocking=True, timeout=timeout)
        if not got_thread:
            yield False
            return
        try:
            file_timeout = 0 if timeout <= 0 else timeout
            with get_lock_manager().acquire_lock(
                'email_sync', timeout=file_timeout, wait_interval=wait_interval
            ) as acquired:
                yield acquired
        finally:
            _email_sync_thread_lock.release()

    return _combined()


def try_acquire_email_sync_leader(lock_dir=None):
    """
    Versucht, der einzige Auto-Sync-Leader unter Gunicorn-Workern zu werden.
    Returns HeldLock oder None.
    """
    manager = get_lock_manager(lock_dir=lock_dir)
    return manager.try_acquire_persistent('email_sync_leader')


def heartbeat_email_sync_lock():
    """Aktualisiert Heartbeat der Sync-Lock-Datei während langer Syncs."""
    get_lock_manager().touch_lock('email_sync')


def acquire_email_send_lock(timeout=0, wait_interval=0.5):
    """
    Legacy File-Lock für Versand — bevorzugt threading.Lock in email_sender nutzen.
    Non-blocking by default.
    """
    return get_lock_manager().acquire_lock(
        'email_send', timeout=timeout, wait_interval=wait_interval
    )
