"""期限超過通知の設定(画面で編集する値)の保存・読み込み。

DBは使わず、instance/overdue_settings.json(Git管理外)に保存する。
ファイルが無ければ既定値を使い、画面で保存したとき(または送信して前回の結果を
記録したとき)に作成される。

ここに保存するのは「いつ・何件のコメントを載せるか」だけ。メールの送信サーバー・宛先や
リンクの基準URLは保存しない(instance/config.py。システム設定の「基本設定」タブで変更する)。
画面の入力チェックは settings_form.py(システム設定の「期限超過通知」タブで使う)。

保存項目:
  enabled       : 自動送信する/しない(既定はしない)
  time          : 自動送信の時刻("HH:MM"。既定 "05:00")。営業日(土日・祝日以外)だけ送る
  comment_count : 各タスクに載せる進捗記載(コメント)の件数(直近から。1〜10、既定 1)
  last_result   : 前回の結果(日時・きっかけ・成否・メッセージ)。毎回上書き

画面の保存とバックグラウンドの送信が同時に書き込んでも壊れないよう、ロックで直列化し、
一時ファイルに書いてから置き換える(週報と共通の部品 app/settings_file.py)。
ファイルがあるのに読み込めない(壊れている・開けない)ときは、表示や自動送信の判定には
既定値を使うが、保存済みの設定を消さないよう上書きはしない(SettingsFileError)。
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
from app.utils import parse_hhmm

SETTINGS_FILENAME = "overdue_settings.json"
SETTINGS_LABEL = "期限超過通知の設定ファイル"

# 各タスクに載せるコメント件数の範囲
COMMENT_COUNT_MIN = 1
COMMENT_COUNT_MAX = 10

DEFAULTS = {
    "enabled": False,
    "time": "05:00",
    "comment_count": 1,
    "last_result": None,
}

# 画面から保存できる項目(last_result は送信処理だけが書き込む)
EDITABLE_KEYS = [k for k in DEFAULTS if k != "last_result"]

_lock = threading.RLock()


def _path():
    return os.path.join(current_app.instance_path, SETTINGS_FILENAME)


def valid_comment_count(value):
    """コメント件数として使える整数か(bool は除く)。"""
    return (isinstance(value, int) and not isinstance(value, bool)
            and COMMENT_COUNT_MIN <= value <= COMMENT_COUNT_MAX)


def _normalize(data):
    """読み込んだ値を検証し、不正・欠落した項目は既定値で補う。"""
    result = copy.deepcopy(DEFAULTS)
    if not isinstance(data, dict):
        return result

    if isinstance(data.get("enabled"), bool):
        result["enabled"] = data["enabled"]
    at = parse_hhmm(data.get("time")) if isinstance(data.get("time"), str) else None
    if at is not None:
        result["time"] = at.strftime("%H:%M")
    if valid_comment_count(data.get("comment_count")):
        result["comment_count"] = data["comment_count"]
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
    """書き込む前に現在の設定を読む。

    ファイルがあるのに読み込めない場合は SettingsFileError を送出する
    (既定値で上書きして、保存済みの設定を消さないため)。
    """
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
    """前回の結果を上書きする(他の設定項目は変更しない)。

    設定ファイルが読み込めない場合は書き込まずに SettingsFileError を送出する。
    """
    with _lock:
        current = _load_for_update()
        current["last_result"] = new_last_result(trigger, ok, message)
        write_json(_path(), current)
        return current["last_result"]
