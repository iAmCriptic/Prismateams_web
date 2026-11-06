from flask import Blueprint

booking_personal_bp = Blueprint(
    'booking_personal',
    __name__,
    template_folder='../../templates/booking_personal',
    static_folder='../../static'
)

from . import views, public, mail

