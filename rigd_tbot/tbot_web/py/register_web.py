# tbot_web/py/register_web.py

from flask import Blueprint, render_template, request, redirect, url_for, flash
from tbot_web.support.auth_web import upsert_user, user_exists

register_blueprint = Blueprint("register_web", __name__)

@register_blueprint.route("/register", methods=["GET", "POST"])
def register():
    if user_exists():
        flash("Admin user already exists. Please log in.", "info")
        return redirect(url_for("login_web.login"))
    username = request.form.get("username", "")
    email = request.form.get("email", "")
    if request.method == "POST":
        password = request.form.get("userpassword", "")
        password2 = request.form.get("userpassword2", "")
        if not username or not email or not password:
            flash("All fields are required.", "error")
            return render_template("register.html", username=username, email=email)
        if password != password2:
            flash("Passwords do not match.", "error")
            return render_template("register.html", username=username, email=email)
        try:
            upsert_user(username, password, email)
            flash("Admin user created successfully. Please log in.", "success")
            return redirect(url_for("login_web.login"))
        except Exception as e:
            flash(f"Error creating user: {e}", "error")
            return render_template("register.html", username=username, email=email)
    return render_template("register.html", username=username, email=email)
