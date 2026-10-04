"""アプリ共通の小さなヘルパー関数。

複数のBlueprintから再利用する純粋関数を置く。
"""
from datetime import datetime


def parse_date(value):
    """フォームの日付文字列(YYYY-MM-DD)をdateに変換する。空・不正ならNone。

    tasks / leaves で共通利用する。
    """
    value = (value or "").strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_hhmm(value):
    """"HH:MM"(または "H:MM")を datetime.time に変換する。不正なら None。

    週報・期限超過通知の送信時刻で共通利用する。
    """
    try:
        return datetime.strptime((value or "").strip(), "%H:%M").time()
    except (TypeError, ValueError):
        return None


def get_active_users():
    """有効なユーザーを表示名順で取得する(担当者・受信者の選択肢用)。"""
    from app.models.user import User

    return User.query.filter_by(is_active=True).order_by(User.display_name).all()
