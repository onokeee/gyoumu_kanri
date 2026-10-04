"""期限超過通知の設定フォームの入力チェックと表示用の値(システム設定の「期限超過通知」タブで使う)。

設定の画面はシステム設定(/system/settings?tab=overdue)にまとめてあり、
期限超過通知の画面(/overdue/)には実行・プレビューと状況の表示だけが残る。
保存先は settings_store.py のまま(instance/overdue_settings.json)。

  parse(form)              フォームの入力を検証する → (保存する値, エラーメッセージの一覧)
  with_input(current, v)   入力エラーで再表示するとき、保存済みの設定に入力中の値を重ねる
  context(settings)        フォームの表示に使う値
"""
from app.overdue import settings_store
from app.utils import parse_hhmm

LABEL = "期限超過通知"
SAVED_MESSAGE = "期限超過通知の設定を保存しました。"


def parse(form):
    """フォームの入力を検証する。戻り値: (values, errors)。errors が空なら保存してよい。"""
    errors = []
    values = {"enabled": form.get("enabled") == "1"}

    at = parse_hhmm(form.get("time"))
    if at is not None:
        values["time"] = at.strftime("%H:%M")
    else:
        errors.append("送信する時刻を「時:分」（例: 05:00）で入力してください。")

    raw_count = (form.get("comment_count") or "").strip()
    count = int(raw_count) if raw_count.isdecimal() else None
    if settings_store.valid_comment_count(count):
        values["comment_count"] = count
    else:
        errors.append("表示するコメント件数は{}〜{}の数字で入力してください。".format(
            settings_store.COMMENT_COUNT_MIN, settings_store.COMMENT_COUNT_MAX))
    return values, errors


def with_input(current, values):
    """保存済みの設定に入力中の値を重ねる(入力エラー時の再表示用。保存はしない)。"""
    current.update(values)
    return current


def context(settings):
    """期限超過通知の設定フォームの表示に使う値。"""
    return {
        "settings": settings,
        "comment_min": settings_store.COMMENT_COUNT_MIN,
        "comment_max": settings_store.COMMENT_COUNT_MAX,
    }
