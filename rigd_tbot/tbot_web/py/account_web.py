# tbot_web/py/account_web.py
# User self-service account management: update email and password; authenticated users only; 100% spec compliant

from flask import Blueprint, request, render_template, flash, redirect, url_for, session
from tbot_web.py.login_web import login_required
from tbot_web.support.auth_web import get_user_by_username, upsert_user
from tbot_bot.support.config_fetch import get_live_config_for_rotation
from tbot_bot.config.provisioning_helper import rotate_all_keys_and_secrets
from tbot_bot.support.bootstrap_utils import is_first_bootstrap

account_blueprint = Blueprint("account_web", __name__, url_prefix="/account")

@account_blueprint.route("/", methods=["GET", "POST"])
@login_required
def account_page():
    username = session.get("user")
    if not username:
        flash("Session expired. Please log in again.", "error")
        return redirect(url_for("login_web.login"))
    user = get_user_by_username(username)
    if not user:
        flash("User not found.", "error")
        return redirect(url_for("login_web.login"))

    if request.method == "POST":
        new_email = request.form.get("email", "").strip()
        old_password = request.form.get("old_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        updated = False

        # Update email if changed
        if new_email and new_email != user["email"]:
            try:
                upsert_user(username, None, new_email, role=user["role"])
                updated = True
                flash("Email updated.", "success")
            except Exception as e:
                flash(f"Failed to update email: {e}", "error")

        # Update password if provided and matches confirmation
        if old_password and new_password and confirm_password:
            if new_password != confirm_password:
                flash("New passwords do not match.", "error")
            else:
                try:
                    upsert_user(username, new_password, user["email"], role=user["role"])
                    updated = True
                    flash("Password updated.", "success")
                except Exception as e:
                    flash(f"Failed to update password: {e}", "error")

        # Rotate keys and secrets after user update, post-bootstrap only
        if updated and not is_first_bootstrap():
            config = get_live_config_for_rotation()
            if config:
                rotate_all_keys_and_secrets(config)

        return redirect(url_for("account_web.account_page"))

    return render_template("account.html", user=user)
