"""週報の作成・送信のとりまとめ(画面の「今すぐ作成」と自動送信の両方から使う)。

run_weekly(app, start, end, trigger, deliver):
  1. 設定(instance/weekly_settings.json)と対象者を読み込む
  2. 材料を集める(collector) → 文章を作る(writer) → Wordにする(docx_builder)
  3. deliver に応じて:
       "download" : ファイルを返すだけ(送信しない・前回の結果も変えない)
       "test"     : テスト宛先(MAIL_TEST_TO、空なら差出人)に送る。Cc なし
       "send"     : 本番の宛先(MAIL_TO・MAIL_CC)に送る
     test / send は成否にかかわらず「前回の結果」を上書きする。

start_background(...) は test / send を別スレッドで実行する(画面からの送信用。
画面はすぐに戻り、結果は「前回の結果」に表示される)。
テスト送信・本番送信は同時に1つだけ実行する(二重送信の防止)。

DBは読み取りのみ(書き込みは一切しない)。必ず app.app_context() の中で動く。
"""
import threading
from datetime import date, datetime

from app import mailer
from app.models.user import User
from app.weekly import collector, docx_builder, settings_store, writer
from app.weekly.rules import build_filename, build_subject, render_pattern

DELIVER_DOWNLOAD = "download"
DELIVER_TEST = "test"
DELIVER_SEND = "send"
DELIVER_CHOICES = (DELIVER_DOWNLOAD, DELIVER_TEST, DELIVER_SEND)

# 添付する Word ファイルの MIME タイプ
DOCX_MAINTYPE = "application"
DOCX_SUBTYPE = "vnd.openxmlformats-officedocument.wordprocessingml.document"

# メール送信(テスト・本番)は同時に1つだけ(二重送信を防ぐ)
_send_lock = threading.Lock()


class WeeklyError(Exception):
    """利用者に伝える想定内のエラー(対象者が未選択など)。ログにトレースは残さない。"""


def is_sending():
    """メール送信(テスト・本番)の処理中か。"""
    return _send_lock.locked()


def target_users(settings):
    """週報に載せる対象者(画面で選んだ人のうち、有効なユーザーだけ。表示名順)。

    削除されたユーザーのIDが新しく登録したユーザーに再利用されても含めないよう、
    ユーザーIDに加えてログインIDも一致する人だけを対象にする。
    """
    ids = settings.get("target_user_ids") or []
    if not ids:
        return []
    users = (
        User.query.filter(User.id.in_(ids), User.is_active.is_(True))
        .order_by(User.display_name)
        .all()
    )
    return [u for u in users if settings_store.is_target(settings, u)]


def _summary(written, users, send_message=None):
    """前回の結果に残す短いメッセージ。"""
    parts = []
    if send_message:
        parts.append(send_message.rstrip("。"))
    parts.append("対象 {}名".format(len(users)))
    if not written["ai_configured"]:
        parts.append("AI未設定のためルールベースで作成")
    elif written["ai_fallback"]:
        parts.append("AI未整形 {}件（{}）".format(
            written["ai_fallback"], written["ai_error"] or "AIの呼び出しに失敗"))
    else:
        parts.append("AI整形 {}件".format(written["ai_used"]))
    return " ／ ".join(parts)


def _build(app, start, end, send_date):
    """週報を作成する。戻り値: (結果の辞書, 対象者, 文章)"""
    settings = settings_store.load()
    users = target_users(settings)
    if not users:
        raise WeeklyError("週報の対象者が選択されていません。設定画面で対象者を選んで保存してください。")

    material = collector.collect(start, end, users)
    written = writer.write_report(material, settings, send_date)
    data = docx_builder.build_docx(
        material, written, datetime.now(), app.config.get("APP_NAME") or "業務管理システム")
    return {
        "data": data,
        "filename": build_filename(settings["filename_pattern"], start, end, send_date),
        "subject": build_subject(settings["subject_pattern"], start, end, send_date),
        "body": render_pattern(settings["mail_body"], start, end, send_date),
    }, users, written


def _deliver(app, start, end, trigger, deliver, send_date):
    """テスト送信・本番送信の本体(_send_lock を持った状態で呼ぶ)。

    成否にかかわらず「前回の結果」を上書きする。
    """
    test = deliver == DELIVER_TEST
    with app.app_context():
        result = {"filename": None, "data": None}
        try:
            # 送信できない設定なら、時間のかかる作成(AI呼び出し)の前に止める
            problem = mailer.check(test=test)
            if problem:
                ok, message = False, problem
            else:
                result, users, written = _build(app, start, end, send_date)
                ok, send_message = mailer.send(
                    result["subject"], result["body"],
                    attachments=[(result["filename"], result["data"],
                                  DOCX_MAINTYPE, DOCX_SUBTYPE)],
                    test=test,
                )
                message = _summary(written, users, send_message)
        except Exception as exc:
            ok, message = False, _error_message(app, exc)

        prefix = "期間 {}〜{}: ".format(start.strftime("%m/%d"), end.strftime("%m/%d"))
        try:
            settings_store.set_last_result(trigger, ok, prefix + message)
        except Exception:
            app.logger.exception("週報の前回の結果を保存できませんでした")
        return dict(result, ok=ok, message=message)


def run_weekly(app, start, end, trigger, deliver, send_date=None):
    """週報を作成し、deliver に応じて送信する(呼び出したスレッドで最後まで実行)。

    trigger   : 前回の結果に残すきっかけ(自動 / 手動 / テスト)
    send_date : 差し込み記号 {送信日}・{作成日} の日付(省略時は今日)
    戻り値: {"ok", "message", "filename", "data"}
    例外は外に出さず、失敗は ok=False とメッセージで返す。
    テスト送信・本番送信は同時に1つだけ(処理中なら終わるまで待つ)。
    """
    if deliver not in DELIVER_CHOICES:
        raise ValueError("deliver が不正です: {}".format(deliver))
    send_date = send_date or date.today()

    if deliver == DELIVER_DOWNLOAD:
        with app.app_context():
            try:
                result, users, written = _build(app, start, end, send_date)
            except Exception as exc:
                return {"ok": False, "message": _error_message(app, exc),
                        "filename": None, "data": None}
            return dict(result, ok=True, message=_summary(written, users))

    with _send_lock:
        return _deliver(app, start, end, trigger, deliver, send_date)


def start_background(app, start, end, trigger, deliver, send_date=None):
    """テスト送信・本番送信を別スレッドで始める(画面の「今すぐ作成」用)。

    既に送信処理中なら何もせず False を返す(二重送信の防止)。
    結果は「前回の結果」に記録される。
    """
    if deliver not in (DELIVER_TEST, DELIVER_SEND):
        raise ValueError("deliver が不正です: {}".format(deliver))
    if not _send_lock.acquire(blocking=False):
        return False
    send_date = send_date or date.today()

    def worker():
        try:
            _deliver(app, start, end, trigger, deliver, send_date)
        except Exception:
            app.logger.exception("週報の送信処理でエラーが発生しました")
        finally:
            _send_lock.release()

    try:
        threading.Thread(target=worker, name="weekly-send", daemon=True).start()
    except Exception:
        _send_lock.release()
        raise
    return True


def _error_message(app, exc):
    """例外を画面・前回の結果用の短い文言にする(想定外のものはログにトレースを残す)。"""
    if isinstance(exc, WeeklyError):
        app.logger.warning("週報: %s", exc)
        return str(exc)
    app.logger.exception("週報の作成・送信に失敗しました")
    return "週報の作成中にエラーが発生しました: {}".format(exc)
