import os
import secrets
import string
import logging
import base64
from datetime import datetime, timedelta
from flask import render_template, current_app, url_for
from flask_mail import Message
from app import mail
from app.models.user import User
from app.utils.lock_manager import acquire_email_send_lock


def send_email_with_lock(msg, timeout=60):
    """
    Sendet eine E-Mail mit Lock-Schutz, um sicherzustellen, dass nur ein Worker gleichzeitig sendet.
    
    Args:
        msg: Flask-Mail Message-Objekt
        timeout: Maximale Wartezeit für Lock in Sekunden (Standard: 60)
    
    Returns:
        True wenn erfolgreich gesendet, False sonst
    
    Raises:
        Exception: Wenn E-Mail-Versand fehlschlägt
    """
    # KRITISCH: Flask-Mail erstellt msg.msg erst beim Senden (in mail.send())
    # Wir müssen das Logo direkt VOR mail.send() mit CID markieren
    # Dazu müssen wir msg._message aufrufen, um msg.msg zu erstellen
    
    # Stelle sicher, dass msg.msg erstellt wurde
    # Flask-Mail erstellt msg.msg erst beim ersten Zugriff oder beim Senden
    # Wir müssen es explizit erstellen, um es vorher manipulieren zu können
    try:
        # Versuche _message() zu verwenden (Flask-Mail's interne Methode)
        if hasattr(msg, '_message'):
            _message = msg._message()
        # Fallback: Zugriff auf msg.msg erstellt es möglicherweise
        elif hasattr(msg, 'msg'):
            # Versuche msg.msg zu erstellen durch Zugriff
            try:
                _ = msg.msg.get_content_type() if msg.msg else None
            except AttributeError:
                # msg.msg ist None - Flask-Mail wird es beim Senden erstellen
                pass
    except Exception as e:
        logging.warning(f"Fehler beim Erstellen von msg.msg: {e}")
        # Wenn das fehlschlägt, wird Flask-Mail msg.msg beim Senden erstellen
        # Wir versuchen dann in einem Patch direkt vor mail.send()
    
    # Suche nach Logo-Anhang und markiere ihn mit CID
    if hasattr(msg, 'msg') and msg.msg:
        if hasattr(msg.msg, 'get_payload'):
            parts = msg.msg.get_payload()
            if isinstance(parts, list):
                # Suche nach logo.png, logo.jpg, logo.gif
                logo_filenames = ['logo.png', 'logo.jpg', 'logo.jpeg', 'logo.gif']
                for part in parts:
                    if (hasattr(part, 'get_content_type') and 
                        part.get_content_type().startswith('image/')):
                        disp = part.get('Content-Disposition', '')
                        # Prüfe, ob es ein Logo-Anhang ist
                        is_logo = any(logo_fn in disp for logo_fn in logo_filenames)
                        if is_logo:
                            # Logo-Anhang gefunden - setze CID und inline
                            if not part.get('Content-ID'):
                                part.add_header('Content-ID', '<portal_logo>')
                            # Stelle sicher, dass es inline ist
                            if 'attachment' in disp and 'inline' not in disp:
                                # Extrahiere filename aus alter disposition
                                import re
                                filename_match = re.search(r'filename="?([^"]+)"?', disp)
                                filename = filename_match.group(1) if filename_match else 'logo.png'
                                try:
                                    part.replace_header('Content-Disposition', f'inline; filename="{filename}"')
                                except:
                                    # Wenn replace fehlschlägt, entferne alte und füge neue hinzu
                                    del part['Content-Disposition']
                                    part.add_header('Content-Disposition', f'inline; filename="{filename}"')
                            elif not disp:
                                part.add_header('Content-Disposition', 'inline; filename="logo.png"')
                            
                            # #region agent log
                            try:
                                import json
                                with open(r'c:\Users\ermat\Documents\GitHub\Prismateams_web\.cursor\debug.log', 'a', encoding='utf-8') as f:
                                    f.write(json.dumps({"location":"email_sender.py:55","message":"Logo-Anhang mit CID markiert VOR mail.send()","data":{"cid":part.get('Content-ID'),"disposition":part.get('Content-Disposition'),"content_type":part.get_content_type()},"timestamp":int(__import__('time').time()*1000),"sessionId":"debug-session","runId":"run1","hypothesisId":"H"}) + '\n')
                            except: pass
                            # #endregion
                            logging.info(f"Logo-Anhang mit CID markiert: {part.get('Content-ID')}, Disposition: {part.get('Content-Disposition')}")
                            break
    
    # #region agent log
    try:
        import json
        msg_content_type = msg.msg.get_content_type() if hasattr(msg, 'msg') and hasattr(msg.msg, 'get_content_type') else 'N/A'
        msg_parts = msg.msg.get_payload() if hasattr(msg, 'msg') and hasattr(msg.msg, 'get_payload') else []
        logo_count = sum(1 for p in msg_parts if isinstance(msg_parts, list) and hasattr(p, 'get_content_type') and p.get_content_type().startswith('image/') and p.get('Content-ID', '').find('portal_logo') != -1)
        with open(r'c:\Users\ermat\Documents\GitHub\Prismateams_web\.cursor\debug.log', 'a', encoding='utf-8') as f:
            f.write(json.dumps({"location":"email_sender.py:30","message":"VOR mail.send() - Message-Struktur","data":{"content_type":msg_content_type,"total_parts":len(msg_parts) if isinstance(msg_parts, list) else 0,"logo_count":logo_count},"timestamp":int(__import__('time').time()*1000),"sessionId":"debug-session","runId":"run1","hypothesisId":"E"}) + '\n')
    except Exception as e:
        try:
            import json
            with open(r'c:\Users\ermat\Documents\GitHub\Prismateams_web\.cursor\debug.log', 'a', encoding='utf-8') as f:
                f.write(json.dumps({"location":"email_sender.py:30","message":"FEHLER beim Loggen vor mail.send()","data":{"error":str(e)},"timestamp":int(__import__('time').time()*1000),"sessionId":"debug-session","runId":"run1","hypothesisId":"E"}) + '\n')
        except: pass
    # #endregion
    
    # KRITISCHER PUNKT: Flask-Mail erstellt msg.msg erst INNERHALB von mail.send()
    # Wir müssen die Message-Struktur NACH ihrer Erstellung, aber VOR dem tatsächlichen Senden manipulieren
    # Lösung: Wrapper um mail.send(), der die Message-Struktur manipuliert
    def send_with_logo_fix():
        """Sende E-Mail und stelle sicher, dass Logo mit CID markiert ist"""
        # Flask-Mail's send() erstellt msg.msg intern
        # Wir müssen einen Hook finden, um danach, aber vor dem tatsächlichen Senden zu manipulieren
        
        # Versuche 1: Manuell msg.msg erstellen, bevor mail.send() aufgerufen wird
        try:
            # Flask-Mail's Message._message() erstellt die Message-Struktur
            if hasattr(msg, '_message'):
                msg.msg = msg._message()
        except Exception as e:
            logging.warning(f"Fehler beim Erstellen von msg.msg via _message(): {e}")
        
        # Jetzt sollte msg.msg existieren - manipuliere es
        if hasattr(msg, 'msg') and msg.msg:
            if hasattr(msg.msg, 'get_payload'):
                parts = msg.msg.get_payload()
                if isinstance(parts, list):
                    logo_filenames = ['logo.png', 'logo.jpg', 'logo.jpeg', 'logo.gif']
                    for part in parts:
                        if (hasattr(part, 'get_content_type') and 
                            part.get_content_type().startswith('image/')):
                            disp = part.get('Content-Disposition', '')
                            is_logo = any(logo_fn in disp for logo_fn in logo_filenames)
                            if is_logo:
                                # Setze CID
                                if not part.get('Content-ID'):
                                    part.add_header('Content-ID', '<portal_logo>')
                                # Stelle sicher, dass es inline ist
                                if 'attachment' in disp and 'inline' not in disp:
                                    import re
                                    filename_match = re.search(r'filename="?([^"]+)"?', disp)
                                    filename = filename_match.group(1) if filename_match else 'logo.png'
                                    try:
                                        part.replace_header('Content-Disposition', f'inline; filename="{filename}"')
                                    except:
                                        del part['Content-Disposition']
                                        part.add_header('Content-Disposition', f'inline; filename="{filename}"')
                                elif not disp:
                                    part.add_header('Content-Disposition', 'inline; filename="logo.png"')
                                
                                # #region agent log
                                try:
                                    import json
                                    with open(r'c:\Users\ermat\Documents\GitHub\Prismateams_web\.cursor\debug.log', 'a', encoding='utf-8') as f:
                                        f.write(json.dumps({"location":"email_sender.py:120","message":"Logo mit CID markiert in send_with_logo_fix()","data":{"cid":part.get('Content-ID'),"disposition":part.get('Content-Disposition'),"content_type":part.get_content_type()},"timestamp":int(__import__('time').time()*1000),"sessionId":"debug-session","runId":"run1","hypothesisId":"I"}) + '\n')
                                except: pass
                                # #endregion
                                logging.info(f"Logo mit CID markiert in send_with_logo_fix(): {part.get('Content-ID')}")
                                break
        
        # Sende die E-Mail - Flask-Mail wird msg.msg verwenden (oder neu erstellen)
        # Das Problem ist, dass Flask-Mail möglicherweise msg.msg neu erstellt
        # Wir müssen sicherstellen, dass unsere Änderungen erhalten bleiben
        
        # Versuche 2: Patch Flask-Mail's send() um unsere Änderungen zu bewahren
        # Oder: Verwende mail's connection direkt und sende die manipulierten msg.msg
        try:
            # Hole die Connection und sende direkt
            with mail.connect() as conn:
                conn.send(msg)
        except Exception as e:
            logging.error(f"Fehler beim Senden mit Connection: {e}")
            # Fallback: Normale mail.send()
            mail.send(msg)
    
    with acquire_email_send_lock(timeout=timeout) as acquired:
        if acquired:
            # Erstelle msg.msg explizit, bevor mail.send() aufgerufen wird
            if not hasattr(msg, 'msg') or not msg.msg:
                try:
                    if hasattr(msg, '_message'):
                        msg.msg = msg._message()
                except Exception as e:
                    logging.warning(f"Fehler beim Erstellen von msg.msg via _message(): {e}")
            
            # Manipuliere msg.msg, wenn es existiert
            if hasattr(msg, 'msg') and msg.msg:
                # KRITISCH: Für inline images mit CID brauchen wir multipart/related, nicht multipart/mixed
                current_content_type = msg.msg.get_content_type() if hasattr(msg.msg, 'get_content_type') else None
                
                # #region agent log
                try:
                    import json
                    with open(r'c:\Users\ermat\Documents\GitHub\Prismateams_web\.cursor\debug.log', 'a', encoding='utf-8') as f:
                        f.write(json.dumps({"location":"email_sender.py:115","message":"Message-Struktur VOR Manipulation","data":{"content_type":current_content_type},"timestamp":int(__import__('time').time()*1000),"sessionId":"debug-session","runId":"run1","hypothesisId":"K"}) + '\n')
                except: pass
                # #endregion
                
                # KRITISCH: Wenn multipart/mixed, müssen wir auf multipart/related umstellen
                # Aber: Wenn es normale Anhänge gibt, müssen wir verschachteln:
                # multipart/mixed (äußere) -> multipart/related (innere, mit Logo)
                if current_content_type == 'multipart/mixed':
                    from email.mime.multipart import MIMEMultipart
                    from email.mime.text import MIMEText
                    from email.header import Header
                    
                    # Erstelle neue multipart/related Struktur
                    # WICHTIG: multipart/related benötigt einen "root" Part (meist multipart/alternative)
                    # und dann related resources (Bilder mit CID)
                    new_msg = MIMEMultipart('related')
                    # Setze Content-Type mit Start-Parameter für bessere Kompatibilität
                    new_msg.set_type('multipart/related')
                    
                    # Kopiere alle Header
                    for key, value in msg.msg.items():
                        if key.lower() not in ['content-type', 'mime-version']:
                            new_msg[key] = value
                    
                    # Extrahiere alle Parts aus der alten Struktur
                    old_parts = msg.msg.get_payload() if hasattr(msg.msg, 'get_payload') else []
                    if isinstance(old_parts, list):
                        # Finde multipart/alternative (Text + HTML)
                        alternative_part = None
                        logo_part = None
                        other_attachments = []
                        
                        # #region agent log
                        try:
                            import json
                            parts_info = []
                            for i, p in enumerate(old_parts):
                                if hasattr(p, 'get_content_type'):
                                    parts_info.append({
                                        "index": i,
                                        "content_type": p.get_content_type(),
                                        "disposition": p.get('Content-Disposition', '') if hasattr(p, 'get') else '',
                                        "content_id": p.get('Content-ID', '') if hasattr(p, 'get') else ''
                                    })
                            with open(r'c:\Users\ermat\Documents\GitHub\Prismateams_web\.cursor\debug.log', 'a', encoding='utf-8') as f:
                                f.write(json.dumps({"location":"email_sender.py:230","message":"Suche nach Logo in Parts","data":{"total_parts":len(old_parts),"parts_info":parts_info},"timestamp":int(__import__('time').time()*1000),"sessionId":"debug-session","runId":"run1","hypothesisId":"C"}) + '\n')
                        except: pass
                        # #endregion
                        
                        for part in old_parts:
                            if hasattr(part, 'get_content_type'):
                                ct = part.get_content_type()
                                if ct == 'multipart/alternative':
                                    alternative_part = part
                                elif ct.startswith('image/'):
                                    # Suche nach Logo - prüfe sowohl Content-Disposition als auch Dateinamen
                                    disp = part.get('Content-Disposition', '')
                                    # Prüfe, ob es ein Logo ist (nach Dateinamen in Content-Disposition)
                                    is_logo = any(logo_fn in disp.lower() for logo_fn in ['logo.png', 'logo.jpg', 'logo.jpeg', 'logo.gif'])
                                    
                                    # #region agent log
                                    if is_logo:
                                        try:
                                            import json
                                            with open(r'c:\Users\ermat\Documents\GitHub\Prismateams_web\.cursor\debug.log', 'a', encoding='utf-8') as f:
                                                f.write(json.dumps({"location":"email_sender.py:248","message":"Logo-Teil GEFUNDEN","data":{"content_type":ct,"disposition":disp,"content_id":part.get('Content-ID', '') if hasattr(part, 'get') else ''},"timestamp":int(__import__('time').time()*1000),"sessionId":"debug-session","runId":"run1","hypothesisId":"C"}) + '\n')
                                        except: pass
                                    # #endregion
                                    
                                    if is_logo and not logo_part:
                                        logo_part = part
                                    else:
                                        other_attachments.append(part)
                                else:
                                    other_attachments.append(part)
                        
                        # KRITISCH: Für multipart/related muss die Struktur korrekt sein:
                        # 1. Root-Part (multipart/alternative mit text/plain und text/html)
                        # 2. Inline-Ressourcen (Bilder mit CID) - müssen NACH dem Root kommen
                        # 3. Andere Anhänge müssen in einen separaten multipart/mixed eingebettet werden
                        
                        # Füge alternative (Text + HTML) als ROOT hinzu - ZUERST!
                        if alternative_part:
                            new_msg.attach(alternative_part)
                        
                        # Füge Logo hinzu (mit CID) - NACH dem Root
                        if logo_part:
                            # #region agent log
                            try:
                                import json
                                old_logo_cid = logo_part.get('Content-ID', '')
                                old_logo_disp = logo_part.get('Content-Disposition', '')
                                with open(r'c:\Users\ermat\Documents\GitHub\Prismateams_web\.cursor\debug.log', 'a', encoding='utf-8') as f:
                                    f.write(json.dumps({"location":"email_sender.py:242","message":"Logo-Teil gefunden beim Umstellen auf multipart/related","data":{"old_cid":old_logo_cid,"old_disposition":old_logo_disp},"timestamp":int(__import__('time').time()*1000),"sessionId":"debug-session","runId":"run1","hypothesisId":"A"}) + '\n')
                            except: pass
                            # #endregion
                            if not logo_part.get('Content-ID'):
                                # WICHTIG: Content-ID muss exakt mit der CID-Referenz im HTML übereinstimmen
                                # Im HTML: cid:portal_logo -> Im Attachment: <portal_logo>
                                logo_part.add_header('Content-ID', '<portal_logo>')
                                # #region agent log
                                try:
                                    import json
                                    final_cid = logo_part.get('Content-ID', '')
                                    with open(r'c:\Users\ermat\Documents\GitHub\Prismateams_web\.cursor\debug.log', 'a', encoding='utf-8') as f:
                                        f.write(json.dumps({"location":"email_sender.py:295","message":"Content-ID auf Logo gesetzt","data":{"content_id":final_cid,"expected_html_ref":"cid:portal_logo"},"timestamp":int(__import__('time').time()*1000),"sessionId":"debug-session","runId":"run1","hypothesisId":"D"}) + '\n')
                                except: pass
                                # #endregion
                            disp = logo_part.get('Content-Disposition', '')
                            if 'attachment' in disp and 'inline' not in disp:
                                import re
                                filename_match = re.search(r'filename="?([^"]+)"?', disp)
                                filename = filename_match.group(1) if filename_match else 'logo.png'
                                try:
                                    logo_part.replace_header('Content-Disposition', f'inline; filename="{filename}"')
                                except:
                                    del logo_part['Content-Disposition']
                                    logo_part.add_header('Content-Disposition', f'inline; filename="{filename}"')
                            elif not disp:
                                logo_part.add_header('Content-Disposition', 'inline; filename="logo.png"')
                            # #region agent log
                            try:
                                import json
                                new_logo_cid = logo_part.get('Content-ID', '')
                                new_logo_disp = logo_part.get('Content-Disposition', '')
                                with open(r'c:\Users\ermat\Documents\GitHub\Prismateams_web\.cursor\debug.log', 'a', encoding='utf-8') as f:
                                    f.write(json.dumps({"location":"email_sender.py:258","message":"Logo-Teil mit CID/Disposition markiert und zu multipart/related hinzugefügt","data":{"new_cid":new_logo_cid,"new_disposition":new_logo_disp},"timestamp":int(__import__('time').time()*1000),"sessionId":"debug-session","runId":"run1","hypothesisId":"A"}) + '\n')
                            except: pass
                            # #endregion
                            new_msg.attach(logo_part)
                            
                            # WICHTIG: Füge Logo ZUSÄTZLICH als attachment hinzu (für separaten Anhang)
                            # Lade Logo-Daten erneut für den Anhang (separate Instanz)
                            from email.mime.image import MIMEImage
                            
                            # Lade Logo-Daten erneut für den Anhang
                            logo_data_for_attachment, logo_mime_type_att, logo_filename_att = get_logo_data()
                            if logo_data_for_attachment and logo_mime_type_att:
                                image_type_att = logo_mime_type_att.split('/')[1] if '/' in logo_mime_type_att else 'png'
                                logo_attachment = MIMEImage(logo_data_for_attachment, image_type_att)
                                
                                # Setze Dateiname für Anhang
                                if image_type_att == 'jpeg' or image_type_att == 'jpg':
                                    attachment_filename_att = 'logo.jpg'
                                elif image_type_att == 'png':
                                    attachment_filename_att = 'logo.png'
                                elif image_type_att == 'gif':
                                    attachment_filename_att = 'logo.gif'
                                else:
                                    attachment_filename_att = 'logo.png'
                                
                                # WICHTIG: KEINE Content-ID für den Anhang (nur für inline)
                                # Setze attachment disposition
                                logo_attachment.add_header('Content-Disposition', 'attachment', filename=attachment_filename_att)
                                
                                # Speichere für später (wird zur multipart/mixed Struktur hinzugefügt)
                                logo_attachment_part = logo_attachment
                                
                                # #region agent log
                                try:
                                    import json
                                    with open(r'c:\Users\ermat\Documents\GitHub\Prismateams_web\.cursor\debug.log', 'a', encoding='utf-8') as f:
                                        f.write(json.dumps({"location":"email_sender.py:330","message":"Logo als Attachment erstellt (zusätzlich zum inline)","data":{"filename":attachment_filename_att,"has_cid":False},"timestamp":int(__import__('time').time()*1000),"sessionId":"debug-session","runId":"run1","hypothesisId":"F"}) + '\n')
                                except: pass
                                # #endregion
                            else:
                                logo_attachment_part = None
                        else:
                            # #region agent log
                            try:
                                import json
                                with open(r'c:\Users\ermat\Documents\GitHub\Prismateams_web\.cursor\debug.log', 'a', encoding='utf-8') as f:
                                    f.write(json.dumps({"location":"email_sender.py:258","message":"Logo-Teil NICHT gefunden beim Umstellen auf multipart/related","data":{},"timestamp":int(__import__('time').time()*1000),"sessionId":"debug-session","runId":"run1","hypothesisId":"A"}) + '\n')
                            except: pass
                            # #endregion
                            logo_attachment_part = None
                        
                        # KRITISCH: Erstelle IMMER multipart/mixed Struktur, wenn Logo vorhanden ist
                        # Grund: Logo muss sowohl inline (in multipart/related) als auch als attachment sein
                        if logo_part and logo_attachment_part:
                            # Erstelle multipart/mixed als äußere Ebene
                            from email.mime.multipart import MIMEMultipart as OuterMIMEMultipart
                            outer_msg = OuterMIMEMultipart('mixed')
                            
                            # Kopiere alle Header von new_msg zu outer_msg
                            for key, value in new_msg.items():
                                if key.lower() not in ['content-type', 'mime-version']:
                                    outer_msg[key] = value
                            
                            # Füge multipart/related (mit alternative + logo als inline) als ersten Part hinzu
                            outer_msg.attach(new_msg)
                            
                            # Füge Logo als attachment hinzu
                            outer_msg.attach(logo_attachment_part)
                            
                            # Füge andere Anhänge hinzu (falls vorhanden)
                            if other_attachments:
                                for att in other_attachments:
                                    outer_msg.attach(att)
                            
                            # Ersetze msg.msg mit der verschachtelten Struktur
                            msg.msg = outer_msg
                            
                            # #region agent log
                            try:
                                import json
                                with open(r'c:\Users\ermat\Documents\GitHub\Prismateams_web\.cursor\debug.log', 'a', encoding='utf-8') as f:
                                    f.write(json.dumps({"location":"email_sender.py:375","message":"Struktur verschachtelt: multipart/mixed mit multipart/related + Logo als Attachment","data":{"outer_type":"multipart/mixed","inner_type":"multipart/related","has_logo_inline":True,"has_logo_attachment":True,"other_attachments_count":len(other_attachments) if other_attachments else 0},"timestamp":int(__import__('time').time()*1000),"sessionId":"debug-session","runId":"run1","hypothesisId":"F"}) + '\n')
                            except: pass
                            # #endregion
                        elif other_attachments:
                            # Logo nicht gefunden, aber andere Anhänge vorhanden
                            # Erstelle multipart/mixed als äußere Ebene
                            from email.mime.multipart import MIMEMultipart as OuterMIMEMultipart
                            outer_msg = OuterMIMEMultipart('mixed')
                            
                            # Kopiere alle Header von new_msg zu outer_msg
                            for key, value in new_msg.items():
                                if key.lower() not in ['content-type', 'mime-version']:
                                    outer_msg[key] = value
                            
                            # Füge multipart/related (mit alternative) als ersten Part hinzu
                            outer_msg.attach(new_msg)
                            
                            # Füge andere Anhänge hinzu
                            for att in other_attachments:
                                outer_msg.attach(att)
                            
                            # Ersetze msg.msg mit der verschachtelten Struktur
                            msg.msg = outer_msg
                        else:
                            # Keine anderen Anhänge und kein Logo-Anhang - multipart/related bleibt wie es ist
                            # Ersetze msg.msg mit neuer Struktur
                            msg.msg = new_msg
                    
                    # #region agent log
                    try:
                        import json
                        # Detaillierte Logging der finalen Struktur
                        final_parts = new_msg.get_payload() if hasattr(new_msg, 'get_payload') else []
                        parts_detail = []
                        if isinstance(final_parts, list):
                            for i, p in enumerate(final_parts):
                                part_info = {
                                    "index": i,
                                    "content_type": p.get_content_type() if hasattr(p, 'get_content_type') else 'N/A',
                                    "content_id": p.get('Content-ID', '') if hasattr(p, 'get') else '',
                                    "disposition": p.get('Content-Disposition', '') if hasattr(p, 'get') else ''
                                }
                                # Wenn es ein multipart ist, zeige auch seine Parts
                                if hasattr(p, 'get_payload'):
                                    sub_parts = p.get_payload()
                                    if isinstance(sub_parts, list):
                                        part_info["subparts_count"] = len(sub_parts)
                                parts_detail.append(part_info)
                        with open(r'c:\Users\ermat\Documents\GitHub\Prismateams_web\.cursor\debug.log', 'a', encoding='utf-8') as f:
                            f.write(json.dumps({"location":"email_sender.py:170","message":"Message-Struktur auf multipart/related umgestellt","data":{"new_content_type":new_msg.get_content_type(),"has_logo":logo_part is not None,"total_parts":len(final_parts) if isinstance(final_parts, list) else 0,"parts_detail":parts_detail},"timestamp":int(__import__('time').time()*1000),"sessionId":"debug-session","runId":"run1","hypothesisId":"K"}) + '\n')
                    except: pass
                    # #endregion
                    logging.info("Message-Struktur auf multipart/related umgestellt für inline Logo")
                else:
                    # Wenn bereits multipart/related oder andere Struktur, markiere Logo nur mit CID
                    if hasattr(msg.msg, 'get_payload'):
                        parts = msg.msg.get_payload()
                        if isinstance(parts, list):
                            logo_filenames = ['logo.png', 'logo.jpg', 'logo.jpeg', 'logo.gif']
                            for part in parts:
                                if (hasattr(part, 'get_content_type') and 
                                    part.get_content_type().startswith('image/')):
                                    disp = part.get('Content-Disposition', '')
                                    is_logo = any(logo_fn in disp for logo_fn in logo_filenames)
                                    if is_logo:
                                        # Setze CID
                                        if not part.get('Content-ID'):
                                            part.add_header('Content-ID', '<portal_logo>')
                                        # Stelle sicher, dass es inline ist
                                        if 'attachment' in disp and 'inline' not in disp:
                                            import re
                                            filename_match = re.search(r'filename="?([^"]+)"?', disp)
                                            filename = filename_match.group(1) if filename_match else 'logo.png'
                                            try:
                                                part.replace_header('Content-Disposition', f'inline; filename="{filename}"')
                                            except:
                                                del part['Content-Disposition']
                                                part.add_header('Content-Disposition', f'inline; filename="{filename}"')
                                        elif not disp:
                                            part.add_header('Content-Disposition', 'inline; filename="logo.png"')
                                        
                                        # #region agent log
                                        try:
                                            import json
                                            with open(r'c:\Users\ermat\Documents\GitHub\Prismateams_web\.cursor\debug.log', 'a', encoding='utf-8') as f:
                                                f.write(json.dumps({"location":"email_sender.py:200","message":"Logo mit CID markiert (bereits multipart/related)","data":{"cid":part.get('Content-ID'),"disposition":part.get('Content-Disposition'),"content_type":part.get_content_type()},"timestamp":int(__import__('time').time()*1000),"sessionId":"debug-session","runId":"run1","hypothesisId":"J"}) + '\n')
                                        except: pass
                                        # #endregion
                                        logging.info(f"Logo mit CID markiert: {part.get('Content-ID')}, Disposition: {part.get('Content-Disposition')}")
                                        break
            
            # #region agent log
            try:
                import json
                if hasattr(msg, 'msg') and msg.msg:
                    msg_ct = msg.msg.get_content_type() if hasattr(msg.msg, 'get_content_type') else 'N/A'
                    parts_count = 0
                    logo_cid_found = None
                    logo_disp_found = None
                    if hasattr(msg.msg, 'get_payload'):
                        parts = msg.msg.get_payload()
                        if isinstance(parts, list):
                            parts_count = len(parts)
                            for p in parts:
                                if hasattr(p, 'get_content_type') and p.get_content_type().startswith('image/'):
                                    disp = p.get('Content-Disposition', '')
                                    if 'logo' in disp.lower():
                                        logo_cid_found = p.get('Content-ID', '')
                                        logo_disp_found = disp
                                        break
                    with open(r'c:\Users\ermat\Documents\GitHub\Prismateams_web\.cursor\debug.log', 'a', encoding='utf-8') as f:
                        f.write(json.dumps({"location":"email_sender.py:313","message":"VOR mail.send() - Finale Message-Struktur in send_email_with_lock()","data":{"content_type":msg_ct,"parts_count":parts_count,"logo_cid":logo_cid_found,"logo_disposition":logo_disp_found},"timestamp":int(__import__('time').time()*1000),"sessionId":"debug-session","runId":"run1","hypothesisId":"B"}) + '\n')
            except Exception as e:
                try:
                    import json
                    with open(r'c:\Users\ermat\Documents\GitHub\Prismateams_web\.cursor\debug.log', 'a', encoding='utf-8') as f:
                        f.write(json.dumps({"location":"email_sender.py:313","message":"FEHLER beim Loggen vor mail.send()","data":{"error":str(e)},"timestamp":int(__import__('time').time()*1000),"sessionId":"debug-session","runId":"run1","hypothesisId":"B"}) + '\n')
                except: pass
            # #endregion
            
            # KRITISCH: Flask-Mail's send() erstellt möglicherweise msg.msg neu und überschreibt unsere Struktur
            # Lösung: Sende die Message direkt über SMTP, ohne Flask-Mail's send()
            try:
                import smtplib
                from email.utils import formataddr
                
                # Hole SMTP-Konfiguration
                mail_server = current_app.config.get('MAIL_SERVER')
                mail_port = current_app.config.get('MAIL_PORT', 587)
                mail_username = current_app.config.get('MAIL_USERNAME')
                mail_password = current_app.config.get('MAIL_PASSWORD')
                mail_use_tls = current_app.config.get('MAIL_USE_TLS', True)
                mail_use_ssl = current_app.config.get('MAIL_USE_SSL', False)
                
                # Stelle sicher, dass msg.msg unsere manipulierten Struktur ist
                if not hasattr(msg, 'msg') or not msg.msg:
                    # Falls msg.msg nicht existiert, erstelle es (sollte aber bereits existieren)
                    if hasattr(msg, '_message'):
                        msg.msg = msg._message()
                    else:
                        # Fallback: Verwende Flask-Mail's send()
                        mail.send(msg)
                        return True
                
                # Sende direkt über SMTP
                if mail_use_ssl:
                    smtp = smtplib.SMTP_SSL(mail_server, mail_port)
                else:
                    smtp = smtplib.SMTP(mail_server, mail_port)
                    if mail_use_tls:
                        smtp.starttls()
                
                smtp.login(mail_username, mail_password)
                
                # Konvertiere Message zu String und sende
                email_string = msg.msg.as_string()
                email_bytes = email_string.encode('utf-8')
                
                # Bestimme Empfänger
                recipients = []
                if hasattr(msg, 'recipients'):
                    recipients.extend(msg.recipients if isinstance(msg.recipients, list) else [msg.recipients])
                if hasattr(msg, 'cc') and msg.cc:
                    recipients.extend(msg.cc if isinstance(msg.cc, list) else [msg.cc])
                if hasattr(msg, 'bcc') and msg.bcc:
                    recipients.extend(msg.bcc if isinstance(msg.bcc, list) else [msg.bcc])
                
                # Sende E-Mail
                smtp.sendmail(msg.sender, recipients, email_bytes)
                smtp.quit()
                
                # #region agent log
                try:
                    import json
                    with open(r'c:\Users\ermat\Documents\GitHub\Prismateams_web\.cursor\debug.log', 'a', encoding='utf-8') as f:
                        f.write(json.dumps({"location":"email_sender.py:350","message":"E-Mail direkt über SMTP gesendet (Flask-Mail umgangen)","data":{"recipients_count":len(recipients)},"timestamp":int(__import__('time').time()*1000),"sessionId":"debug-session","runId":"run1","hypothesisId":"B"}) + '\n')
                except: pass
                # #endregion
                
                return True
                
            except Exception as smtp_error:
                # Fallback: Verwende Flask-Mail's send() wenn SMTP direkt fehlschlägt
                logging.warning(f"Direktes SMTP-Senden fehlgeschlagen, verwende Flask-Mail: {smtp_error}")
                try:
                    mail.send(msg)
                    # #region agent log
                    try:
                        import json
                        with open(r'c:\Users\ermat\Documents\GitHub\Prismateams_web\.cursor\debug.log', 'a', encoding='utf-8') as f:
                            f.write(json.dumps({"location":"email_sender.py:365","message":"Fallback: Flask-Mail.send() verwendet","data":{"error":str(smtp_error)},"timestamp":int(__import__('time').time()*1000),"sessionId":"debug-session","runId":"run1","hypothesisId":"B"}) + '\n')
                    except: pass
                    # #endregion
                    return True
                except Exception as fallback_error:
                    logging.error(f"Fehler beim Senden der E-Mail: {fallback_error}")
                    raise
        else:
            logging.warning("E-Mail-Versand-Lock konnte nicht erworben werden, versuche erneut ohne Lock...")
            # Fallback: Versuche ohne Lock zu senden (falls Lock-Mechanismus nicht funktioniert)
            if not hasattr(msg, 'msg') or not msg.msg:
                try:
                    if hasattr(msg, '_message'):
                        msg.msg = msg._message()
                except Exception as e:
                    logging.warning(f"Fehler beim Erstellen von msg.msg via _message(): {e}")
            
            # Manipuliere auch hier
            if hasattr(msg, 'msg') and msg.msg:
                if hasattr(msg.msg, 'get_payload'):
                    parts = msg.msg.get_payload()
                    if isinstance(parts, list):
                        logo_filenames = ['logo.png', 'logo.jpg', 'logo.jpeg', 'logo.gif']
                        for part in parts:
                            if (hasattr(part, 'get_content_type') and 
                                part.get_content_type().startswith('image/')):
                                disp = part.get('Content-Disposition', '')
                                is_logo = any(logo_fn in disp for logo_fn in logo_filenames)
                                if is_logo:
                                    if not part.get('Content-ID'):
                                        part.add_header('Content-ID', '<portal_logo>')
                                    if 'attachment' in disp and 'inline' not in disp:
                                        import re
                                        filename_match = re.search(r'filename="?([^"]+)"?', disp)
                                        filename = filename_match.group(1) if filename_match else 'logo.png'
                                        try:
                                            part.replace_header('Content-Disposition', f'inline; filename="{filename}"')
                                        except:
                                            del part['Content-Disposition']
                                            part.add_header('Content-Disposition', f'inline; filename="{filename}"')
                                    elif not disp:
                                        part.add_header('Content-Disposition', 'inline; filename="logo.png"')
                                    break
            
            mail.send(msg)
            return True


def generate_confirmation_code():
    """Generiert einen 6-stelligen Bestätigungscode."""
    return ''.join(secrets.choice(string.digits) for _ in range(6))


def get_logo_data():
    """Holt das Portal-Logo aus SystemSettings oder Konfiguration und gibt Logo-Daten, MIME-Type und Dateiname zurück."""
    # #region agent log
    try:
        import json
        with open(r'c:\Users\ermat\Documents\GitHub\Prismateams_web\.cursor\debug.log', 'a', encoding='utf-8') as f:
            f.write(json.dumps({"location":"email_sender.py:44","message":"get_logo_data() aufgerufen","data":{},"timestamp":int(__import__('time').time()*1000),"sessionId":"debug-session","runId":"run1","hypothesisId":"A"}) + '\n')
    except: pass
    # #endregion
    try:
        from app.models.settings import SystemSettings
        
        # Versuche Portal-Logo aus SystemSettings zu laden
        portal_logo_setting = SystemSettings.query.filter_by(key='portal_logo').first()
        if portal_logo_setting and portal_logo_setting.value:
            # Portal-Logo ist in uploads/system/ gespeichert
            project_root = os.path.dirname(current_app.root_path)
            logo_path = os.path.join(project_root, current_app.config['UPLOAD_FOLDER'], 'system', portal_logo_setting.value)
            if os.path.exists(logo_path):
                try:
                    with open(logo_path, 'rb') as f:
                        logo_data = f.read()
                    # Bestimme MIME-Type basierend auf Dateierweiterung
                    ext = os.path.splitext(portal_logo_setting.value)[1].lower()
                    mime_types = {
                        '.png': 'image/png',
                        '.jpg': 'image/jpeg',
                        '.jpeg': 'image/jpeg',
                        '.gif': 'image/gif',
                        '.svg': 'image/svg+xml'
                    }
                    mime_type = mime_types.get(ext, 'image/png')
                    filename = portal_logo_setting.value
                    # #region agent log
                    try:
                        import json
                        with open(r'c:\Users\ermat\Documents\GitHub\Prismateams_web\.cursor\debug.log', 'a', encoding='utf-8') as f:
                            f.write(json.dumps({"location":"email_sender.py:70","message":"Portal-Logo geladen","data":{"has_data":logo_data is not None,"data_size":len(logo_data) if logo_data else 0,"mime_type":mime_type,"filename":filename},"timestamp":int(__import__('time').time()*1000),"sessionId":"debug-session","runId":"run1","hypothesisId":"A"}) + '\n')
                    except: pass
                    # #endregion
                    return logo_data, mime_type, filename
                except Exception as e:
                    logging.warning(f"Fehler beim Laden des Portal-Logos: {e}")
    except Exception as e:
        logging.warning(f"Fehler beim Zugriff auf SystemSettings: {e}")
    
    # Fallback zu Standard-Logo
    try:
        logo_path = current_app.config.get('APP_LOGO', 'static/img/logo.png')
        
        # Wenn der Pfad mit 'static/' beginnt, entferne es
        if logo_path.startswith('static/'):
            logo_path = logo_path[7:]
        
        # Konvertiere zu absolutem Pfad
        static_folder = current_app.static_folder
        full_path = os.path.join(static_folder, logo_path)
        
        if os.path.exists(full_path):
            with open(full_path, 'rb') as f:
                logo_data = f.read()
            # Bestimme MIME-Type basierend auf Dateierweiterung
            ext = os.path.splitext(full_path)[1].lower()
            mime_types = {
                '.png': 'image/png',
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.gif': 'image/gif',
                '.svg': 'image/svg+xml'
            }
            mime_type = mime_types.get(ext, 'image/png')
            filename = os.path.basename(full_path)
            # #region agent log
            try:
                import json
                with open(r'c:\Users\ermat\Documents\GitHub\Prismateams_web\.cursor\debug.log', 'a', encoding='utf-8') as f:
                    f.write(json.dumps({"location":"email_sender.py:102","message":"Standard-Logo geladen","data":{"has_data":logo_data is not None,"data_size":len(logo_data) if logo_data else 0,"mime_type":mime_type,"filename":filename},"timestamp":int(__import__('time').time()*1000),"sessionId":"debug-session","runId":"run1","hypothesisId":"A"}) + '\n')
            except: pass
            # #endregion
            return logo_data, mime_type, filename
    except Exception as e:
        logging.warning(f"Fehler beim Laden des Standard-Logos: {e}")
    
    # Wenn kein Logo gefunden wurde, gib None zurück
    # #region agent log
    try:
        import json
        with open(r'c:\Users\ermat\Documents\GitHub\Prismateams_web\.cursor\debug.log', 'a', encoding='utf-8') as f:
            f.write(json.dumps({"location":"email_sender.py:107","message":"KEIN Logo gefunden - get_logo_data gibt None zurück","data":{},"timestamp":int(__import__('time').time()*1000),"sessionId":"debug-session","runId":"run1","hypothesisId":"A"}) + '\n')
    except: pass
    # #endregion
    return None, None, None


def get_logo_base64():
    """Holt das Portal-Logo aus SystemSettings oder Konfiguration und gibt es als Base64-String zurück."""
    logo_data, mime_type, _ = get_logo_data()
    if logo_data and mime_type:
        logo_base64 = base64.b64encode(logo_data).decode('utf-8')
        return f"data:{mime_type};base64,{logo_base64}"
    return None


def create_message_with_logo(subject, recipients, html_content, body_text=None, sender=None, cc=None, logo_cid='portal_logo'):
    """
    Erstellt eine Flask-Mail Message mit Logo als CID-Anhang.
    
    Args:
        subject: E-Mail-Betreff
        recipients: Liste von Empfängern oder String mit kommagetrennten Adressen
        html_content: HTML-Inhalt der E-Mail
        body_text: Plain-Text-Version (optional)
        sender: Absender (optional, wird aus Config geholt wenn None)
        cc: CC-Empfänger (optional)
        logo_cid: Content-ID für das Logo (Standard: 'portal_logo')
    
    Returns:
        Flask-Mail Message-Objekt mit Logo als CID-Anhang
    """
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.image import MIMEImage
    from email.header import Header
    from config import get_formatted_sender
    
    # Hole Absender
    if not sender:
        mail_username = current_app.config.get('MAIL_USERNAME')
        sender = get_formatted_sender() or mail_username
    
    # Normalisiere Empfänger
    if isinstance(recipients, str):
        recipients_list = [r.strip() for r in recipients.split(',')]
    else:
        recipients_list = recipients
    
    # Erstelle multipart/related Message für HTML mit inline images
    msg_multipart = MIMEMultipart('related')
    
    # Setze Header
    msg_multipart['Subject'] = Header(subject, 'utf-8')
    msg_multipart['From'] = sender
    msg_multipart['To'] = ', '.join(recipients_list)
    if cc:
        if isinstance(cc, str):
            cc_list = [c.strip() for c in cc.split(',')]
        else:
            cc_list = cc
        msg_multipart['Cc'] = ', '.join(cc_list)
    
    # Erstelle multipart/alternative für plain text und HTML
    msg_alternative = MIMEMultipart('alternative')
    msg_multipart.attach(msg_alternative)
    
    # Füge plain text hinzu (falls vorhanden)
    if body_text:
        msg_alternative.attach(MIMEText(body_text, 'plain', 'utf-8'))
    else:
        # Fallback: HTML zu Text konvertieren (einfach)
        import re
        from html import unescape
        text_content = re.sub(r'<[^>]+>', '', html_content)
        text_content = unescape(text_content).strip()
        msg_alternative.attach(MIMEText(text_content, 'plain', 'utf-8'))
    
    # Füge HTML hinzu
    msg_alternative.attach(MIMEText(html_content, 'html', 'utf-8'))
    
    # Füge Logo als inline attachment mit CID hinzu
    logo_data, logo_mime_type, logo_filename = get_logo_data()
    if logo_data and logo_mime_type:
        image_type = logo_mime_type.split('/')[1] if '/' in logo_mime_type else 'png'
        
        # Standardisiere Dateiname basierend auf MIME-Type
        if image_type == 'jpeg' or image_type == 'jpg':
            attachment_filename = 'logo.jpg'
        elif image_type == 'png':
            attachment_filename = 'logo.png'
        elif image_type == 'gif':
            attachment_filename = 'logo.gif'
        else:
            attachment_filename = 'logo.png'  # Default
        
        img_attachment = MIMEImage(logo_data, image_type)
        img_attachment.add_header('Content-ID', f'<{logo_cid}>')
        img_attachment.add_header('Content-Disposition', 'inline', filename=attachment_filename)
        # Stelle sicher, dass Content-Type korrekt gesetzt ist
        img_attachment.add_header('Content-Type', logo_mime_type)
        msg_multipart.attach(img_attachment)
        logging.info(f"Logo als Anhang hinzugefügt: {attachment_filename} ({logo_mime_type}), CID: {logo_cid}, Größe: {len(logo_data)} bytes")
    else:
        logging.warning("Logo konnte nicht geladen werden - kein Logo als Anhang hinzugefügt")
    
    # Erstelle Flask-Mail Message Objekt und kopiere die konstruierte Message
    msg = Message(
        subject=subject,
        recipients=recipients_list,
        body=body_text or '',
        html=html_content,
        sender=sender
    )
    if cc:
        if isinstance(cc, str):
            msg.cc = cc.split(',')
        else:
            msg.cc = cc
    
    # Ersetze die interne Message-Struktur mit unserer multipart/related Version
    # WICHTIG: Flask-Mail verwendet msg.msg beim Senden, also müssen wir die komplette
    # multipart-Struktur hier setzen
    msg.msg = msg_multipart
    
    # Debug: Überprüfe, dass Logo-Anhang vorhanden ist
    if hasattr(msg.msg, 'get_payload'):
        parts = msg.msg.get_payload()
        if isinstance(parts, list):
            attachment_count = sum(1 for p in parts if hasattr(p, 'get_content_type') and p.get_content_type().startswith('image/'))
            logging.info(f"Message-Struktur nach msg.msg Setzen: {len(parts)} Teile, davon {attachment_count} Bild-Anhänge")
            logo_found = False
            for i, part in enumerate(parts):
                if hasattr(part, 'get_content_type') and part.get_content_type().startswith('image/'):
                    cid = part.get('Content-ID', 'N/A')
                    filename = part.get('Content-Disposition', 'N/A')
                    logging.info(f"  Logo-Anhang {i}: Content-ID={cid}, Disposition={filename}")
                    if cid != 'N/A' and logo_cid in cid:
                        logo_found = True
            
            if not logo_found and logo_data and logo_mime_type:
                logging.warning("Logo wurde nicht in Message-Struktur gefunden, obwohl es hinzugefügt wurde!")
    
    return msg


def send_confirmation_email(user):
    """Sendet eine Bestätigungs-E-Mail an den Benutzer."""
    try:
        # Generiere Bestätigungscode
        confirmation_code = generate_confirmation_code()
        
        # Setze Ablaufzeit (24 Stunden)
        expires_at = datetime.utcnow() + timedelta(hours=24)
        
        # Aktualisiere Benutzer-Daten
        user.confirmation_code = confirmation_code
        user.confirmation_code_expires = expires_at
        user.is_email_confirmed = False
        
        # Speichere in Datenbank
        from app import db
        db.session.commit()
        
        # Prüfe E-Mail-Konfiguration
        mail_server = current_app.config.get('MAIL_SERVER')
        mail_username = current_app.config.get('MAIL_USERNAME')
        mail_password = current_app.config.get('MAIL_PASSWORD')
        mail_port = current_app.config.get('MAIL_PORT', 587)
        mail_use_tls = current_app.config.get('MAIL_USE_TLS', True)
        mail_use_ssl = current_app.config.get('MAIL_USE_SSL', False)
        
        
        if not all([mail_server, mail_username, mail_password]):
            logging.warning(f"E-Mail-Konfiguration unvollständig. Code für {user.email}: {confirmation_code}")
            return False
        
        # Get portal name from SystemSettings
        try:
            from app.models.settings import SystemSettings
            portal_name_setting = SystemSettings.query.filter_by(key='portal_name').first()
            portal_name = portal_name_setting.value if portal_name_setting and portal_name_setting.value else current_app.config.get('APP_NAME', 'Prismateams')
        except:
            portal_name = current_app.config.get('APP_NAME', 'Prismateams')
        
        # HTML-Template rendern (Logo wird als CID-Anhang eingefügt)
        html_content = render_template(
            'emails/confirmation_code.html',
            user=user,
            confirmation_code=confirmation_code,
            app_name=portal_name,
            current_year=datetime.utcnow().year,
            logo_cid='portal_logo'
        )
        
        # Plain text Version
        plain_text = f"E-Mail-Bestätigungscode: {confirmation_code}\n\nBitte geben Sie diesen Code zur Bestätigung Ihrer E-Mail-Adresse ein."
        
        # Erstelle Message mit Logo als CID-Anhang
        msg = create_message_with_logo(
            subject=f'E-Mail-Bestätigung - {portal_name}',
            recipients=[user.email],
            html_content=html_content,
            body_text=plain_text
        )
        
        # E-Mail senden mit verbesserter Fehlerbehandlung
        try:
            send_email_with_lock(msg)
            logging.info(f"Confirmation email sent to {user.email} with code: {confirmation_code}")
            return True
        except Exception as send_error:
            logging.error(f"Failed to send confirmation email to {user.email}: {str(send_error)}")
            
            # Versuche alternative Konfiguration für Infomaniak
            try:
                logging.info("Versuche alternative E-Mail-Konfiguration...")
                
                # Get portal name from SystemSettings (bereits oben definiert, aber zur Sicherheit nochmal)
                try:
                    from app.models.settings import SystemSettings
                    portal_name_setting = SystemSettings.query.filter_by(key='portal_name').first()
                    portal_name = portal_name_setting.value if portal_name_setting and portal_name_setting.value else current_app.config.get('APP_NAME', 'Prismateams')
                except:
                    portal_name = current_app.config.get('APP_NAME', 'Prismateams')
                
                # HTML-Template rendern
                html_content_alt = render_template(
                    'emails/confirmation_code.html',
                    user=user,
                    confirmation_code=confirmation_code,
                    app_name=portal_name,
                    current_year=datetime.utcnow().year,
                    logo_cid='portal_logo'
                )
                
                # Plain text Version
                plain_text_alt = f"E-Mail-Bestätigungscode: {confirmation_code}\n\nBitte geben Sie diesen Code zur Bestätigung Ihrer E-Mail-Adresse ein."
                
                # Erstelle Message mit Logo als CID-Anhang
                msg_alt = create_message_with_logo(
                    subject=f'E-Mail-Bestätigung - {portal_name}',
                    recipients=[user.email],
                    html_content=html_content_alt,
                    body_text=plain_text_alt
                )
                
                # Versuche erneut zu senden
                send_email_with_lock(msg_alt)
                logging.info(f"Alternative E-Mail erfolgreich gesendet an {user.email}")
                return True
                
            except Exception as alt_error:
                logging.error(f"Alternative E-Mail-Versand auch fehlgeschlagen: {str(alt_error)}")
                return False
        
    except Exception as e:
        logging.error(f"Failed to send confirmation email to {user.email}: {str(e)}")
        # Code trotzdem in Datenbank speichern für manuelle Eingabe
        return False


def verify_confirmation_code(user, code):
    """Überprüft den Bestätigungscode."""
    if not user.confirmation_code or not user.confirmation_code_expires:
        return False
    
    # Prüfe Ablaufzeit
    if datetime.utcnow() > user.confirmation_code_expires:
        return False
    
    # Prüfe Code
    if user.confirmation_code != code:
        return False
    
    # Code ist gültig - bestätige E-Mail
    user.is_email_confirmed = True
    user.confirmation_code = None
    user.confirmation_code_expires = None
    
    from app import db
    db.session.commit()
    
    return True


def resend_confirmation_email(user):
    """Sendet eine neue Bestätigungs-E-Mail."""
    return send_confirmation_email(user)


def send_borrow_receipt_email(borrow_transactions):
    """Sendet eine E-Mail mit Ausleihschein-PDF nach erfolgreicher Ausleihe."""
    try:
        from app.models.inventory import BorrowTransaction, Product
        from app.utils.pdf_generator import generate_borrow_receipt_pdf
        from io import BytesIO
        
        # Normalisiere zu Liste
        if not isinstance(borrow_transactions, list):
            borrow_transactions = [borrow_transactions]
        
        if not borrow_transactions:
            logging.error("Keine Transaktionen zum Versenden vorhanden.")
            return False
        
        first_transaction = borrow_transactions[0]
        borrower = first_transaction.borrower
        
        # Prüfe E-Mail-Konfiguration
        mail_server = current_app.config.get('MAIL_SERVER')
        mail_username = current_app.config.get('MAIL_USERNAME')
        mail_password = current_app.config.get('MAIL_PASSWORD')
        
        if not all([mail_server, mail_username, mail_password]):
            logging.warning(f"E-Mail-Konfiguration unvollständig. Ausleihschein für {first_transaction.transaction_number} nicht gesendet.")
            return False
        
        if not borrower.email:
            logging.warning(f"Benutzer {borrower.id} hat keine E-Mail-Adresse. Ausleihschein nicht gesendet.")
            return False
        
        # Get portal name from SystemSettings
        try:
            from app.models.settings import SystemSettings
            portal_name_setting = SystemSettings.query.filter_by(key='portal_name').first()
            portal_name = portal_name_setting.value if portal_name_setting and portal_name_setting.value else current_app.config.get('APP_NAME', 'Prismateams')
        except:
            portal_name = current_app.config.get('APP_NAME', 'Prismateams')
        
        # Erstelle E-Mail
        from config import get_formatted_sender
        sender = get_formatted_sender() or mail_username
        msg = Message(
            subject=f'Ausleihschein - {portal_name}',
            recipients=[borrower.email],
            sender=sender
        )
        
        # Logo als Base64 laden
        logo_base64 = get_logo_base64()
        
        # HTML-Template für Ausleihschein
        borrow_date = first_transaction.borrow_date.strftime('%d.%m.%Y %H:%M')
        expected_return_date = first_transaction.expected_return_date.strftime('%d.%m.%Y')
        
        html_content = render_template(
            'emails/borrow_receipt.html',
            app_name=portal_name,
            borrower=borrower,
            transactions=borrow_transactions,
            borrow_date=borrow_date,
            expected_return_date=expected_return_date,
            transaction_number=first_transaction.transaction_number,
            current_year=datetime.utcnow().year,
            logo_base64=logo_base64
        )
        
        msg.html = html_content
        
        # PDF-Anhang generieren
        pdf_buffer = BytesIO()
        generate_borrow_receipt_pdf(borrow_transactions, pdf_buffer)
        pdf_buffer.seek(0)
        
        # PDF als Anhang hinzufügen
        filename = f"Ausleihschein_{first_transaction.transaction_number}.pdf"
        msg.attach(filename, "application/pdf", pdf_buffer.read())
        
        # E-Mail senden
        try:
            send_email_with_lock(msg)
            logging.info(f"Borrow receipt email sent to {borrower.email} for transaction {first_transaction.transaction_number}")
            return True
        except Exception as send_error:
            logging.error(f"Failed to send borrow receipt email to {borrower.email}: {str(send_error)}")
            return False
        
    except Exception as e:
        logging.error(f"Failed to send borrow receipt email: {str(e)}")
        return False


def send_return_confirmation_email(borrow_transaction):
    """Sendet eine Bestätigungs-E-Mail nach erfolgreicher Rückgabe mit PDF-Anhang."""
    try:
        from app.models.inventory import BorrowTransaction, Product
        from app.utils.pdf_generator import generate_return_confirmation_pdf
        from io import BytesIO
        
        product = borrow_transaction.product
        borrower = borrow_transaction.borrower
        
        # Prüfe E-Mail-Konfiguration
        mail_server = current_app.config.get('MAIL_SERVER')
        mail_username = current_app.config.get('MAIL_USERNAME')
        mail_password = current_app.config.get('MAIL_PASSWORD')
        
        if not all([mail_server, mail_username, mail_password]):
            logging.warning(f"E-Mail-Konfiguration unvollständig. Rückgabe-Bestätigung für {borrow_transaction.transaction_number} nicht gesendet.")
            return False
        
        # Get portal name from SystemSettings
        try:
            from app.models.settings import SystemSettings
            portal_name_setting = SystemSettings.query.filter_by(key='portal_name').first()
            portal_name = portal_name_setting.value if portal_name_setting and portal_name_setting.value else current_app.config.get('APP_NAME', 'Prismateams')
        except:
            portal_name = current_app.config.get('APP_NAME', 'Prismateams')
        
        # Erstelle E-Mail
        from config import get_formatted_sender
        sender = get_formatted_sender() or mail_username
        msg = Message(
            subject=f'Rückgabe-Bestätigung - {portal_name}',
            recipients=[borrower.email],
            sender=sender
        )
        
        # Logo als Base64 laden
        logo_base64 = get_logo_base64()
        
        # HTML-Template für Rückgabe-Bestätigung
        return_date = borrow_transaction.actual_return_date.strftime('%d.%m.%Y') if borrow_transaction.actual_return_date else datetime.utcnow().strftime('%d.%m.%Y')
        
        html_content = render_template(
            'emails/return_confirmation.html',
            app_name=portal_name,
            borrower=borrower,
            product=product,
            transaction=borrow_transaction,
            return_date=return_date,
            current_year=datetime.utcnow().year,
            logo_base64=logo_base64
        )
        
        msg.html = html_content
        
        # PDF-Anhang generieren
        pdf_buffer = BytesIO()
        generate_return_confirmation_pdf(borrow_transaction, pdf_buffer)
        pdf_buffer.seek(0)
        
        # PDF als Anhang hinzufügen
        filename = f"Rueckgabe_Bestaetigung_{borrow_transaction.transaction_number}.pdf"
        msg.attach(filename, "application/pdf", pdf_buffer.read())
        
        # E-Mail senden
        try:
            send_email_with_lock(msg)
            logging.info(f"Return confirmation email sent to {borrower.email} for transaction {borrow_transaction.transaction_number}")
            return True
        except Exception as send_error:
            logging.error(f"Failed to send return confirmation email to {borrower.email}: {str(send_error)}")
            return False
        
    except Exception as e:
        logging.error(f"Failed to send return confirmation email: {str(e)}")
        return False


def send_booking_confirmation_email(booking_request):
    """Sendet eine Bestätigungs-E-Mail nach Buchungsanfrage."""
    try:
        from app.models.booking import BookingRequest
        
        # Prüfe E-Mail-Konfiguration
        mail_server = current_app.config.get('MAIL_SERVER')
        mail_username = current_app.config.get('MAIL_USERNAME')
        mail_password = current_app.config.get('MAIL_PASSWORD')
        
        if not all([mail_server, mail_username, mail_password]):
            logging.warning(f"E-Mail-Konfiguration unvollständig. Bestätigung für Buchung {booking_request.id} nicht gesendet.")
            return False
        
        # Get portal name from SystemSettings
        try:
            from app.models.settings import SystemSettings
            portal_name_setting = SystemSettings.query.filter_by(key='portal_name').first()
            portal_name = portal_name_setting.value if portal_name_setting and portal_name_setting.value else current_app.config.get('APP_NAME', 'Prismateams')
        except:
            portal_name = current_app.config.get('APP_NAME', 'Prismateams')
        
        # Erstelle E-Mail
        from config import get_formatted_sender
        sender = get_formatted_sender() or mail_username
        msg = Message(
            subject=f'Buchungsbestätigung - {portal_name}',
            recipients=[booking_request.email],
            sender=sender
        )
        
        # Logo als Base64 laden
        logo_base64 = get_logo_base64()
        
        # Generiere Link zur Buchungsübersicht
        booking_url = url_for('booking.public_view', token=booking_request.token, _external=True)
        
        # HTML-Template rendern
        html_content = render_template(
            'emails/booking_confirmation.html',
            app_name=portal_name,
            booking_request=booking_request,
            booking_url=booking_url,
            current_year=datetime.utcnow().year,
            logo_base64=logo_base64
        )
        
        msg.html = html_content
        
        # E-Mail senden
        try:
            send_email_with_lock(msg)
            logging.info(f"Booking confirmation email sent to {booking_request.email} for booking {booking_request.id}")
            return True
        except Exception as send_error:
            logging.error(f"Failed to send booking confirmation email to {booking_request.email}: {str(send_error)}")
            return False
        
    except Exception as e:
        logging.error(f"Failed to send booking confirmation email: {str(e)}")
        return False


def send_booking_accepted_email(booking_request, calendar_event):
    """Sendet eine E-Mail bei Annahme einer Buchung."""
    try:
        from app.models.booking import BookingRequest
        from flask import url_for
        
        # Prüfe E-Mail-Konfiguration
        mail_server = current_app.config.get('MAIL_SERVER')
        mail_username = current_app.config.get('MAIL_USERNAME')
        mail_password = current_app.config.get('MAIL_PASSWORD')
        
        if not all([mail_server, mail_username, mail_password]):
            logging.warning(f"E-Mail-Konfiguration unvollständig. Annahme-Benachrichtigung für Buchung {booking_request.id} nicht gesendet.")
            return False
        
        # Get portal name from SystemSettings
        try:
            from app.models.settings import SystemSettings
            portal_name_setting = SystemSettings.query.filter_by(key='portal_name').first()
            portal_name = portal_name_setting.value if portal_name_setting and portal_name_setting.value else current_app.config.get('APP_NAME', 'Prismateams')
        except:
            portal_name = current_app.config.get('APP_NAME', 'Prismateams')
        
        # Erstelle E-Mail
        from config import get_formatted_sender
        sender = get_formatted_sender() or mail_username
        msg = Message(
            subject=f'Buchung angenommen - {booking_request.event_name}',
            recipients=[booking_request.email],
            sender=sender
        )
        
        # Logo als Base64 laden
        logo_base64 = get_logo_base64()
        
        # Generiere Links
        booking_url = url_for('booking.public_view', token=booking_request.token, _external=True)
        calendar_url = url_for('calendar.view_event', event_id=calendar_event.id, _external=True) if calendar_event else None
        
        # HTML-Template rendern
        html_content = render_template(
            'emails/booking_accepted.html',
            app_name=portal_name,
            booking_request=booking_request,
            calendar_event=calendar_event,
            booking_url=booking_url,
            calendar_url=calendar_url,
            current_year=datetime.utcnow().year,
            logo_base64=logo_base64
        )
        
        msg.html = html_content
        
        # E-Mail senden
        try:
            send_email_with_lock(msg)
            logging.info(f"Booking accepted email sent to {booking_request.email} for booking {booking_request.id}")
            return True
        except Exception as send_error:
            logging.error(f"Failed to send booking accepted email to {booking_request.email}: {str(send_error)}")
            return False
        
    except Exception as e:
        logging.error(f"Failed to send booking accepted email: {str(e)}")
        return False


def send_booking_rejected_email(booking_request):
    """Sendet eine E-Mail bei Ablehnung einer Buchung."""
    try:
        from app.models.booking import BookingRequest
        from flask import url_for
        
        # Prüfe E-Mail-Konfiguration
        mail_server = current_app.config.get('MAIL_SERVER')
        mail_username = current_app.config.get('MAIL_USERNAME')
        mail_password = current_app.config.get('MAIL_PASSWORD')
        
        if not all([mail_server, mail_username, mail_password]):
            logging.warning(f"E-Mail-Konfiguration unvollständig. Ablehnungs-Benachrichtigung für Buchung {booking_request.id} nicht gesendet.")
            return False
        
        # Get portal name from SystemSettings
        try:
            from app.models.settings import SystemSettings
            portal_name_setting = SystemSettings.query.filter_by(key='portal_name').first()
            portal_name = portal_name_setting.value if portal_name_setting and portal_name_setting.value else current_app.config.get('APP_NAME', 'Prismateams')
        except:
            portal_name = current_app.config.get('APP_NAME', 'Prismateams')
        
        # Erstelle E-Mail
        from config import get_formatted_sender
        sender = get_formatted_sender() or mail_username
        msg = Message(
            subject=f'Buchung abgelehnt - {booking_request.event_name}',
            recipients=[booking_request.email],
            sender=sender
        )
        
        # Logo als Base64 laden
        logo_base64 = get_logo_base64()
        
        # Generiere Link zur Buchungsübersicht
        booking_url = url_for('booking.public_view', token=booking_request.token, _external=True)
        
        # HTML-Template rendern
        html_content = render_template(
            'emails/booking_rejected.html',
            app_name=portal_name,
            booking_request=booking_request,
            booking_url=booking_url,
            current_year=datetime.utcnow().year,
            logo_base64=logo_base64
        )
        
        msg.html = html_content
        
        # E-Mail senden
        try:
            send_email_with_lock(msg)
            logging.info(f"Booking rejected email sent to {booking_request.email} for booking {booking_request.id}")
            return True
        except Exception as send_error:
            logging.error(f"Failed to send booking rejected email to {booking_request.email}: {str(send_error)}")
            return False
        
    except Exception as e:
        logging.error(f"Failed to send booking rejected email: {str(e)}")
        return False