"""スキルテストの設定フォームの入力チェックと表示用の値(システム設定の「スキルテスト」タブで使う)。

設定の画面はシステム設定(/system/settings?tab=skilltest)にまとめてあり、
スキルテスト管理(/skilltest/admin)には受験履歴と問題プールだけが残る。
保存先は settings_store.py のまま(instance/skilltest_settings.json)。

  parse(form)              フォームの入力を検証する → (保存する値, エラーメッセージの一覧)
  with_input(current, v)   入力エラーで再表示するとき、保存済みの設定に入力中の値を重ねる
  context(settings)        フォームの表示に使う値
"""
from app.models.skill import SKILL_TECHNICAL, scale_for
from app.skilltest import service, settings_store

LABEL = "スキルテスト"
SAVED_MESSAGE = "スキルテストの設定を保存しました（受験中・受験済みのテストには影響しません）。"

# レベルごと以外の数値の項目: (キー, 表示名, 下限, 上限, 単位)
_SCALAR_FIELDS = (
    ("pass_rate", "合格ライン", settings_store.PASS_RATE_MIN, settings_store.PASS_RATE_MAX, "%"),
    ("retake_days", "再受験までの日数", settings_store.RETAKE_DAYS_MIN,
     settings_store.RETAKE_DAYS_MAX, "日"),
    ("max_auto_level", "判定・自動登録するレベルの上限", settings_store.AUTO_LEVEL_MIN,
     settings_store.AUTO_LEVEL_MAX, ""),
    ("pool_target_per_level", "問題プールの目標数", settings_store.POOL_TARGET_MIN,
     settings_store.POOL_TARGET_MAX, "問"),
)


def _number(form, name):
    raw = (form.get(name) or "").strip()
    return int(raw) if raw.isdecimal() else None


def parse(form):
    """フォームの入力を検証する。戻り値: (values, errors)。errors が空なら保存してよい。"""
    errors = []
    values = {"questions_per_level": {}, "time_limits": {}}

    for level in settings_store.LEVELS:
        count = _number(form, "questions_{}".format(level))
        if settings_store.valid_int(count, settings_store.QUESTIONS_MIN, settings_store.QUESTIONS_MAX):
            values["questions_per_level"][str(level)] = count
        else:
            errors.append("Lv{}の問題数は{}〜{}の数字で入力してください。".format(
                level, settings_store.QUESTIONS_MIN, settings_store.QUESTIONS_MAX))
        limit = _number(form, "limit_{}".format(level))
        if settings_store.valid_int(limit, settings_store.TIME_LIMIT_MIN, settings_store.TIME_LIMIT_MAX):
            values["time_limits"][str(level)] = limit
        else:
            errors.append("Lv{}の制限時間は{}〜{}秒の数字で入力してください。".format(
                level, settings_store.TIME_LIMIT_MIN, settings_store.TIME_LIMIT_MAX))

    for key, label, low, high, unit in _SCALAR_FIELDS:
        value = _number(form, key)
        if settings_store.valid_int(value, low, high):
            values[key] = value
        else:
            errors.append("{}は{}〜{}{}の数字で入力してください。".format(label, low, high, unit))
    return values, errors


def with_input(current, values):
    """保存済みの設定に入力中の値を重ねる(入力エラー時の再表示用。保存はしない)。

    レベルごとの値は、正しく入力されたレベルだけを重ねる。
    """
    current["questions_per_level"].update(values.get("questions_per_level", {}))
    current["time_limits"].update(values.get("time_limits", {}))
    for key, _label, _low, _high, _unit in _SCALAR_FIELDS:
        if key in values:
            current[key] = values[key]
    return current


def context(settings):
    """スキルテストの設定フォームの表示に使う値。"""
    scale = scale_for(SKILL_TECHNICAL)
    _rows, total, seconds = settings_store.plan(
        settings, settings_store.tested_levels(settings, len(scale) - 1))
    return {
        "settings": settings,
        "levels": settings_store.LEVELS,
        "plan_total": total,
        "plan_minutes": int(round(seconds / 60.0)),
        "scale": scale,
        "limits": settings_store,
        "grace_sec": service.GRACE_SEC,
        "margin_min": service.DEADLINE_MARGIN_MIN,
    }
