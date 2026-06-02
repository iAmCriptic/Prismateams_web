"""Idempotente Schema- und Datenmigration für das Bewertungsmodul."""

from sqlalchemy import inspect, text

from app import db
from app.models.assessment import (
    AssessmentCriterion,
    AssessmentEvaluation,
    AssessmentList,
    AssessmentStand,
    AssessmentStandType,
    AssessmentVisitorEvaluation,
    AssessmentWarning,
)


def _column_names(inspector, table):
    if table not in inspector.get_table_names():
        return set()
    return {col["name"] for col in inspector.get_columns(table)}


def _add_column(connection, dialect, table, column, col_type_mysql, col_type_sqlite=None):
    sqlite_type = col_type_sqlite or col_type_mysql
    col_def = col_type_sqlite if dialect == "sqlite" else col_type_mysql
    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}"))


def _drop_index_if_exists(connection, dialect, table, index_name):
    try:
        if dialect == "sqlite":
            connection.execute(text(f"DROP INDEX IF EXISTS {index_name}"))
        else:
            connection.execute(text(f"ALTER TABLE {table} DROP INDEX {index_name}"))
    except Exception:
        pass


def _drop_legacy_floor_plan_tables(connection, inspector):
    for table in ("ass_floor_plan_objects", "ass_floor_plans"):
        if table in inspector.get_table_names():
            try:
                connection.execute(text(f"DROP TABLE {table}"))
                print(f"[OK] Legacy-Tabelle {table} entfernt")
            except Exception as exc:
                print(f"[WARNUNG] {table} konnte nicht gelöscht werden: {exc}")


def run_assessment_migrations():
    inspector = inspect(db.engine)
    dialect = db.engine.dialect.name
    tables = set(inspector.get_table_names())

    with db.engine.begin() as connection:
        _drop_legacy_floor_plan_tables(connection, inspect(db.engine))

    if "ass_stands" in tables:
        cols = _column_names(inspector, "ass_stands")
        if "stand_type_id" not in cols:
            with db.engine.begin() as connection:
                _add_column(connection, dialect, "ass_stands", "stand_type_id", "INT NULL")

    if "ass_criteria" in tables:
        cols = _column_names(inspector, "ass_criteria")
        if "list_id" not in cols:
            with db.engine.begin() as connection:
                _add_column(connection, dialect, "ass_criteria", "list_id", "INT NULL")
            _drop_index_if_exists(db.engine.connect(), dialect, "ass_criteria", "name")

    for table, columns in (
        ("ass_evaluations", [("list_id", "INT NULL"), ("subject_id", "INT NULL")]),
        ("ass_visitor_evaluations", [("list_id", "INT NULL"), ("subject_id", "INT NULL")]),
        ("ass_warnings", [("list_id", "INT NULL"), ("subject_id", "INT NULL")]),
    ):
        if table not in tables:
            continue
        cols = _column_names(inspector, table)
        for col_name, col_def in columns:
            if col_name not in cols:
                with db.engine.begin() as connection:
                    _add_column(connection, dialect, table, col_name, col_def)

    if "ass_evaluations" in tables:
        cols = _column_names(inspector, "ass_evaluations")
        if "stand_id" in cols:
            with db.engine.begin() as connection:
                if dialect == "mysql":
                    try:
                        connection.execute(text(
                            "ALTER TABLE ass_evaluations MODIFY stand_id INT NULL"
                        ))
                    except Exception:
                        pass
                _drop_index_if_exists(connection, dialect, "ass_evaluations", "uq_ass_eval_user_stand")

    if "ass_visitor_evaluations" in tables:
        with db.engine.begin() as connection:
            _drop_index_if_exists(connection, dialect, "ass_visitor_evaluations", "uq_ass_visitor_stand")

    _migrate_default_data()


def _migrate_default_data():
    default_type = AssessmentStandType.query.filter_by(name="Allgemein").first()
    if not default_type:
        default_type = AssessmentStandType(name="Allgemein", sort_order=0)
        db.session.add(default_type)
        db.session.flush()

    for stand in AssessmentStand.query.filter(AssessmentStand.stand_type_id.is_(None)).all():
        stand.stand_type_id = default_type.id

    default_list = AssessmentList.query.filter_by(slug="hauptbewertung").first()
    if not default_list:
        ranking_mode = "standard"
        ranking_sort = "total"
        from app.models.assessment import AssessmentAppSetting

        mode_setting = AssessmentAppSetting.query.filter_by(setting_key="ranking_active_mode").first()
        sort_setting = AssessmentAppSetting.query.filter_by(setting_key="ranking_sort_mode").first()
        if mode_setting and mode_setting.setting_value:
            ranking_mode = mode_setting.setting_value
        if sort_setting and sort_setting.setting_value:
            ranking_sort = sort_setting.setting_value

        default_list = AssessmentList(
            name="Hauptbewertung",
            slug="hauptbewertung",
            description="Standard-Bewertungsliste (migriert)",
            subject_mode="stand",
            is_active=True,
            sort_order=0,
            enable_visitor_rating=True,
            ranking_mode=ranking_mode,
            ranking_sort=ranking_sort,
        )
        default_list.set_stand_type_id_list([])
        db.session.add(default_list)
        db.session.flush()

    for criterion in AssessmentCriterion.query.filter(AssessmentCriterion.list_id.is_(None)).all():
        criterion.list_id = default_list.id

    for evaluation in AssessmentEvaluation.query.filter(AssessmentEvaluation.list_id.is_(None)).all():
        evaluation.list_id = default_list.id

    for visitor in AssessmentVisitorEvaluation.query.filter(AssessmentVisitorEvaluation.list_id.is_(None)).all():
        visitor.list_id = default_list.id

    for warning in AssessmentWarning.query.filter(AssessmentWarning.list_id.is_(None)).all():
        warning.list_id = default_list.id

    db.session.commit()
