"""期限超過通知の作成・送信のとりまとめ(画面の「今すぐ送信」と自動送信の両方から使う)。

run_overdue(app, trigger, test):
  1. 設定(instance/overdue_settings.json)を読み込む
  2. 期限超過タスクを集めてメール(件名・テキスト版・HTML版)を作る(content)
  3. test=True  : テスト宛先(MAIL_TEST_TO、空なら差出人)に送る。Cc なし
     test=False : 本番の宛先に送る。OVERDUE_MAIL_TO が記入されていれば
                  OVERDUE_MAIL_TO・OVERDUE_MAIL_CC、空なら MAIL_TO・MAIL_CC
  成否にかかわらず「前回の結果」を上書きする。期限超過が0件でも送る(「該当なし」)。

start_background(...) は送信を別スレッドで実行する(画面からの送信用。
画面はすぐに戻り、結果は「前回の結果」に表示される)。
送信は同時に1つだけ実行する(二重送信の防止)。

DBは読み取りのみ(書き込みは一切しない)。必ず app.app_context() の中で動く。
"""
import threading
from datetime import date

from flask import current_app

from app import mailer
from app.overdue import content, settings_store

# 本番の宛先が空のときに示す設定項目の名前
TO_LABEL = "宛先（OVERDUE_MAIL_TO または MAIL_TO）"

# メール送信(テスト・本番)は同時に1つだけ(二重送信を防ぐ)
_send_lock = threading.Lock()


def is_sending():
    """メール送信(テスト・本番)の処理中か。"""
    return _send_lock.locked()


def production_recipients():
    """本番の宛先 (To, Cc, 使う設定の名前)。

    OVERDUE_MAIL_TO が記入されていれば OVERDUE_MAIL_TO・OVERDUE_MAIL_CC を、
    空なら週報と同じ MAIL_TO・MAIL_CC を使う。
    """
    config = current_app.config
    to = mailer.addresses(config.get("OVERDUE_MAIL_TO"))
    if to:
        return to, mailer.addresses(config.get("OVERDUE_MAIL_CC")), "OVERDUE_MAIL_TO / OVERDUE_MAIL_CC"
    values = mailer.settings()
    return values["to"], values["cc"], "MAIL_TO / MAIL_CC"


def check(test=False):
    """送信に必要な設定が揃っているか。問題があればその説明、無ければ None。"""
    to, _cc, _source = production_recipients()
    return mailer.check(test, to=to, to_label=TO_LABEL)


def build_mail(today=None):
    """保存済みの設定(表示するコメント件数)で、今日の時点のメールの内容を作る。"""
    settings = settings_store.load()
    return content.build(today or date.today(), settings["comment_count"])


def _summary(mail, send_message):
    """前回の結果に残す短いメッセージ。"""
    parts = [send_message.rstrip("。"),
             "未着手・進行中 {}件／保留 {}件".format(mail["counts"]["active"], mail["counts"]["hold"])]
    if mail["link_problem"]:
        parts.append("リンクなし（APP_BASE_URL 未設定・不正）")
    return " ／ ".join(parts)


def _deliver(app, trigger, test, today):
    """送信の本体(_send_lock を持った状態で呼ぶ)。成否にかかわらず「前回の結果」を上書きする。"""
    with app.app_context():
        try:
            problem = check(test)
            if problem:
                ok, message = False, problem
            else:
                mail = build_mail(today)
                to, cc, _source = production_recipients()
                ok, send_message = mailer.send(
                    mail["subject"], mail["text"], html=mail["html"], to=to, cc=cc, test=test)
                message = _summary(mail, send_message)
        except Exception as exc:
            app.logger.exception("期限超過通知の作成・送信に失敗しました")
            ok, message = False, "期限超過通知の作成中にエラーが発生しました: {}".format(exc)

        try:
            settings_store.set_last_result(trigger, ok, message)
        except Exception:
            app.logger.exception("期限超過通知の前回の結果を保存できませんでした")
        return {"ok": ok, "message": message}


def run_overdue(app, trigger, test=False, today=None):
    """期限超過通知を作成して送信する(呼び出したスレッドで最後まで実行)。

    trigger : 前回の結果に残すきっかけ(自動 / 手動 / テスト)
    today   : 期限超過の基準日(省略時は今日)
    戻り値: {"ok", "message"}。例外は外に出さず、失敗は ok=False とメッセージで返す。
    送信は同時に1つだけ(処理中なら終わるまで待つ)。
    """
    with _send_lock:
        return _deliver(app, trigger, test, today)


def start_background(app, trigger, test=False):
    """送信を別スレッドで始める(画面の「今すぐ送信」用)。

    既に送信処理中なら何もせず False を返す(二重送信の防止)。
    結果は「前回の結果」に記録される。
    """
    if not _send_lock.acquire(blocking=False):
        return False
    today = date.today()

    def worker():
        try:
            _deliver(app, trigger, test, today)
        except Exception:
            app.logger.exception("期限超過通知の送信処理でエラーが発生しました")
        finally:
            _send_lock.release()

    try:
        threading.Thread(target=worker, name="overdue-send", daemon=True).start()
    except Exception:
        _send_lock.release()
        raise
    return True
