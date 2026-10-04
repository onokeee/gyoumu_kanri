"""期限超過通知(毎朝のメール)の設定画面と手動送信。マネージャーのみ。

GET  /overdue/          設定画面(次回の自動送信・前回の結果・メール/リンクの設定状況・
                        各設定・今この時点のメールのプレビュー)
POST /overdue/settings  設定の保存(instance/overdue_settings.json。DBは使わない)
POST /overdue/run       今すぐ送信: test=テスト送信 / send=本番の宛先に送信(バックグラウンド)

メールの送信サーバー・宛先・リンクの基準URL(APP_BASE_URL)は instance/config.py で設定する
(この画面では読み取り専用で状況だけを表示する)。
"""
from datetime import date, datetime

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user

from app import mailer
from app.overdue import content, service, settings_store
from app.overdue.rules import next_run
from app.utils import parse_hhmm

overdue_bp = Blueprint("overdue", __name__, url_prefix="/overdue")

WEEKDAY_LABELS = ["月", "火", "水", "木", "金", "土", "日"]
ACTION_TEST = "test"
ACTION_SEND = "send"


@overdue_bp.before_request
def _managers_only():
    """期限超過通知の設定・送信はマネージャーのみ(未ログインはログイン画面へ)。

    login_required は OPTIONS を素通しするため使わず、ここで直接確認する。
    """
    if not current_user.is_authenticated:
        return current_app.login_manager.unauthorized()
    if not getattr(current_user, "is_manager", False):
        abort(403)


def _preview_document(html):
    """プレビュー用のHTML(リンクは別タブで開く)。iframe の srcdoc に入れて表示する。"""
    return html.replace("<head>", '<head>\n<base target="_blank">', 1)


def _render(settings, status=200):
    """設定画面を表示する(保存エラー時は入力中の値で再表示する)。"""
    mail = mailer.settings()
    to, cc, source = service.production_recipients()
    test_to, _cc = mailer.recipients(test=True)
    base_url, link_problem = content.link_base()
    # 今この時点のメールの内容。「今すぐ送信」と同じく保存済みの設定で作る
    # (入力エラーで再表示する場合も、未保存の入力値は使わない)
    preview = content.build(date.today(), settings_store.load()["comment_count"])
    return render_template(
        "overdue/settings.html",
        settings=settings,
        comment_min=settings_store.COMMENT_COUNT_MIN,
        comment_max=settings_store.COMMENT_COUNT_MAX,
        upcoming=next_run(settings, datetime.now()),
        weekday_labels=WEEKDAY_LABELS,
        last=settings["last_result"],
        mail=mail,
        to_count=len(to),
        cc_count=len(cc),
        recipient_source=source,
        mail_problem=service.check(test=False),
        test_problem=service.check(test=True),
        test_to_count=len(test_to),
        test_to_is_from=not mail["test_to"],
        base_url=base_url,
        link_configured=bool(str(current_app.config.get("APP_BASE_URL") or "").strip()),
        link_problem=link_problem,
        preview=preview,
        preview_document=_preview_document(preview["html"]),
        sending=service.is_sending(),
    ), status


@overdue_bp.route("/")
def settings_view():
    return _render(settings_store.load())


@overdue_bp.route("/settings", methods=["POST"])
def save_settings():
    errors = []
    values = {"enabled": request.form.get("enabled") == "1"}

    at = parse_hhmm(request.form.get("time"))
    if at is not None:
        values["time"] = at.strftime("%H:%M")
    else:
        errors.append("送信する時刻を「時:分」（例: 05:00）で入力してください。")

    raw_count = (request.form.get("comment_count") or "").strip()
    count = int(raw_count) if raw_count.isdecimal() else None
    if settings_store.valid_comment_count(count):
        values["comment_count"] = count
    else:
        errors.append("表示するコメント件数は{}〜{}の数字で入力してください。".format(
            settings_store.COMMENT_COUNT_MIN, settings_store.COMMENT_COUNT_MAX))

    if errors:
        for message in errors:
            flash(message, "danger")
        # 入力中の内容を残したまま再表示する(保存はしない)
        current = settings_store.load()
        current.update(values)
        return _render(current, status=400)

    try:
        settings_store.save(values)
    except OSError as exc:
        current_app.logger.exception("期限超過通知の設定を保存できませんでした")
        flash("設定を保存できませんでした: {}".format(exc), "danger")
        current = settings_store.load()
        current.update(values)
        return _render(current, status=500)

    flash("期限超過通知の設定を保存しました。", "success")
    return redirect(url_for("overdue.settings_view"))


@overdue_bp.route("/run", methods=["POST"])
def run_now():
    action = request.form.get("action", "")
    if action == ACTION_TEST:
        trigger, label, test = settings_store.TRIGGER_TEST, "テスト送信", True
    elif action == ACTION_SEND:
        trigger, label, test = settings_store.TRIGGER_MANUAL, "本番の宛先への送信", False
    else:
        abort(400)

    app = current_app._get_current_object()
    if not service.start_background(app, trigger, test=test):
        flash("別の送信を処理中です。完了してから、もう一度実行してください。", "warning")
        return redirect(url_for("overdue.settings_view"))

    flash("{}を開始しました。結果は「前回の結果」に表示されます"
          "（画面を再読み込みして確認してください）。".format(label), "info")
    return redirect(url_for("overdue.settings_view"))
