"""スキルテストの設定(画面で編集する値)の保存・読み込み。マネージャーが編集する。

DBは使わず、instance/skilltest_settings.json(Git管理外)に保存する。
ファイルが無ければ既定値を使い、画面で保存したとき(または問題の補充の結果を
記録したとき)に作成される。

保存項目:
  questions_per_level   : レベルごとの問題数({"1": 8, "2": 8, "3": 7, "4": 7})
  time_limits           : レベルごとの1問の制限時間(秒。{"1": 60, "2": 90, "3": 150, "4": 180})
  pass_rate             : 合格ライン(正答率 %。既定 70)
  retake_days           : 同じスキルを再受験できるまでの日数(前回の受験開始から。0 なら制限なし)
  max_auto_level        : テストで判定・自動登録するレベルの上限(1〜4。既定 4)
  pool_target_per_level : 問題プールの補充で目標にする、レベルごとの有効な問題数(既定 20)
  last_result           : 前回の問題の補充の結果(日時・きっかけ・成否・メッセージ)。毎回上書き

受験中のテストは開始時点の設定の控え(SkillTestAttempt.settings_snapshot)で採点するため、
設定を変えても受験中・受験済みのテストには影響しない。

画面の保存とバックグラウンドの補充が同時に書き込んでも壊れないよう、ロックで直列化し、
一時ファイルに書いてから置き換える(週報・期限超過通知と共通の部品 app/settings_file.py)。
ファイルがあるのに読み込めない(壊れている・開けない)ときは既定値で動き、
保存済みの設定を消さないよう上書きはしない(SettingsFileError)。
"""
import copy
import os
import threading

from flask import current_app

from app.settings_file import (  # noqa: F401  (TRIGGER_〜・SettingsFileError は呼び出し側も使う)
    TRIGGER_AUTO,
    TRIGGER_MANUAL,
    TRIGGER_TEST,
    SettingsFileError,
    new_last_result,
    normalize_last_result,
    read_json,
    write_json,
)

SETTINGS_FILENAME = "skilltest_settings.json"
SETTINGS_LABEL = "スキルテストの設定ファイル"

# テストで判定できるレベル(1〜4)。5・6 と コンセプチュアル/ヒューマンはマネージャーが評価する
LEVELS = [1, 2, 3, 4]

# 各項目の範囲(画面の入力チェックと読み込み時の検証に使う)
QUESTIONS_MIN, QUESTIONS_MAX = 1, 30         # レベルごとの問題数
TIME_LIMIT_MIN, TIME_LIMIT_MAX = 10, 900     # 1問の制限時間(秒)
PASS_RATE_MIN, PASS_RATE_MAX = 1, 100        # 合格ライン(%)
RETAKE_DAYS_MIN, RETAKE_DAYS_MAX = 0, 365    # 再受験までの日数
AUTO_LEVEL_MIN, AUTO_LEVEL_MAX = 1, 4        # 自動登録するレベルの上限
POOL_TARGET_MIN, POOL_TARGET_MAX = 1, 200    # 問題プールの目標数(レベルごと)

DEFAULTS = {
    "questions_per_level": {"1": 8, "2": 8, "3": 7, "4": 7},
    "time_limits": {"1": 60, "2": 90, "3": 150, "4": 180},
    "pass_rate": 70,
    "retake_days": 7,
    "max_auto_level": 4,
    "pool_target_per_level": 20,
    "last_result": None,
}

# 画面から保存できる項目(last_result は問題の補充だけが書き込む)
EDITABLE_KEYS = [k for k in DEFAULTS if k != "last_result"]

_lock = threading.RLock()


def _path():
    return os.path.join(current_app.instance_path, SETTINGS_FILENAME)


def valid_int(value, low, high):
    """範囲内の整数か(bool は除く)。"""
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def _per_level(data, default, low, high):
    """レベルごとの値({"1": n, ...})を検証し、不正・欠落したレベルは既定値で補う。"""
    result = dict(default)
    if isinstance(data, dict):
        for level in LEVELS:
            value = data.get(str(level))
            if valid_int(value, low, high):
                result[str(level)] = value
    return result


def _normalize(data):
    """読み込んだ値を検証し、不正・欠落した項目は既定値で補う。"""
    result = copy.deepcopy(DEFAULTS)
    if not isinstance(data, dict):
        return result
    result["questions_per_level"] = _per_level(
        data.get("questions_per_level"), DEFAULTS["questions_per_level"],
        QUESTIONS_MIN, QUESTIONS_MAX)
    result["time_limits"] = _per_level(
        data.get("time_limits"), DEFAULTS["time_limits"], TIME_LIMIT_MIN, TIME_LIMIT_MAX)
    for key, low, high in (
        ("pass_rate", PASS_RATE_MIN, PASS_RATE_MAX),
        ("retake_days", RETAKE_DAYS_MIN, RETAKE_DAYS_MAX),
        ("max_auto_level", AUTO_LEVEL_MIN, AUTO_LEVEL_MAX),
        ("pool_target_per_level", POOL_TARGET_MIN, POOL_TARGET_MAX),
    ):
        if valid_int(data.get(key), low, high):
            result[key] = data[key]
    result["last_result"] = normalize_last_result(data.get("last_result"))
    return result


def load():
    """現在の設定を返す(ファイルが無い・読み込めない場合は既定値)。"""
    with _lock:
        try:
            data = read_json(_path(), SETTINGS_LABEL)
        except SettingsFileError as exc:
            current_app.logger.warning("%s（既定値を使用）", exc)
            data = None
        return _normalize(data)


def _load_for_update():
    """書き込む前に現在の設定を読む(読み込めなければ SettingsFileError。上書きしない)。"""
    return _normalize(read_json(_path(), SETTINGS_LABEL))


def save(values):
    """画面で編集した項目を保存する(last_result は変更しない)。"""
    with _lock:
        current = _load_for_update()
        for key in EDITABLE_KEYS:
            if key in values:
                current[key] = values[key]
        data = _normalize(current)
        write_json(_path(), data)
        return data


def set_last_result(trigger, ok, message):
    """前回の問題の補充の結果を上書きする(他の設定項目は変更しない)。"""
    with _lock:
        current = _load_for_update()
        current["last_result"] = new_last_result(trigger, ok, message)
        write_json(_path(), current)
        return current["last_result"]


# --------------------------------------------------------------------------- #
# 設定値の取り出し(受験開始時の控え settings_snapshot にも同じ形で使える)
# --------------------------------------------------------------------------- #
def tested_levels(settings, skill_max_level):
    """テストで判定するレベル(1〜min(上限, スキルの最大レベル))。"""
    top = min(int(settings.get("max_auto_level") or AUTO_LEVEL_MAX), AUTO_LEVEL_MAX,
              int(skill_max_level or 0))
    return list(range(1, max(top, 0) + 1))


def questions_for(settings, level):
    """そのレベルの問題数。"""
    return int(settings["questions_per_level"].get(str(level),
                                                   DEFAULTS["questions_per_level"]["1"]))


def time_limit_for(settings, level):
    """そのレベルの1問の制限時間(秒)。"""
    return int(settings["time_limits"].get(str(level), DEFAULTS["time_limits"]["1"]))


def plan(settings, levels):
    """出題の計画: [{level, count, limit}] と 合計の問題数・制限時間(秒)。"""
    rows = [{"level": lv, "count": questions_for(settings, lv),
             "limit": time_limit_for(settings, lv)} for lv in levels]
    total = sum(r["count"] for r in rows)
    seconds = sum(r["count"] * r["limit"] for r in rows)
    return rows, total, seconds
