from flask import Blueprint

from .admin_settings import admin_settings_bp
from .auth import auth_bp
from .context import inject_assessment_context
from .criteria import criteria_bp
from .evaluations import evaluations_bp
from .excel_uploads import excel_uploads_bp
from .general import general_bp
from .inspections import inspections_bp
from .map import map_bp
from .ranking import ranking_bp
from .rooms import rooms_bp
from .stands import stands_bp
from .users import users_bp
from .warnings import warnings_bp


assessment_bp = Blueprint("assessment", __name__, url_prefix="/assessment")

assessment_bp.register_blueprint(auth_bp)
assessment_bp.register_blueprint(admin_settings_bp)
assessment_bp.register_blueprint(users_bp)
assessment_bp.register_blueprint(stands_bp)
assessment_bp.register_blueprint(rooms_bp)
assessment_bp.register_blueprint(criteria_bp)
assessment_bp.register_blueprint(evaluations_bp)
assessment_bp.register_blueprint(warnings_bp, url_prefix="/warnings")
assessment_bp.register_blueprint(inspections_bp)
assessment_bp.register_blueprint(ranking_bp)
assessment_bp.register_blueprint(general_bp)
assessment_bp.register_blueprint(excel_uploads_bp)
assessment_bp.register_blueprint(map_bp)


@assessment_bp.app_context_processor
def _assessment_context():
    return inject_assessment_context()
