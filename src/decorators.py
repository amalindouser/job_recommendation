from functools import wraps
from flask import flash, redirect, url_for
from flask_login import current_user


def role_required(role):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                flash("Silakan login terlebih dahulu.", "warning")
                return redirect(url_for('login'))
            if current_user.role != role:
                flash(f"Anda tidak memiliki akses ke halaman ini. Role Anda: {current_user.role}", "error")
                return redirect(url_for('landing'))
            return f(*args, **kwargs)
        return wrapper
    return decorator


def employer_required(f):
    return role_required('employer')(f)


def job_seeker_required(f):
    return role_required('job_seeker')(f)
