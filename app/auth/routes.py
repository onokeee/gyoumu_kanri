"""認証(ログイン/ログアウト)のルーティング。"""
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user

from app.extensions import db
from app.models.user import User
from app.auth.ldap_client import authenticate

auth_bp = Blueprint("auth", __name__)


def _ensure_local_user(info):
    """固定ローカルアカウント(admin 等)は、アプリ未登録でも用意する(初期・緊急用)。"""
    user = User.query.filter_by(username=info["username"]).first()
    if user is None:
        user = User(username=info["username"])
        db.session.add(user)
    user.display_name = info["display_name"]
    user.role = info["role"]
    user.is_active = True
    db.session.commit()
    return user


def _match_registered_user(info):
    """LDAP認証済みのIDを『アプリに登録済み・有効』と突き合わせる。

    アプリ未登録 or 無効化 なら None(=ログイン不可)。
    登録済みなら氏名(display_name)は LDAP を正として同期し、
    役割(role)はアプリの登録(マネージャーがメンバー管理で設定)を正として維持する。
    """
    user = User.query.filter_by(username=info["username"]).first()
    if user is None or not user.is_active:
        return None
    user.display_name = info["display_name"]
    db.session.commit()
    return user


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    # すでにログイン済みならトップへ
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        # ① LDAP(＋固定ローカル)で本人確認(実在するユーザーか＋パスワード)
        info = authenticate(username, password)
        if info is None:
            flash("IDまたはパスワードが正しくありません。", "danger")
            return render_template("auth/login.html", username=username)

        if info.get("source") == "local":
            # 固定ローカル管理者は常に許可(アプリ登録チェック免除)
            user = _ensure_local_user(info)
        else:
            # ② LDAPで実在確認できても、アプリ未登録/無効のIDはログインさせない
            user = _match_registered_user(info)
            if user is None:
                flash(
                    "このIDはアプリに登録されていません(または無効化されています)。"
                    "マネージャーにアカウント登録を依頼してください。", "danger"
                )
                return render_template("auth/login.html", username=username)

        login_user(user)
        flash(f"ようこそ、{user.display_name} さん。", "success")

        # ログイン前にアクセスしようとしていたページがあればそこへ戻す
        next_page = request.args.get("next")
        if next_page and next_page.startswith("/"):
            return redirect(next_page)
        return redirect(url_for("main.dashboard"))

    return render_template("auth/login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("ログアウトしました。", "info")
    return redirect(url_for("auth.login"))
