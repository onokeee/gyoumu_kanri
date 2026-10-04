"""週報の設定フォームの入力チェックと表示用の値(システム設定の「週報」タブで使う)。

設定の画面はシステム設定(/system/settings?tab=weekly)にまとめてあり、
週報の画面(/weekly/)には実行と状況の表示だけが残る。保存先は settings_store.py のまま
(instance/weekly_settings.json)。

  parse(form)              フォームの入力を検証する → (保存する値, エラーメッセージの一覧)
  with_input(current, v)   入力エラーで再表示するとき、保存済みの設定に入力中の値を重ねる
  context(settings)        フォームの表示に使う値
"""
from datetime import date

from app.utils import get_active_users
from app.weekly import settings_store
from app.weekly.rules import (
    PERIOD_RULES,
    PLACEHOLDER_HELP,
    SAMPLE_PLACEHOLDER_HELP,
    WEEKDAY_LABELS,
    parse_hhmm,
    preview_names,
)

LABEL = "週報"
SAVED_MESSAGE = "週報の設定を保存しました。"


def _text(form, name, single_line=False):
    """フォームのテキスト(改行を統一。1行項目は改行を除く)。"""
    value = (form.get(name) or "").replace("\r\n", "\n").replace("\r", "\n")
    if single_line:
        value = " ".join(value.split("\n")).strip()
    return value


def parse(form):
    """フォームの入力を検証する。戻り値: (values, errors)。errors が空なら保存してよい。"""
    errors = []
    values = {"enabled": form.get("enabled") == "1"}

    weekday = form.get("weekday", "")
    if weekday.isdecimal() and 0 <= int(weekday) <= 6:
        values["weekday"] = int(weekday)
    else:
        errors.append("送信する曜日を選択してください。")

    at = parse_hhmm(form.get("time"))
    if at is not None:
        values["time"] = at.strftime("%H:%M")
    else:
        errors.append("送信する時刻を「時:分」（例: 08:00）で入力してください。")

    rule = form.get("period_rule", "")
    if rule in PERIOD_RULES:
        values["period_rule"] = rule
    else:
        errors.append("対象期間のルールを選択してください。")

    # 対象者のチェックボックスの値は「ユーザーID:ログインID」(画面表示後のID再利用による取り違え防止)
    active = {u.id: u for u in get_active_users()}
    chosen = {}
    invalid = False
    for raw in form.getlist("target_user_ids"):
        user_id, _sep, username = raw.partition(":")
        user = active.get(int(user_id)) if user_id.isdecimal() else None
        if user is None or user.username != username:
            invalid = True
            continue
        chosen[user.id] = user.username
    if invalid:
        errors.append("対象者に有効でないユーザーが含まれています。画面を開き直して選び直してください。")
    values["target_user_ids"] = sorted(chosen)
    values["target_usernames"] = {str(i): name for i, name in chosen.items()}

    for key in ("team_sample", "person_sample", "guidelines", "mail_body"):
        values[key] = _text(form, key).strip("\n")
    values["filename_pattern"] = _text(form, "filename_pattern", single_line=True)
    values["subject_pattern"] = _text(form, "subject_pattern", single_line=True)
    if not values["filename_pattern"]:
        errors.append("ファイル名のパターンを入力してください。")
    if not values["subject_pattern"]:
        errors.append("メール件名のパターンを入力してください。")
    for key, label in (("team_sample", "チーム全体の見本"), ("person_sample", "個人の見本"),
                       ("guidelines", "書く際の注意点"), ("mail_body", "メール本文")):
        if len(values[key]) > settings_store.TEXT_MAX:
            errors.append("{}は{}文字以内にしてください。".format(label, settings_store.TEXT_MAX))
    return values, errors


def with_input(current, values):
    """保存済みの設定に入力中の値を重ねる(入力エラー時の再表示用。保存はしない)。"""
    current.update(values)
    return current


def context(settings):
    """週報の設定フォームの表示に使う値。"""
    users = get_active_users()
    # IDとログインIDの両方が一致する人だけを選択済みにする(IDが再利用された別人は選ばない)
    selected_ids = {u.id for u in users if settings_store.is_target(settings, u)}
    return {
        "settings": settings,
        "users": users,
        "selected_ids": selected_ids,
        "selected_count": sum(1 for u in users if u.id in selected_ids),
        "weekday_labels": WEEKDAY_LABELS,
        "period_rules": PERIOD_RULES,
        "placeholders": PLACEHOLDER_HELP,
        "sample_placeholders": SAMPLE_PLACEHOLDER_HELP,
        "preview": preview_names(settings, date.today()),
    }
