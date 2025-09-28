# tbot_web/py/users_web.py
# Admin user management (CRUD) with RBAC: ensures atomic Fernet key/secret rotation post-user changes per RIGD spec

from flask import Blueprint, request, render_template, flash, redirect, url_for, session
from tbot_web.support.auth_web import get_db_connection, upsert_user, delete_user, get_user_by_username, list_users, rbac_required
from pathlib import Path

from tbot_bot.support.config_fetch import get_live_config_for_rotation
from tbot_bot.config.provisioning_helper import rotate_all_keys_and_secrets
from tbot_bot.support.bootstrap_utils import is_first_bootstrap

users_blueprint = Blueprint("users_web", __name__, url_prefix="/users")


@users_blueprint.route("/", methods=["GET"])
@rbac_required("admin")
def users_list():
    users = list_users()
    return render_template("users.html", users=users)

@users_blueprint.route("/edit/<username>", methods=["GET", "POST"])
@rbac_required("admin")
def edit_user(username):
    user = get_user_by_username(username)
    if not user:
        flash("User not found.", "error")
        return redirect(url_for("users_web.users_list"))
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        role = request.form.get("role", "").strip()
        password = request.form.get("password", "").strip()
        try:
            # Only update password if provided
            upsert_user(username, password if password else "PLACEHOLDER_DO_NOT_USE", email, role=role if role else user.get("role", "viewer"))
            # Only rotate keys/secrets post-bootstrap
            if not is_first_bootstrap():
                config = get_live_config_for_rotation()
                if config:
                    rotate_all_keys_and_secrets(config)
            flash("User updated successfully.", "success")
            return redirect(url_for("users_web.users_list"))
        except Exception as e:
            flash(f"Error updating user: {e}", "error")
            return render_template("edit_user.html", user=user)
    return render_template("edit_user.html", user=user)

@users_blueprint.route("/delete/<username>", methods=["POST"])
@rbac_required("admin")
def delete_user_route(username):
    try:
        delete_user(username)
        # Only rotate keys/secrets post-bootstrap
        if not is_first_bootstrap():
            config = get_live_config_for_rotation()
            if config:
                rotate_all_keys_and_secrets(config)
        flash("User deleted successfully.", "success")
    except Exception as e:
        flash(f"Error deleting user: {e}", "error")
    return redirect(url_for("users_web.users_list"))
