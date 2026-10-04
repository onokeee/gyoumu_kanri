"""週報の設定(画面で編集する値)の保存・読み込み。

DBは使わず、instance/weekly_settings.json(Git管理外)に保存する。
ファイルが無ければ既定値を使い、画面で保存したとき(または送信して前回の結果を
記録したとき)に作成される。

ここに保存するのは「いつ・誰を・どう書くか」だけ。メールの送信サーバー・宛先や
AIのキーは保存しない(instance/config.py。システム設定の「基本設定」タブで変更する)。
画面の入力チェックは settings_form.py(システム設定の「週報」タブで使う)。

保存項目:
  enabled          : 自動送信する/しない
  weekday / time   : 自動送信の曜日(0=月〜6=日)・時刻("HH:MM")
  period_rule      : 期間のルール(rules.PERIOD_RULES)
  target_user_ids  : 週報に載せる対象者(ユーザーID)。新規ユーザーは自動では入らない
  target_usernames : 対象者のIDごとのログインID({"ID": "ログインID"})。
                     削除されたユーザーのIDが新しいユーザーに再利用されても、
                     IDとログインIDの両方が一致する人だけを対象者とする(取り違え防止)
  team_sample / person_sample / guidelines : 文章の見本と書く際の注意点
  filename_pattern / subject_pattern / mail_body : ファイル名・件名・メール本文
  last_result      : 前回の結果(日時・きっかけ・成否・メッセージ)。毎回上書き

画面の保存とバックグラウンドの送信が同時に書き込んでも壊れないよう、
ロックで直列化し、一時ファイルに書いてから置き換える(os.replace)。
ファイルがあるのに読み込めない(壊れている・開けない)ときは、表示や自動送信の判定には
既定値を使うが、保存済みの設定を消さないよう上書きはしない(SettingsFileError)。
ファイルの読み書きは期限超過通知と共通の部品(app/settings_file.py)を使う。
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
from app.weekly.rules import PERIOD_PREV7, PERIOD_RULES, parse_hhmm

SETTINGS_FILENAME = "weekly_settings.json"
SETTINGS_LABEL = "週報の設定ファイル"

# 文章の見本などの最大文字数(設定ファイルの肥大化を防ぐ)
TEXT_MAX = 20000

DEFAULT_TEAM_SAMPLE = """■全体の状況（{期間}）
・完了3件、新規着手2件。全体としておおむね計画どおりに進んでいる。
・期限超過は1件（〇〇の確認待ち。来週前半に完了見込み）。
■主な成果
・〇〇の手順を見直し、作業時間を削減（120 ｈ/年）。
■課題・リスク
・△△は関係者の日程調整中のため保留。来週に再開予定。
■来週の予定
・□□の試行を開始する。"""

DEFAULT_PERSON_SAMPLE = """■今週の実績
・〇〇の資料作成を完了（成果: 作業時間 5 ｈ/月 の削減）。
・△△の検討を進め、方針案を作成した。
■課題・相談事項
・□□は確認待ちのため、期限を1週間延長したい。
■来週の予定
・△△の方針案を共有し、意見を集める。"""

DEFAULT_GUIDELINES = """・事実を簡潔に書く（1項目1〜2行程度）。
・完了したものは、成果（数値・効果）を添える。
・遅れや課題がある場合は、理由と今後の対応を書く。
・敬称は付けない。
・材料に無いことは書かず、該当が無い項目は「特になし」と書く。"""

DEFAULT_FILENAME_PATTERN = "週報_{開始日}-{終了日}.docx"
DEFAULT_SUBJECT_PATTERN = "【週報】{期間}"
DEFAULT_MAIL_BODY = """各位

{期間} の週報を送付します。
添付のWordファイルをご確認ください。

※このメールは業務管理システムから送信しています。"""

DEFAULTS = {
    "enabled": False,
    "weekday": 0,
    "time": "08:00",
    "period_rule": PERIOD_PREV7,
    "target_user_ids": [],
    "target_usernames": {},
    "team_sample": DEFAULT_TEAM_SAMPLE,
    "person_sample": DEFAULT_PERSON_SAMPLE,
    "guidelines": DEFAULT_GUIDELINES,
    "filename_pattern": DEFAULT_FILENAME_PATTERN,
    "subject_pattern": DEFAULT_SUBJECT_PATTERN,
    "mail_body": DEFAULT_MAIL_BODY,
    "last_result": None,
}

# 画面から保存できる項目(last_result は送信処理だけが書き込む)
EDITABLE_KEYS = [k for k in DEFAULTS if k != "last_result"]

_TEXT_KEYS = (
    "team_sample", "person_sample", "guidelines",
    "filename_pattern", "subject_pattern", "mail_body",
)

_lock = threading.RLock()


def _path():
    return os.path.join(current_app.instance_path, SETTINGS_FILENAME)


def _normalize(data):
    """読み込んだ値を検証し、不正・欠落した項目は既定値で補う。"""
    result = copy.deepcopy(DEFAULTS)
    if not isinstance(data, dict):
        return result

    if isinstance(data.get("enabled"), bool):
        result["enabled"] = data["enabled"]
    weekday = data.get("weekday")
    if isinstance(weekday, int) and not isinstance(weekday, bool) and 0 <= weekday <= 6:
        result["weekday"] = weekday
    at = parse_hhmm(data.get("time")) if isinstance(data.get("time"), str) else None
    if at is not None:
        result["time"] = at.strftime("%H:%M")
    if data.get("period_rule") in PERIOD_RULES:
        result["period_rule"] = data["period_rule"]
    ids = data.get("target_user_ids")
    names = data.get("target_usernames")
    if isinstance(ids, list) and isinstance(names, dict):
        # ログインIDの記録が無いIDは本人か確認できないため、対象者に含めない
        result["target_user_ids"] = sorted({
            i for i in ids
            if isinstance(i, int) and not isinstance(i, bool)
            and isinstance(names.get(str(i)), str) and names.get(str(i))
        })
        result["target_usernames"] = {
            str(i): names[str(i)] for i in result["target_user_ids"]
        }
    for key in _TEXT_KEYS:
        if isinstance(data.get(key), str):
            result[key] = data[key][:TEXT_MAX]
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
    (既定値で上書きして、保存済みの対象者・見本などを消さないため)。
    """
    return _normalize(read_json(_path(), SETTINGS_LABEL))


def is_target(settings, user):
    """user が対象者として選ばれているか(ユーザーIDとログインIDの両方が一致する場合だけ)。"""
    names = settings.get("target_usernames") or {}
    return bool(user.username) and names.get(str(user.id)) == user.username


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
