from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app import db
from app.models.contact import Contact
from app.models.email import EmailMessage
from app.utils.access_control import check_module_access
from app.utils.i18n import translate
from sqlalchemy import or_, func, distinct
import re
import logging

contacts_bp = Blueprint('contacts', __name__)


def extract_email_addresses(text):
    """Extrahiert E-Mail-Adressen aus einem Text."""
    if not text:
        return []
    
    # Regex für E-Mail-Adressen
    pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    emails = re.findall(pattern, text)
    return [email.lower() for email in emails if email]


@contacts_bp.route('/')
@login_required
@check_module_access('module_contacts')
def index():
    """Liste aller Kontakte."""
    contacts = Contact.query.order_by(Contact.name).all()
    return render_template('contacts/index.html', contacts=contacts)


@contacts_bp.route('/create', methods=['GET', 'POST'])
@login_required
@check_module_access('module_contacts')
def create():
    """Neuen Kontakt erstellen."""
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        phone = request.form.get('phone', '').strip()
        notes = request.form.get('notes', '').strip()
        
        # Validierung
        if not name:
            flash(translate('contacts.flash.name_required'), 'danger')
            return render_template('contacts/create.html')
        
        if not email:
            flash(translate('contacts.flash.email_required'), 'danger')
            return render_template('contacts/create.html')
        
        if not Contact.is_valid_email(email):
            flash(translate('contacts.flash.invalid_email'), 'danger')
            return render_template('contacts/create.html', name=name, email=email, phone=phone, notes=notes)
        
        # Prüfe auf Duplikat (optional, nur Warnung)
        existing = Contact.query.filter_by(email=email).first()
        if existing:
            flash(translate('contacts.flash.duplicate_email'), 'warning')
        
        # Erstelle Kontakt
        contact = Contact(
            name=name,
            email=email,
            phone=phone if phone else None,
            notes=notes if notes else None,
            created_by=current_user.id
        )
        
        try:
            db.session.add(contact)
            db.session.commit()
            flash(translate('contacts.flash.created'), 'success')
            return redirect(url_for('contacts.index'))
        except Exception as e:
            db.session.rollback()
            logging.error(f"Fehler beim Erstellen des Kontakts: {e}")
            flash(translate('contacts.flash.create_error'), 'danger')
            return render_template('contacts/create.html', name=name, email=email, phone=phone, notes=notes)
    
    return render_template('contacts/create.html')


@contacts_bp.route('/<int:contact_id>/edit', methods=['GET', 'POST'])
@login_required
@check_module_access('module_contacts')
def edit(contact_id):
    """Kontakt bearbeiten."""
    contact = Contact.query.get_or_404(contact_id)
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        phone = request.form.get('phone', '').strip()
        notes = request.form.get('notes', '').strip()
        
        # Validierung
        if not name:
            flash(translate('contacts.flash.name_required'), 'danger')
            return render_template('contacts/edit.html', contact=contact)
        
        if not email:
            flash(translate('contacts.flash.email_required'), 'danger')
            return render_template('contacts/edit.html', contact=contact)
        
        if not Contact.is_valid_email(email):
            flash(translate('contacts.flash.invalid_email'), 'danger')
            contact.name = name
            contact.email = email
            contact.phone = phone
            contact.notes = notes
            return render_template('contacts/edit.html', contact=contact)
        
        # Prüfe auf Duplikat (wenn E-Mail geändert wurde)
        if email != contact.email:
            existing = Contact.query.filter_by(email=email).first()
            if existing:
                flash(translate('contacts.flash.duplicate_email'), 'warning')
        
        # Aktualisiere Kontakt
        contact.name = name
        contact.email = email
        contact.phone = phone if phone else None
        contact.notes = notes if notes else None
        
        try:
            db.session.commit()
            flash(translate('contacts.flash.updated'), 'success')
            return redirect(url_for('contacts.index'))
        except Exception as e:
            db.session.rollback()
            logging.error(f"Fehler beim Aktualisieren des Kontakts: {e}")
            flash(translate('contacts.flash.update_error'), 'danger')
            return render_template('contacts/edit.html', contact=contact)
    
    return render_template('contacts/edit.html', contact=contact)


@contacts_bp.route('/<int:contact_id>/delete', methods=['POST'])
@login_required
@check_module_access('module_contacts')
def delete(contact_id):
    """Kontakt löschen."""
    contact = Contact.query.get_or_404(contact_id)
    
    try:
        db.session.delete(contact)
        db.session.commit()
        flash(translate('contacts.flash.deleted'), 'success')
    except Exception as e:
        db.session.rollback()
        logging.error(f"Fehler beim Löschen des Kontakts: {e}")
        flash(translate('contacts.flash.delete_error'), 'danger')
    
    return redirect(url_for('contacts.index'))


@contacts_bp.route('/api/search')
@login_required
@check_module_access('module_contacts')
def search():
    """
    Sucht nach Kontakten und E-Mail-Adressen für Autovervollständigung.
    Kombiniert gespeicherte Kontakte mit E-Mail-Adressen aus empfangenen E-Mails.
    """
    query = request.args.get('q', '').strip().lower()
    
    if not query or len(query) < 2:
        return jsonify({'results': []})
    
    results = []
    seen_emails = set()
    
    # 1. Suche in gespeicherten Kontakten
    contacts = Contact.query.filter(
        or_(
            Contact.name.ilike(f'%{query}%'),
            Contact.email.ilike(f'%{query}%')
        )
    ).limit(10).all()
    
    for contact in contacts:
        email_lower = contact.email.lower()
        if email_lower not in seen_emails:
            seen_emails.add(email_lower)
            results.append({
                'type': 'contact',
                'id': contact.id,
                'name': contact.name,
                'email': contact.email,
                'phone': contact.phone or '',
                'display': f"{contact.name} <{contact.email}>"
            })
    
    # 2. Suche in E-Mail-Adressen aus empfangenen E-Mails
    # Extrahiere E-Mail-Adressen aus sender, recipients und cc Feldern
    email_messages = EmailMessage.query.filter(
        or_(
            EmailMessage.sender.ilike(f'%{query}%'),
            EmailMessage.recipients.ilike(f'%{query}%'),
            EmailMessage.cc.ilike(f'%{query}%')
        )
    ).limit(50).all()
    
    # Sammle alle eindeutigen E-Mail-Adressen
    email_addresses = set()
    for msg in email_messages:
        # Extrahiere aus sender
        if msg.sender:
            emails = extract_email_addresses(msg.sender)
            email_addresses.update(emails)
        
        # Extrahiere aus recipients
        if msg.recipients:
            emails = extract_email_addresses(msg.recipients)
            email_addresses.update(emails)
        
        # Extrahiere aus cc
        if msg.cc:
            emails = extract_email_addresses(msg.cc)
            email_addresses.update(emails)
    
    # Füge E-Mail-Adressen hinzu, die noch nicht in Kontakten sind
    for email in email_addresses:
        if query in email and email not in seen_emails:
            seen_emails.add(email)
            results.append({
                'type': 'email',
                'id': None,
                'name': '',
                'email': email,
                'phone': '',
                'display': email
            })
    
    # Sortiere Ergebnisse: Kontakte zuerst, dann E-Mail-Adressen
    # Innerhalb jeder Gruppe alphabetisch nach E-Mail
    results.sort(key=lambda x: (x['type'] == 'email', x['email'].lower()))
    
    # Begrenze auf 20 Ergebnisse
    results = results[:20]
    
    return jsonify({'results': results})
