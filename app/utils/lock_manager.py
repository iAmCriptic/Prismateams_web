"""
Lock Manager für Single-Worker-Tasks
Stellt sicher, dass bestimmte Aufgaben nur von einem Gunicorn-Worker gleichzeitig ausgeführt werden.
Verwendet File-based Locking, das über Worker-Grenzen hinweg funktioniert.
"""

import os
import logging
import time
from contextlib import contextmanager
from pathlib import Path
from flask import current_app

# Plattform-spezifische Lock-Implementierung
import platform
IS_WINDOWS = platform.system() == 'Windows'

try:
    import fcntl  # Unix/Linux
    HAS_FCNTL = True
except ImportError:
    HAS_FCNTL = False

logger = logging.getLogger(__name__)


class LockManager:
    """Verwaltet File-based Locks für Single-Worker-Tasks."""
    
    def __init__(self, lock_dir=None):
        """
        Initialisiere den Lock Manager.
        
        Args:
            lock_dir: Verzeichnis für Lock-Dateien (optional, wird automatisch bestimmt)
        """
        self.lock_dir = lock_dir
        self._locks = {}
    
    def _get_lock_dir(self):
        """Bestimme das Verzeichnis für Lock-Dateien."""
        if self.lock_dir:
            return Path(self.lock_dir)
        
        # Versuche instance-Verzeichnis zu verwenden
        try:
            if current_app:
                instance_path = current_app.instance_path
                lock_dir = Path(instance_path) / 'locks'
                lock_dir.mkdir(parents=True, exist_ok=True)
                return lock_dir
        except:
            pass
        
        # Fallback: Verwende temporäres Verzeichnis
        import tempfile
        lock_dir = Path(tempfile.gettempdir()) / 'prismateams_locks'
        lock_dir.mkdir(parents=True, exist_ok=True)
        return lock_dir
    
    @contextmanager
    def acquire_lock(self, lock_name, timeout=300, wait_interval=5):
        """
        Erwerbe einen Lock für eine bestimmte Aufgabe.
        
        Args:
            lock_name: Name des Locks (z.B. 'email_sync', 'email_send')
            timeout: Maximale Wartezeit in Sekunden (Standard: 5 Minuten)
            wait_interval: Wartezeit zwischen Versuchen in Sekunden (Standard: 5 Sekunden)
        
        Yields:
            True wenn Lock erfolgreich erworben wurde, False sonst
        
        Example:
            with lock_manager.acquire_lock('email_sync') as acquired:
                if acquired:
                    # Führe Aufgabe aus
                    sync_emails()
        """
        lock_dir = self._get_lock_dir()
        lock_file_path = lock_dir / f"{lock_name}.lock"
        
        lock_file = None
        acquired = False
        
        try:
            # Versuche Lock zu erwerben
            start_time = time.time()
            
            while time.time() - start_time < timeout:
                try:
                    if HAS_FCNTL:
                        # Unix/Linux: Verwende fcntl für atomares Locking
                        lock_file = open(lock_file_path, 'a')
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        # Lock erfolgreich erworben
                        acquired = True
                        
                        # Schreibe PID und Timestamp in Lock-Datei
                        lock_file.seek(0)
                        lock_file.truncate()
                        lock_file.write(f"PID: {os.getpid()}\n")
                        lock_file.write(f"Timestamp: {time.time()}\n")
                        lock_file.flush()
                        
                        logger.info(f"Lock '{lock_name}' erfolgreich erworben (PID: {os.getpid()})")
                        break
                    else:
                        # Windows/Fallback: Verwende atomare Dateierstellung
                        # Versuche Lock-Datei exklusiv zu erstellen
                        try:
                            # Prüfe ob Lock-Datei existiert und noch aktiv ist
                            if lock_file_path.exists():
                                file_age = time.time() - lock_file_path.stat().st_mtime
                                # Wenn Datei älter als 5 Minuten, könnte sie verwaist sein
                                if file_age < 300:  # 5 Minuten
                                    # Versuche PID aus Datei zu lesen und zu prüfen ob Prozess noch läuft
                                    try:
                                        with open(lock_file_path, 'r') as f:
                                            content = f.read()
                                            if 'PID:' in content:
                                                pid_line = [l for l in content.split('\n') if l.startswith('PID:')]
                                                if pid_line:
                                                    pid = int(pid_line[0].split(':')[1].strip())
                                                    # Prüfe ob Prozess noch läuft (Windows)
                                                    if IS_WINDOWS:
                                                        import subprocess
                                                        try:
                                                            subprocess.check_output(['tasklist', '/FI', f'PID eq {pid}'], 
                                                                                    stderr=subprocess.DEVNULL)
                                                            # Prozess läuft noch, Lock ist aktiv
                                                            raise IOError("Lock file exists and process is running")
                                                        except (subprocess.CalledProcessError, FileNotFoundError):
                                                            # Prozess läuft nicht mehr, Lock ist verwaist
                                                            pass
                                                    else:
                                                        # Unix: Prüfe mit kill -0
                                                        try:
                                                            os.kill(pid, 0)
                                                            # Prozess läuft noch
                                                            raise IOError("Lock file exists and process is running")
                                                        except (OSError, ProcessLookupError):
                                                            # Prozess läuft nicht mehr
                                                            pass
                                    except:
                                        pass
                            
                            # Versuche Lock-Datei zu erstellen/öffnen
                            lock_file = open(lock_file_path, 'x')  # 'x' = exklusives Erstellen
                            # Lock erfolgreich erworben
                            acquired = True
                            
                            # Schreibe PID und Timestamp in Lock-Datei
                            lock_file.write(f"PID: {os.getpid()}\n")
                            lock_file.write(f"Timestamp: {time.time()}\n")
                            lock_file.flush()
                            
                            logger.info(f"Lock '{lock_name}' erfolgreich erworben (PID: {os.getpid()})")
                            break
                        except FileExistsError:
                            # Datei existiert bereits, Lock ist aktiv
                            if lock_file:
                                lock_file.close()
                                lock_file = None
                            raise IOError("Lock file already exists")
                    
                except (IOError, OSError, FileExistsError) as e:
                    # Lock bereits von anderem Prozess gehalten
                    if lock_file:
                        lock_file.close()
                        lock_file = None
                    
                    elapsed = time.time() - start_time
                    logger.debug(f"Lock '{lock_name}' nicht verfügbar, warte... (bereits {elapsed:.1f}s gewartet)")
                    time.sleep(wait_interval)
            
            if not acquired:
                logger.warning(f"Konnte Lock '{lock_name}' nicht innerhalb von {timeout}s erwerben")
            
            yield acquired
            
        except Exception as e:
            logger.error(f"Fehler beim Erwerben des Locks '{lock_name}': {e}", exc_info=True)
            yield False
            
        finally:
            # Gib Lock frei
            if lock_file and acquired:
                try:
                    if HAS_FCNTL:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                    lock_file.close()
                    
                    # Lösche Lock-Datei (nur wenn wir sie erstellt haben)
                    try:
                        if lock_file_path.exists():
                            lock_file_path.unlink()
                    except Exception as e:
                        logger.warning(f"Konnte Lock-Datei '{lock_file_path}' nicht löschen: {e}")
                    
                    logger.info(f"Lock '{lock_name}' freigegeben")
                except Exception as e:
                    logger.error(f"Fehler beim Freigeben des Locks '{lock_name}': {e}")
    
    def is_locked(self, lock_name):
        """
        Prüfe, ob ein Lock aktuell aktiv ist.
        
        Args:
            lock_name: Name des Locks
        
        Returns:
            True wenn Lock aktiv ist, False sonst
        """
        lock_dir = self._get_lock_dir()
        lock_file_path = lock_dir / f"{lock_name}.lock"
        
        if not lock_file_path.exists():
            return False
        
        if not lock_file_path.exists():
            return False
        
        try:
            if HAS_FCNTL:
                # Unix/Linux: Versuche non-blocking Lock zu erwerben
                with open(lock_file_path, 'r') as f:
                    try:
                        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        # Wenn erfolgreich, war Lock nicht aktiv
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                        return False
                    except (IOError, OSError):
                        # Lock ist aktiv
                        return True
            else:
                # Windows/Fallback: Prüfe Datei-Alter und Prozess-Status
                file_age = time.time() - lock_file_path.stat().st_mtime
                if file_age >= 300:  # Älter als 5 Minuten
                    return False
                
                # Prüfe ob Prozess noch läuft
                try:
                    with open(lock_file_path, 'r') as f:
                        content = f.read()
                        if 'PID:' in content:
                            pid_line = [l for l in content.split('\n') if l.startswith('PID:')]
                            if pid_line:
                                pid = int(pid_line[0].split(':')[1].strip())
                                if IS_WINDOWS:
                                    import subprocess
                                    try:
                                        subprocess.check_output(['tasklist', '/FI', f'PID eq {pid}'], 
                                                                stderr=subprocess.DEVNULL)
                                        return True  # Prozess läuft noch
                                    except (subprocess.CalledProcessError, FileNotFoundError):
                                        return False  # Prozess läuft nicht mehr
                                else:
                                    try:
                                        os.kill(pid, 0)
                                        return True  # Prozess läuft noch
                                    except (OSError, ProcessLookupError):
                                        return False  # Prozess läuft nicht mehr
                except:
                    pass
                
                # Wenn Datei jünger als 5 Minuten, annehmen dass Lock aktiv ist
                return True
        except (IOError, OSError):
            # Fehler beim Prüfen, annehmen dass Lock nicht aktiv ist
            return False


# Globale Instanz
_lock_manager = None


def get_lock_manager():
    """Hole die globale Lock-Manager-Instanz."""
    global _lock_manager
    if _lock_manager is None:
        _lock_manager = LockManager()
    return _lock_manager


def acquire_email_sync_lock(timeout=300):
    """
    Context Manager für E-Mail-Synchronisierungs-Lock.
    
    Args:
        timeout: Maximale Wartezeit in Sekunden
    
    Example:
        with acquire_email_sync_lock() as acquired:
            if acquired:
                sync_emails_from_server()
    """
    return get_lock_manager().acquire_lock('email_sync', timeout=timeout)


def acquire_email_send_lock(timeout=60):
    """
    Context Manager für E-Mail-Versand-Lock.
    
    Args:
        timeout: Maximale Wartezeit in Sekunden
    
    Example:
        with acquire_email_send_lock() as acquired:
            if acquired:
                mail.send(msg)
    """
    return get_lock_manager().acquire_lock('email_send', timeout=timeout)

