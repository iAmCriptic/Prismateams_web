from app import db
from app.models.file import File, Folder
from app.models.user import User
from app.utils.private_files import list_view_contents, natural_name_key, natural_sort_key


def test_natural_sort_key_orders_numbered_months_and_versions():
    months = [
        '10. Oktober',
        '12. Dezember',
        '2. Februar',
        '3.März',
        '4. April',
        '5. Mai',
        '6.Juni',
        '7. Juli',
        '8. August',
        '9. September',
    ]
    assert sorted(months, key=natural_sort_key) == [
        '2. Februar',
        '3.März',
        '4. April',
        '5. Mai',
        '6.Juni',
        '7. Juli',
        '8. August',
        '9. September',
        '10. Oktober',
        '12. Dezember',
    ]

    nested = ['1.10.pdf', '1.2.pdf', '1.1.pdf', '2.1.pdf', '10.1.pdf']
    assert sorted(nested, key=natural_sort_key) == [
        '1.1.pdf',
        '1.2.pdf',
        '1.10.pdf',
        '2.1.pdf',
        '10.1.pdf',
    ]

    mixed = ['Kapitel 10', 'kapitel 2', 'Kapitel 1', 'Anhang']
    assert sorted(mixed, key=natural_sort_key) == [
        'Anhang',
        'Kapitel 1',
        'kapitel 2',
        'Kapitel 10',
    ]


def test_list_view_contents_uses_natural_sort_and_pagination(app):
    user = User(
        email='natsort@example.com',
        first_name='Nat',
        last_name='Sort',
        password_hash='hash',
    )
    db.session.add(user)
    db.session.flush()

    parent = Folder(
        name='1. Veranstaltungen 26',
        space='public',
        storage_backend='local',
        created_by=user.id,
    )
    db.session.add(parent)
    db.session.flush()

    folder_names = ['10. Oktober', '12. Dezember', '2. Februar', '3.März', '9. September']
    for name in folder_names:
        db.session.add(Folder(
            name=name,
            parent_id=parent.id,
            space='public',
            storage_backend='local',
            created_by=user.id,
        ))

    file_names = ['10_Protokoll.pdf', '2_Protokoll.pdf', '1_Protokoll.pdf']
    for idx, name in enumerate(file_names, start=1):
        db.session.add(File(
            name=name,
            original_name=name,
            file_path=f'/tmp/stored_{idx}_{name}',
            file_size=128,
            folder_id=parent.id,
            space='public',
            storage_backend='local',
            uploaded_by=user.id,
            is_current=True,
        ))
    db.session.commit()

    _, subfolders, files, _ = list_view_contents('public', parent.id, user, offset=0, limit=48)
    assert [f.name for f in subfolders] == [
        '2. Februar',
        '3.März',
        '9. September',
        '10. Oktober',
        '12. Dezember',
    ]
    assert [f.name for f in files] == [
        '1_Protokoll.pdf',
        '2_Protokoll.pdf',
        '10_Protokoll.pdf',
    ]

    # Verify pagination windowing respects natural order across page boundary
    _, page1_folders, page1_files, _ = list_view_contents('public', parent.id, user, offset=0, limit=3)
    _, page2_folders, page2_files, _ = list_view_contents('public', parent.id, user, offset=3, limit=3)
    assert [f.name for f in page1_folders] == ['2. Februar', '3.März', '9. September']
    assert page1_files == []
    assert [f.name for f in page2_folders] == ['10. Oktober', '12. Dezember']
    assert [f.name for f in page2_files] == ['1_Protokoll.pdf']


def test_natural_name_key_supports_dicts():
    items = [{'name': '10. B'}, {'name': '2. A'}]
    assert [i['name'] for i in sorted(items, key=natural_name_key)] == ['2. A', '10. B']
