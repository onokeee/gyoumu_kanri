"""LDAP認証クライアント(現在はダミー実装)。

★将来の差し替えポイント★
本番では、ここの authenticate() 内の「社内LDAP-API」ブロックを実リクエストに置き換える。
呼び出し側(auth/routes.py)は authenticate() の戻り値の形だけに依存しているので、
この関数の中身を差し替えるだけで本番認証に移行できる。

戻り値の仕様:
  認証成功 -> dict(username, display_name, role, source)
  認証失敗 -> None
"""
import os

from app.models.user import ROLE_MANAGER, ROLE_MEMBER

# -----------------------------------------------------------------------------
# 固定ローカルアカウント(社内情報連携=LDAPとは独立に常に有効)
# 本番でLDAPに差し替えても残す。初期設定・緊急時用の管理者。
# パスワードは環境変数 ADMIN_PASSWORD で上書き可(本番では必ず .env で設定・変更する)。
# -----------------------------------------------------------------------------
_LOCAL_ACCOUNTS = {
    "admin": {
        "password": os.environ.get("ADMIN_PASSWORD", "onode001"),
        "display_name": "管理 太郎",
        "role": ROLE_MANAGER,
    },
}

# -----------------------------------------------------------------------------
# ダミーユーザー(本番LDAP導入までの動作確認用)
# パスワードはすべて "password"。本番では使われない。
# -----------------------------------------------------------------------------
_DUMMY_USERS = {
    "kacho": {
        "password": "password",
        "display_name": "マネージャー 大輔",
        "role": ROLE_MANAGER,
    },
    "leader": {
        "password": "password",
        "display_name": "班長 花子",
        "role": ROLE_MEMBER,
    },
    "yamada": {
        "password": "password",
        "display_name": "山田 一郎",
        "role": ROLE_MEMBER,
    },
    "suzuki": {
        "password": "password",
        "display_name": "鈴木 二郎",
        "role": ROLE_MEMBER,
    },
    "tanaka": {
        "password": "password",
        "display_name": "田中 三郎",
        "role": ROLE_MEMBER,
    },
}


def authenticate(username, password):
    """ユーザー名とパスワードを検証する。

    ①固定ローカルアカウント(社内情報連携とは独立) → ②社内LDAP-API(現状ダミー) の順。
    戻り値には source("local"=固定ローカル / "ldap"=社内LDAP)を含める。
    ログイン側は source が "ldap" のとき、アプリ登録済みかを突き合わせて可否判定する。
    本番では下記②を社内LDAP-APIへの問い合わせに置き換える(①はそのまま残す):

        import requests
        resp = requests.post(LDAP_API_URL, json={"id": username, "password": password})
        if resp.status_code == 200:
            data = resp.json()
            return {
                "username": username,
                "display_name": data["name"],
                "role": _map_role(data),   # LDAPの属性から役割を決定
                "source": "ldap",
            }
        return None
    """
    username = (username or "").strip()

    # ① 固定ローカルアカウント(LDAP差し替え後も常に有効。アプリ登録チェックは免除)
    local = _LOCAL_ACCOUNTS.get(username)
    if local and password == local["password"]:
        return {
            "username": username,
            "display_name": local["display_name"],
            "role": local["role"],
            "source": "local",
        }

    # ② 社内LDAP-API(現状はダミー)。本番はこのブロックを差し替える。
    info = _DUMMY_USERS.get(username)
    if info and password == info["password"]:
        return {
            "username": username,
            "display_name": info["display_name"],
            "role": info["role"],
            "source": "ldap",
        }
    return None
