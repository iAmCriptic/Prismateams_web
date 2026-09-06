"""IMAP folder listing and message sync into the local DB."""

from datetime import datetime, timedelta
import logging
import re

from sqlalchemy.exc import IntegrityError

from app import db
from app.models.email import EmailFolder, EmailMessage
from app.models.settings import SystemSettings
from app.utils.lock_manager import heartbeat_email_sync_lock
from app.blueprints.email._bp import logger
from app.blueprints.email.folder_sync import sync_emails_from_folder
from app.blueprints.email.imap_client import (
    _imap_logout,
    _is_placeholder_imap_config,
    _parse_imap_list_line,
    connect_imap,
    is_gmail_namespace_root,
    is_standard_mail_folder,
)
from app.blueprints.email.mailbox import (
    _cleanup_main_mailbox_folder_pollution,
    _find_email_folder,
    _folder_mailbox_filter,
    _is_provider_namespace_folder,
)

def sync_imap_folders(mailbox=None):
    """Sync IMAP folders from server to database."""
    mailbox_id = mailbox.id if mailbox is not None else None
    mail_conn = None
    try:
        mail_conn = connect_imap('INBOX', mailbox=mailbox)
        if not mail_conn:
            logging.error("IMAP-Verbindung fehlgeschlagen beim Synchronisieren der Ordner")
            return False, "IMAP-Verbindung fehlgeschlagen"
    except Exception as conn_error:
        logging.error(f"Fehler beim Verbinden mit IMAP für Ordner-Sync: {conn_error}")
        return False, f"IMAP-Verbindungsfehler: {str(conn_error)}"
    
    try:
        list_rows = []
        status, folders = mail_conn.list()
        if status == 'OK' and folders:
            list_rows.extend(folders)
        else:
            logging.warning("IMAP LIST (root) fehlgeschlagen oder leer: %s", status)

        # Gmail: Sonderordner liegen unter [Gmail] / [Google Mail] – explizit nachlisten
        for ns in ('[Gmail]', '[Google Mail]'):
            try:
                st, more = mail_conn.list(f'"{ns}"', '*')
                if st == 'OK' and more:
                    list_rows.extend(more)
                    logging.info("IMAP LIST unter %s: %s Einträge", ns, len(more))
            except Exception as ns_err:
                logging.debug("IMAP LIST %s übersprungen: %s", ns, ns_err)

        if not list_rows:
            return False, "Ordner-Liste konnte nicht abgerufen werden"

        # Deduplizieren nach Rohzeile
        seen_raw = set()
        unique_rows = []
        for row in list_rows:
            key = row if isinstance(row, (bytes, str)) else repr(row)
            if key in seen_raw:
                continue
            seen_raw.add(key)
            unique_rows.append(row)
        
        synced_folders = []
        skipped_folders = []
        
        logging.info(f"Processing {len(unique_rows)} folders from IMAP server (mailbox_id={mailbox_id})")
        skip_gmail_on_main = False
        if mailbox_id is None:
            try:
                from app.utils.multi_mailboxes import is_email_multi_enabled
                skip_gmail_on_main = bool(is_email_multi_enabled())
            except Exception:
                skip_gmail_on_main = False
        
        for folder_info in unique_rows:
            try:
                folder_name, separator = _parse_imap_list_line(folder_info)
                folder_str = folder_info.decode('utf-8', errors='ignore') if isinstance(folder_info, bytes) else str(folder_info)
                if not folder_name:
                    skipped_folders.append(folder_str)
                    logging.debug(f"Skipping unparsable/invalid folder line: '{folder_str}'")
                    continue

                logging.info(f"Found folder: '{folder_name}'")

                # Nur den Gmail-Root überspringen, nicht [Gmail]/Trash usw.
                if is_gmail_namespace_root(folder_name):
                    logging.debug(f"Skipping Gmail namespace root: '{folder_name}'")
                    continue

                # Bei Multi-Postfach: Gmail-/Google-Mail-Namespaces nicht ins Hauptpostfach
                if skip_gmail_on_main and _is_provider_namespace_folder(folder_name):
                    logging.debug(
                        "Skipping provider namespace folder on Hauptpostfach: %s",
                        folder_name,
                    )
                    continue
                
                is_system = is_standard_mail_folder(folder_name)
                display_name = EmailFolder.get_folder_display_name(folder_name)

                parent_folder = None
                if separator in folder_name:
                    parent_candidate = folder_name.rsplit(separator, 1)[0]
                    # Gmail-Root nicht als Parent speichern (sonst hängen Kinder an fehlendem Knoten)
                    if parent_candidate and parent_candidate != folder_name and not is_gmail_namespace_root(parent_candidate):
                        parent_folder = parent_candidate
                    else:
                        parent_folder = None

                now = datetime.utcnow()
                folder_type = 'standard' if is_system else 'custom'
                folder_payload = {
                    'name': folder_name,
                    'display_name': display_name,
                    'folder_type': folder_type,
                    'is_system': is_system,
                    'parent_folder': parent_folder,
                    'separator': separator,
                    'last_synced': now,
                    'created_at': now,
                    'mailbox_id': mailbox_id,
                }

                try:
                    existing_folder = _find_email_folder(folder_name, mailbox_id)
                    if existing_folder:
                        existing_folder.display_name = display_name
                        existing_folder.folder_type = folder_type
                        existing_folder.is_system = is_system
                        existing_folder.parent_folder = parent_folder
                        existing_folder.separator = separator
                        existing_folder.last_synced = now
                        logging.debug(f"Updated existing folder: '{folder_name}'")
                    else:
                        db.session.add(EmailFolder(**folder_payload))
                        logging.info(f"Added new folder: '{folder_name}' ({display_name})")
                    synced_folders.append(folder_name)
                except IntegrityError:
                    db.session.rollback()
                    existing_folder = _find_email_folder(folder_name, mailbox_id)
                    if existing_folder:
                        existing_folder.last_synced = datetime.utcnow()
                        synced_folders.append(folder_name)
                        logging.debug(f"Recovered folder after IntegrityError: '{folder_name}'")
                    else:
                        logging.warning(f"IntegrityError without existing folder for '{folder_name}' – retrying insert")
                        try:
                            db.session.add(EmailFolder(
                                name=folder_name,
                                display_name=display_name,
                                folder_type=folder_type,
                                is_system=is_system,
                                parent_folder=parent_folder,
                                separator=separator,
                                last_synced=datetime.utcnow(),
                                mailbox_id=mailbox_id,
                            ))
                            db.session.flush()
                            synced_folders.append(folder_name)
                            logging.info(f"Inserted folder after retry: '{folder_name}'")
                        except IntegrityError as retry_error:
                            db.session.rollback()
                            logging.error(f"Failed to insert folder '{folder_name}' after retry: {retry_error}")
                            continue
                        
            except Exception as e:
                logging.error(f"Fehler beim Verarbeiten des Ordners '{folder_str if 'folder_str' in locals() else folder_info}': {e}")
                continue
        
        logging.info(f"Synced {len(synced_folders)} folders, skipped {len(skipped_folders)} invalid folders")
        
        invalid_folder_names = ['/', '']
        for invalid_name in invalid_folder_names:
            invalid_folders = (
                EmailFolder.query.filter_by(name=invalid_name)
                .filter(_folder_mailbox_filter(mailbox_id))
                .all()
            )
            for invalid_folder in invalid_folders:
                logging.info(f"Removing invalid folder '{invalid_name}' from database")
                db.session.delete(invalid_folder)
        
        db.session.commit()
        if mailbox_id is None:
            _cleanup_main_mailbox_folder_pollution()
        
        # Schließe IMAP-Verbindung sicher
        if mail_conn:
            try:
                mail_conn.close()
            except Exception as close_error:
                logging.debug(f"Fehler beim Schließen der IMAP-Verbindung: {close_error}")
            try:
                mail_conn.logout()
            except Exception as logout_error:
                logging.debug(f"Fehler beim Logout von IMAP: {logout_error}")
        
        return True, f"{len(synced_folders)} Ordner synchronisiert"
        
    except Exception as e:
        logging.error(f"Folder sync failed: {str(e)}")
        import traceback
        logging.error(f"Traceback: {traceback.format_exc()}")
        
        # Stelle sicher, dass IMAP-Verbindung geschlossen wird
        if mail_conn:
            try:
                mail_conn.close()
            except:
                pass
            try:
                mail_conn.logout()
            except:
                pass
        
        return False, f"Ordner-Sync-Fehler: {str(e)}"


def cleanup_old_emails():
    """Lösche alte E-Mails basierend auf der konfigurierten Speicherdauer."""
    try:
        # Hole Speicherdauer aus Einstellungen
        storage_setting = SystemSettings.query.filter_by(key='email_storage_days').first()
        storage_days = 0
        if storage_setting and storage_setting.value:
            try:
                storage_days = int(storage_setting.value)
            except ValueError:
                storage_days = 0
        
        # Wenn Speicherdauer 0 ist, keine Bereinigung
        if storage_days <= 0:
            logging.debug("E-Mail-Bereinigung deaktiviert (Speicherdauer = 0)")
            return 0
        
        # Berechne das Datum, ab dem E-Mails gelöscht werden sollen
        cutoff_date = datetime.utcnow() - timedelta(days=storage_days)
        
        # Finde E-Mails, die älter als die Speicherdauer sind
        old_emails = EmailMessage.query.filter(
            EmailMessage.created_at < cutoff_date
        ).all()
        
        deleted_count = 0
        for email in old_emails:
            try:
                # Lösche auch alle Anhänge (wird durch cascade automatisch gemacht)
                db.session.delete(email)
                deleted_count += 1
            except Exception as e:
                logging.error(f"Fehler beim Löschen der E-Mail {email.id}: {e}")
                continue
        
        if deleted_count > 0:
            db.session.commit()
            logging.info(f"E-Mail-Bereinigung: {deleted_count} E-Mails gelöscht (älter als {storage_days} Tage)")
        else:
            logging.debug(f"E-Mail-Bereinigung: Keine E-Mails zum Löschen gefunden (älter als {storage_days} Tage)")
        
        return deleted_count
        
    except Exception as e:
        logging.error(f"Fehler bei der E-Mail-Bereinigung: {e}", exc_info=True)
        db.session.rollback()
        return 0


def sync_emails_from_server(mailbox=None):
    """Sync emails from IMAP server to database with folder support.

    mailbox=None → Hauptpostfach (App-Config).
    """
    label = f"mailbox#{mailbox.id}" if mailbox is not None else "main"
    logger.info(f"E-Mail-Synchronisation wird gestartet ({label})")
    
    shared_conn = None
    try:
        from app.utils.multi_mailboxes import get_mailbox_imap_config
        cfg = get_mailbox_imap_config(mailbox)
        imap_server = cfg.get('server')
        username = cfg.get('user')
        password = cfg.get('password')
        auth_type = (getattr(mailbox, 'auth_type', None) or 'password') if mailbox is not None else 'password'
        # OAuth-Postfächer haben kein IMAP-Passwort – Platzhalter-Check nur für Passwort-Auth
        if auth_type != 'oauth' and _is_placeholder_imap_config(imap_server, username, password):
            message = "IMAP ist nicht konfiguriert (Platzhalterwerte erkannt) - Synchronisation übersprungen"
            logger.warning(message)
            return False, message
        if not imap_server or not username:
            message = "IMAP-Konfiguration unvollständig (Server/Benutzer fehlen)"
            logging.warning(message)
            return False, message

        # Synchronisiere zuerst die Ordner-Liste
        folder_success, folder_message = sync_imap_folders(mailbox=mailbox)
        if not folder_success:
            logging.warning(f"Ordner-Sync-Warnung: {folder_message}")
            # Weiter mit Standard-Ordnern, auch wenn Ordner-Sync fehlschlägt
            logging.info("Verwende Standard-Ordner als Fallback")
        
        mailbox_id = mailbox.id if mailbox is not None else None
        # Hole Ordner aus Datenbank
        folder_rows = (
            db.session.query(EmailFolder.name, EmailFolder.display_name)
            .filter(_folder_mailbox_filter(mailbox_id))
            .all()
        )
        if not folder_rows:
            # Fallback: Verwende Standard-Ordner
            folder_rows = [('INBOX', 'Posteingang')]
            logging.info("Keine Ordner in Datenbank gefunden, verwende Standard-Ordner")
        
        logging.info(f"Syncing emails from {len(folder_rows)} folders: {[name for (name, _) in folder_rows]}")
        
        # Eine IMAP-Session für alle Ordner (weniger Logins, schneller, Provider-freundlicher)
        shared_conn = connect_imap('INBOX', mailbox=mailbox)
        if not shared_conn:
            message = "IMAP-Verbindung fehlgeschlagen - Synchronisation abgebrochen"
            logging.error(message)
            return False, message

        total_synced = 0
        total_new = 0
        folder_results = []
        successful_folders = 0
        failed_folders = 0
        
        for (folder_name, display_name) in folder_rows:
            try:
                heartbeat_email_sync_lock()
                logging.info(f"Syncing folder: '{folder_name}' ({display_name})")
                success, message = sync_emails_from_folder(
                    folder_name, mail_conn=shared_conn, mailbox=mailbox
                )
                if success:
                    successful_folders += 1
                    import re
                    # Suche nach verschiedenen Mustern für Anzahl
                    match = re.search(r'(\d+)\s+(neu|new)', message, re.IGNORECASE)
                    if match:
                        count = int(match.group(1))
                        total_new += count
                    # Auch nach "E-Mails" suchen
                    match = re.search(r'(\d+)\s+E-Mails', message, re.IGNORECASE)
                    if match:
                        count = int(match.group(1))
                        total_synced += count
                    folder_results.append(f"{display_name}: {message}")
                    logging.info(f"✓ Ordner '{folder_name}' erfolgreich synchronisiert: {message}")
                else:
                    failed_folders += 1
                    logging.warning(f"✗ Ordner '{folder_name}' konnte nicht synchronisiert werden: {message}")
                    folder_results.append(f"{display_name}: Fehler - {message}")
            except Exception as folder_error:
                failed_folders += 1
                logging.error(f"Fehler beim Synchronisieren des Ordners '{folder_name}': {folder_error}")
                import traceback
                logging.error(f"Traceback: {traceback.format_exc()}")
                folder_results.append(f"{display_name}: Fehler - {str(folder_error)}")
                continue
        
        logger.info(f"E-Mail-Synchronisation wurde beendet: {successful_folders} Ordner erfolgreich, {failed_folders} Ordner fehlgeschlagen")
        
        # Erstelle Ergebnis-Meldung
        if total_new > 0:
            result_msg = f"{total_new} neue E-Mails aus {successful_folders} Ordnern synchronisiert"
        elif total_synced > 0:
            result_msg = f"{total_synced} E-Mails aus {successful_folders} Ordnern synchronisiert"
        elif successful_folders > 0:
            result_msg = f"{successful_folders} Ordner synchronisiert (keine neuen E-Mails)"
        else:
            result_msg = "Keine E-Mails synchronisiert"
        
        if failed_folders > 0:
            result_msg += f" ({failed_folders} Ordner fehlgeschlagen)"
        
        return True, result_msg
    except Exception as e:
        logging.error(f"Kritischer Fehler in sync_emails_from_server: {e}")
        import traceback
        logging.error(f"Traceback: {traceback.format_exc()}")
        logger.error(f"E-Mail-Synchronisation Fehler: {e}", exc_info=True)
        return False, f"Kritischer Fehler: {str(e)}"
    finally:
        if shared_conn is not None:
            _imap_logout(shared_conn)


def sync_all_configured_mailboxes():
    """Sync Hauptpostfach + alle aktiven Multi-Postfächer (wenn Multi aktiv)."""
    results = []
    ok_main, msg_main = sync_emails_from_server(mailbox=None)
    results.append(('main', ok_main, msg_main))

    try:
        from app.utils.multi_mailboxes import get_active_sync_mailboxes, is_email_multi_enabled
        if is_email_multi_enabled():
            for mb in get_active_sync_mailboxes():
                try:
                    ok, msg = sync_emails_from_server(mailbox=mb)
                    results.append((f'mailbox#{mb.id}', ok, msg))
                except Exception as exc:
                    logging.error(f"Multi-Postfach-Sync fehlgeschlagen ({mb.id}): {exc}")
                    results.append((f'mailbox#{mb.id}', False, str(exc)))
    except Exception as exc:
        logging.error(f"Multi-Postfach-Sync Setup-Fehler: {exc}")

    any_ok = any(r[1] for r in results)
    summary = '; '.join(f'{name}: {msg}' for name, _, msg in results)
    return any_ok, summary
