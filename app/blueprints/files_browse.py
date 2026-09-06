"""Browse-Hot-Path for the files module."""

from flask import flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required

from app.models.file import File, Folder
from app.models.settings import SystemSettings
from app.models.user import User
from app.utils.access_control import check_module_access
from app.utils.file_storage_limits import get_global_max_file_size, resolve_limits_for_user
from app.utils.private_files import (
    ensure_personal_root,
    ensure_team_root,
    folder_is_under_personal_root,
    is_private_folders_enabled,
    is_team_folders_enabled,
    list_folder_favorites,
    list_view_contents,
    normalize_view,
    parse_team_id,
    user_file_teams,
    user_may_use_file_team,
)


def register_browse_routes(files_bp):
    @files_bp.route('/', defaults={'folder_id': None}, endpoint='index')
    @files_bp.route('/folder/<int:folder_id>')
    @login_required
    @check_module_access('module_files')
    def browse_folder(folder_id=None):
        """Browse the files root or a specific folder."""
        from app.blueprints.files import FILES_BROWSE_PAGE_SIZE, _is_guest_user, _paginate_browse_items

        accessible_folder_ids = set()
        is_guest = _is_guest_user()
        private_enabled = is_private_folders_enabled() and not is_guest
        team_enabled = is_team_folders_enabled() and not is_guest
        spaces_enabled = (private_enabled or team_enabled)
        files_team_id = parse_team_id(request.args.get('team_id')) if not is_guest else None
        # Gäste behalten die alte Root-Ansicht ohne Sidebar-Nav
        if is_guest:
            files_view = None
        else:
            files_view = normalize_view(
                request.args.get('view'),
                private_enabled=private_enabled,
                team_enabled=team_enabled,
            )

        # Öffentliche / Team-Ordner landen ohne ?view= default in Ablage → kein Zugriff.
        if not is_guest and not request.args.get('view') and folder_id:
            target = Folder.query.get(folder_id)
            if target and target.deleted_at is None:
                if team_enabled and ((getattr(target, 'space', None) or '') == 'team' or getattr(target, 'is_team_root', False)):
                    tid = getattr(target, 'team_id', None)
                    if tid:
                        return redirect(url_for('files.browse_folder', folder_id=folder_id, view='team', team_id=tid))
                if private_enabled and files_view == 'ablage':
                    personal_root = ensure_personal_root(current_user.id)
                    if not folder_is_under_personal_root(target, personal_root.id):
                        return redirect(url_for('files.browse_folder', folder_id=folder_id, view='public'))

        if files_view == 'team':
            if not files_team_id:
                files_team_id = parse_team_id(session.get('files_last_team_id'))
            if not user_may_use_file_team(current_user, files_team_id):
                flash('Sie haben keinen Zugriff auf diese Team-Ablage.', 'danger')
                fallback = 'ablage' if private_enabled else 'public'
                return redirect(url_for('files.index', view=fallback))

        if not is_guest and files_view:
            session['files_last_view'] = files_view
            session['files_last_folder_id'] = folder_id
            if files_view == 'team' and files_team_id:
                session['files_last_team_id'] = files_team_id
            elif files_view != 'team':
                session.pop('files_last_team_id', None)

        # Gast-Accounts: Nur Freigabelinks anzeigen
        if is_guest:
            from app.utils.access_control import get_guest_accessible_items, get_guest_directly_shared_folders
            accessible_files, accessible_folders = get_guest_accessible_items(current_user)
            accessible_folder_ids = {folder.id for folder in accessible_folders}
        
            # Filtere nach aktuell angezeigtem Ordner
            current_folder = None
            if folder_id:
                # Prüfe ob Gast Zugriff auf diesen Ordner hat
                folder_with_access = next((f for f in accessible_folders if f.id == folder_id), None)
                if not folder_with_access:
                    flash('Sie haben keinen Zugriff auf diesen Ordner.', 'danger')
                    return redirect(url_for('files.index'))
                current_folder = folder_with_access
        
            # Zeige nur zugängliche Unterordner des aktuellen Ordners
            if folder_id:
                subfolders = [f for f in accessible_folders if f.parent_id == folder_id]
            else:
                # Root zeigt explizit freigegebene Ordner als Einstiegspunkte
                # sowie Fallback-Roots (wenn ein Parent nicht zugänglich ist).
                directly_shared_folders = get_guest_directly_shared_folders(current_user)
                root_like_folders = [
                    f for f in accessible_folders
                    if f.parent_id is None or f.parent_id not in accessible_folder_ids
                ]
                unique_folders = {}
                for folder in directly_shared_folders + root_like_folders:
                    unique_folders[folder.id] = folder
                subfolders = list(unique_folders.values())
        
            # Zeige nur zugängliche Dateien im aktuellen Ordner
            # (get_guest_accessible_items gibt bereits alle Dateien inkl. Unterordnern zurück)
            if folder_id:
                files = [f for f in accessible_files if f.folder_id == folder_id]
            else:
                # Root zeigt auch direkt freigegebene Dateien, wenn ihr Ordner nicht zugänglich ist
                files = [
                    f for f in accessible_files
                    if f.folder_id is None or f.folder_id not in accessible_folder_ids
                ]
        
            # Sortiere
            subfolders = sorted(subfolders, key=lambda x: x.name)
            files = sorted(files, key=lambda x: x.name)
        elif spaces_enabled:
            if files_view == 'ablage':
                ensure_personal_root(current_user.id)
            if files_view == 'team' and files_team_id:
                ensure_team_root(files_team_id, current_user.id)
            result = list_view_contents(files_view, folder_id, current_user, team_id=files_team_id)
            current_folder, subfolders, files, _view_key = result
            if current_folder == 'forbidden':
                flash('Sie haben keinen Zugriff auf diesen Ordner.', 'danger')
                view_kwargs = {'view': files_view}
                if files_view == 'team' and files_team_id:
                    view_kwargs['team_id'] = files_team_id
                return redirect(url_for('files.index', **view_kwargs))
        else:
            # Ohne Private-/Team-Ordner: Public-Baum + optional Papierkorb (Sidebar bleibt)
            current_folder = None
            if files_view == 'trash':
                subfolders = (
                    Folder.query.filter(
                        Folder.deleted_at.isnot(None),
                        Folder.created_by == current_user.id,
                        Folder.is_personal_root.is_(False),
                        Folder.is_team_root.is_(False),
                    )
                    .order_by(Folder.deleted_at.desc())
                    .all()
                )
                files = (
                    File.query.filter(
                        File.deleted_at.isnot(None),
                        File.uploaded_by == current_user.id,
                        File.is_current.is_(True),
                    )
                    .order_by(File.deleted_at.desc())
                    .all()
                )
            else:
                if folder_id:
                    current_folder = Folder.query.get_or_404(folder_id)
                    if current_folder.deleted_at is not None:
                        flash('Dieser Ordner wurde gelöscht.', 'warning')
                        return redirect(url_for('files.index', view=files_view or 'public'))
                    if (getattr(current_folder, 'space', None) or '') == 'team' or getattr(current_folder, 'is_team_root', False):
                        flash('Sie haben keinen Zugriff auf diesen Ordner.', 'danger')
                        return redirect(url_for('files.index', view='public'))

                # Get subfolders
                if folder_id:
                    subfolders = Folder.query.filter(
                        Folder.parent_id == folder_id,
                        Folder.deleted_at.is_(None),
                        Folder.is_personal_root.is_(False),
                        Folder.is_team_root.is_(False),
                    ).order_by(Folder.name).all()
                else:
                    subfolders = Folder.query.filter(
                        Folder.parent_id.is_(None),
                        Folder.deleted_at.is_(None),
                        Folder.is_personal_root.is_(False),
                        Folder.is_team_root.is_(False),
                        Folder.space != 'team',
                    ).order_by(Folder.name).all()

                if folder_id:
                    files = File.query.filter(
                        File.folder_id == folder_id,
                        File.is_current.is_(True),
                        File.deleted_at.is_(None),
                    ).order_by(File.name).all()
                else:
                    files = File.query.filter(
                        File.folder_id.is_(None),
                        File.is_current.is_(True),
                        File.deleted_at.is_(None),
                        File.space != 'team',
                    ).order_by(File.name).all()

                if files is None:
                    files = []
    
        # Build breadcrumbs starting from root to current folder
        breadcrumb_folders = []
        view_kwargs = {'view': files_view} if files_view else {}
        if files_view == 'team' and files_team_id:
            view_kwargs['team_id'] = files_team_id
        if current_folder and current_folder != 'forbidden':
            ancestors = []
            node = current_folder
            personal_root_id = None
            team_root_id = None
            if private_enabled and files_view == 'ablage':
                personal_root_id = ensure_personal_root(current_user.id).id
            if team_enabled and files_view == 'team' and files_team_id:
                team_root = ensure_team_root(files_team_id, current_user.id)
                team_root_id = team_root.id if team_root else None
            while node:
                if personal_root_id and node.id == personal_root_id:
                    break
                if team_root_id and node.id == team_root_id:
                    break
                ancestors.append(node)
                node = node.parent
            ancestors.reverse()
            if _is_guest_user():
                ancestors = [folder for folder in ancestors if folder.id in accessible_folder_ids]
            breadcrumb_folders = [
                {
                    'id': folder.id,
                    'name': folder.name,
                    'url': url_for('files.browse_folder', folder_id=folder.id, **view_kwargs)
                }
                for folder in ancestors
            ]

        # Feature flags
        dropbox_setting = SystemSettings.query.filter_by(key='files_dropbox_enabled').first()
        sharing_setting = SystemSettings.query.filter_by(key='files_sharing_enabled').first()
        files_dropbox_enabled = (dropbox_setting and str(dropbox_setting.value).lower() == 'true') or False
        files_sharing_enabled = (sharing_setting and str(sharing_setting.value).lower() == 'true') or False

        from app.utils.document_formats import get_create_type_map
        create_types = get_create_type_map()
    
        # Check ONLYOFFICE availability
        from app.utils.onlyoffice import is_onlyoffice_enabled
        onlyoffice_available = is_onlyoffice_enabled()

        # Lazy loading: Text-Previews nicht mehr synchron vom Disk lesen (P17).
        # Media/PDF laden clientseitig per IntersectionObserver.
        browse_offset = max(0, request.args.get('offset', 0, type=int) or 0)
        subfolders, files, files_has_more, files_total_count = _paginate_browse_items(
            subfolders, files, offset=browse_offset, limit=FILES_BROWSE_PAGE_SIZE
        )
        file_preview_map = {}
        file_preview_html_map = {}

        # Uploader names for list view
        # Eager-load uploaders for list view (relationship) + map fallback
        for f in files:
            try:
                _ = f.uploader
            except Exception:
                pass
        uploader_ids = {f.uploaded_by for f in files if f.uploaded_by}
        creator_ids = {folder.created_by for folder in subfolders if folder.created_by}
        user_ids = uploader_ids | creator_ids
        users_by_id = {
            u.id: u for u in User.query.filter(User.id.in_(user_ids)).all()
        } if user_ids else {}

        root_url = url_for('files.index', **view_kwargs) if view_kwargs else url_for('files.index')

        folder_favorites = []
        favorite_folder_ids = set()
        if not is_guest:
            folder_favorites = list_folder_favorites(current_user, url_for)
            favorite_folder_ids = {f['id'] for f in folder_favorites}

        nav_teams = user_file_teams(current_user) if team_enabled else []
        files_team_name = None
        if files_view == 'team' and files_team_id:
            files_team_name = next((t.name for t in nav_teams if t.id == files_team_id), None)

        from app.utils.webdav import is_webdav_enabled
        files_webdav_enabled = is_webdav_enabled()
        webdav_url = f"{request.url_root.rstrip('/')}/webdav"

        return render_template(
            'files/index.html',
            current_folder=current_folder if current_folder != 'forbidden' else None,
            subfolders=subfolders,
            files=files,
            file_preview_map=file_preview_map,
            file_preview_html_map=file_preview_html_map,
            files_browse_offset=browse_offset,
            files_browse_next_offset=browse_offset + len(subfolders) + len(files),
            files_has_more=files_has_more,
            files_total_count=files_total_count,
            files_dropbox_enabled=files_dropbox_enabled,
            files_sharing_enabled=files_sharing_enabled,
            files_private_folders_enabled=private_enabled,
            files_team_folders_enabled=team_enabled,
            files_webdav_enabled=files_webdav_enabled,
            webdav_url=webdav_url,
            files_nav_teams=nav_teams,
            files_team_id=files_team_id,
            files_team_name=files_team_name,
            files_view=files_view,
            create_types=create_types,
            onlyoffice_available=onlyoffice_available,
            breadcrumb_folders=breadcrumb_folders,
            users_by_id=users_by_id,
            files_root_url=root_url,
            is_trash_view=(files_view == 'trash'),
            folder_favorites=folder_favorites,
            favorite_folder_ids=favorite_folder_ids,
            files_max_upload_bytes=(
                resolve_limits_for_user(current_user.id)['max_file_size']
                if not is_guest else get_global_max_file_size()
            ),
        )


