"""認証(ログイン/ログアウト)のルーティング。

app/auth/ldap_client.py は本番環境ごとに差し替えるファイルなので、ここからは
authenticate() と _LOCAL_ACCOUNTS(表示名・役割)しか使わない(中身には依存しない)。
固定ローカル管理者(admin)のパスワードは、instance/config.py の ADMIN_PASSWORD で
先に確認する(設定が空のときだけ ldap_client.py の判定に任せる)。
"""
import hmac

from flask import Blueprint, current_app, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user

from app.extensions import db
from app.models.user import User, ROLE_MANAGER
from app.auth import ldap_client
from app.auth.ldap_client import authenticate

auth_bp = Blueprint("auth", __name__)

ADMIN_USERNAME = "admin"


def _check_config_admin(username, password):
    """instance/config.py の ADMIN_PASSWORD で固定ローカル管理者を確認する。

    戻り値: (確認したか, 認証結果)
      - ADMIN_PASSWORD が空、または admin 以外のID → (False, None) = ldap_client.py に任せる
      - admin で一致 → (True, 認証結果の dict)
      - admin で不一致 → (True, None) = ログイン不可(ldap_client.py 側の既定パスワードは使わせない)
    """
    expected = str(current_app.config.get("ADMIN_PASSWORD") or "")
    if not expected or username != ADMIN_USERNAME:
        return False, None
    # 比較時間から内容を推測されないよう hmac.compare_digest を使う
    if not hmac.compare_digest(str(password or "").encode("utf-8"), expected.encode("utf-8")):
        return True, None
    local = getattr(ldap_client, "_LOCAL_ACCOUNTS", {}).get(ADMIN_USERNAME, {})
    return True, {
        "username": ADMIN_USERNAME,
        "display_name": local.get("display_name") or "管理者",
        "role": local.get("role") or ROLE_MANAGER,
        "source": "local",
    }


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

        # ① 本人確認: 固定ローカル管理者は instance/config.py で、
        #    それ以外は ldap_client.py の authenticate()(LDAP＋固定ローカル)で確認する
        checked, info = _check_config_admin(username, password)
        if not checked:
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
