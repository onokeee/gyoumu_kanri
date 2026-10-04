"""画面で編集する設定(JSONファイル)の読み書きの共通部品。

週報(instance/weekly_settings.json)・期限超過通知(instance/overdue_settings.json)など、
DBを使わずに instance/ のJSONファイルへ設定と「前回の結果」を保存する機能で使う。

  read_json(path, label)      : 読む。無ければ None、あるのに読めなければ SettingsFileError
  write_json(path, data)      : 一時ファイルに書いてから置き換える(書き込み途中で壊れない)
  normalize_last_result(v)    : 読み込んだ「前回の結果」を検証する(不正なら None)
  new_last_result(...)        : 新しい「前回の結果」(日時・きっかけ・成否・メッセージ)

画面の保存とバックグラウンドの送信が同時に書き込んでも壊れないよう、呼び出し側は
機能ごとのロックで「読む→書く」を直列化する。
ファイルがあるのに読み込めない(壊れている・開けない)ときは、保存済みの設定を
消さないよう上書きしない(SettingsFileError を送出する)。
"""
import json
import os
import tempfile
from datetime import datetime

# 実行のきっかけ(前回の結果の表示用)
TRIGGER_AUTO = "自動"
TRIGGER_MANUAL = "手動"
TRIGGER_TEST = "テスト"

# 前回の結果のメッセージの最大文字数
MESSAGE_MAX = 500


class SettingsFileError(OSError):
    """設定ファイルはあるが読み込めない(壊れている・開けない)。上書きを防ぐために使う。"""


def read_json(path, label):
    """設定ファイルを読む。無ければ None、あるのに読めなければ SettingsFileError。

    label はエラーメッセージに使う設定の名前(例: 「週報の設定ファイル」)。
    エディタで保存したときに付く BOM は無視する。
    """
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise SettingsFileError(
            "{}（instance/{}）を読み込めません。"
            "ファイルを修正するか削除してください: {}".format(
                label, os.path.basename(path), exc)
        ) from exc


def write_json(path, data):
    """一時ファイルに書いてから置き換える(書き込み途中で壊れたファイルを残さない)。"""
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    stem = os.path.splitext(os.path.basename(path))[0]
    fd, tmp_path = tempfile.mkstemp(prefix=".{}_".format(stem), suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def normalize_last_result(value):
    """読み込んだ「前回の結果」を検証して整える(辞書でなければ None)。"""
    if not isinstance(value, dict):
        return None
    return {
        "at": str(value.get("at") or ""),
        "trigger": str(value.get("trigger") or ""),
        "ok": bool(value.get("ok")),
        "message": str(value.get("message") or "")[:MESSAGE_MAX],
    }


def new_last_result(trigger, ok, message):
    """今の日時で「前回の結果」を作る。"""
    return {
        "at": datetime.now().strftime("%Y/%m/%d %H:%M"),
        "trigger": trigger,
        "ok": bool(ok),
        "message": str(message or "")[:MESSAGE_MAX],
    }
