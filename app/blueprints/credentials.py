from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from app import db
from app.models.credential import Credential
from cryptography.fernet import Fernet
import os
import requests
from urllib.parse import urlparse

credentials_bp = Blueprint('credentials', __name__)


def get_encryption_key():
    """Get or create encryption key for credentials."""
    key_file = 'credential_key.key'
    if os.path.exists(key_file):
        with open(key_file, 'rb') as f:
            return f.read()
    else:
        key = Fernet.generate_key()
        with open(key_file, 'wb') as f:
            f.write(key)
        return key


def get_favicon_url(website_url):
    """Get favicon URL for a website."""
    try:
        parsed = urlparse(website_url)
        domain = f"{parsed.scheme}://{parsed.netloc}"
        
        # Try common favicon locations
        favicon_urls = [
            f"{domain}/favicon.ico",
            f"https://www.google.com/s2/favicons?domain={parsed.netloc}&sz=32",
        ]
        
        for url in favicon_urls:
            try:
                response = requests.head(url, timeout=2)
                if response.status_code == 200:
                    return url
            except:
                continue
        
        # Fallback to Google's favicon service
        return f"https://www.google.com/s2/favicons?domain={parsed.netloc}&sz=32"
    except:
        return None


@credentials_bp.route('/')
@login_required
def index():
    """List all credentials."""
    credentials = Credential.query.order_by(Credential.website_name).all()
    return render_template('credentials/index.html', credentials=credentials)


@credentials_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    """Create a new credential entry."""
    if request.method == 'POST':
        website_url = request.form.get('website_url', '').strip()
        website_name = request.form.get('website_name', '').strip()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        notes = request.form.get('notes', '').strip()
        
        if not all([website_url, website_name, username, password]):
            flash('Bitte füllen Sie alle Pflichtfelder aus.', 'danger')
            return render_template('credentials/create.html')
        
        # Get favicon
        favicon_url = get_favicon_url(website_url)
        
        # Create credential
        credential = Credential(
            website_url=website_url,
            website_name=website_name,
            username=username,
            notes=notes,
            favicon_url=favicon_url,
            created_by=current_user.id
        )
        
        # Encrypt and set password
        key = get_encryption_key()
        credential.set_password(password, key)
        
        db.session.add(credential)
        db.session.commit()
        
        flash(f'Zugangsdaten für "{website_name}" wurden gespeichert.', 'success')
        return redirect(url_for('credentials.index'))
    
    return render_template('credentials/create.html')


@credentials_bp.route('/edit/<int:credential_id>', methods=['GET', 'POST'])
@login_required
def edit(credential_id):
    """Edit a credential entry."""
    credential = Credential.query.get_or_404(credential_id)
    key = get_encryption_key()
    
    if request.method == 'POST':
        credential.website_url = request.form.get('website_url', '').strip()
        credential.website_name = request.form.get('website_name', '').strip()
        credential.username = request.form.get('username', '').strip()
        credential.notes = request.form.get('notes', '').strip()
        
        new_password = request.form.get('password', '').strip()
        if new_password:
            credential.set_password(new_password, key)
        
        # Update favicon
        credential.favicon_url = get_favicon_url(credential.website_url)
        
        db.session.commit()
        
        flash(f'Zugangsdaten für "{credential.website_name}" wurden aktualisiert.', 'success')
        return redirect(url_for('credentials.index'))
    
    # Decrypt password for display
    decrypted_password = credential.get_password(key)
    
    return render_template('credentials/edit.html', credential=credential, password=decrypted_password)


@credentials_bp.route('/delete/<int:credential_id>', methods=['POST'])
@login_required
def delete(credential_id):
    """Delete a credential entry."""
    credential = Credential.query.get_or_404(credential_id)
    
    db.session.delete(credential)
    db.session.commit()
    
    flash(f'Zugangsdaten für "{credential.website_name}" wurden gelöscht.', 'success')
    return redirect(url_for('credentials.index'))


@credentials_bp.route('/view-password/<int:credential_id>')
@login_required
def view_password(credential_id):
    """View decrypted password (AJAX endpoint)."""
    credential = Credential.query.get_or_404(credential_id)
    key = get_encryption_key()
    
    try:
        password = credential.get_password(key)
        return jsonify({'password': password})
    except Exception as e:
        return jsonify({'error': 'Fehler beim Entschlüsseln des Passworts'}), 500



