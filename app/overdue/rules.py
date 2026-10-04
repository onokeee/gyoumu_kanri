"""期限超過通知の「実行時刻の判定・次回の送信日時」(純粋関数のみ)。

DBにもFlaskにも依存しないため、画面・スケジューラのどこからでも使える。
自動送信は営業日(月〜金で、日本の祝日・休日でない日。app/holidays.py)だけ行う。
"""
from datetime import datetime, time, timedelta

from app.holidays import is_business_day
from app.utils import parse_hhmm

# 次の営業日を探す上限(日数)。連休が続いてもこれより長くはならない
_SEARCH_DAYS = 31


def due_key(settings, now):
    """今が自動送信の実行時刻なら (日付, "HH:MM") を返す。そうでなければ None。

    自動送信が有効で、今日が営業日で、今の時刻(HH:MM)が設定と一致するとき。
    """
    if not settings.get("enabled"):
        return None
    at = parse_hhmm(settings.get("time"))
    if at is None or now.strftime("%H:%M") != at.strftime("%H:%M"):
        return None
    if not is_business_day(now.date()):
        return None
    return (now.date(), at.strftime("%H:%M"))


def next_run(settings, now):
    """次回の自動送信日時(次の営業日の設定時刻)。自動送信が無効・時刻不正なら None。

    今日が営業日で、まだ設定時刻を過ぎていなければ今日。
    当日の実行時刻の「分」の間はまだ実行中とみなし、当日の日時を返す。
    """
    if not settings.get("enabled"):
        return None
    at = parse_hhmm(settings.get("time"))
    if at is None:
        return None
    candidate = datetime.combine(now.date(), time(at.hour, at.minute))
    if candidate < now.replace(second=0, microsecond=0):
        candidate += timedelta(days=1)
    for _ in range(_SEARCH_DAYS):
        if is_business_day(candidate.date()):
            return candidate
        candidate += timedelta(days=1)
    return None
