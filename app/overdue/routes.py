"""期限超過通知(毎朝のメール)の画面と手動送信。マネージャーのみ。

GET  /overdue/          期限超過通知の画面(次回の自動送信・前回の結果・メール/リンクの設定状況・
                        現在の設定の概要・今この時点のメールのプレビュー)
POST /overdue/run       今すぐ送信: test=テスト送信 / send=本番の宛先に送信(バックグラウンド)
POST /overdue/settings  旧URL。システム設定の保存(POST /system/settings/overdue)へ転送する

期限超過通知の設定(自動送信・時刻・コメント件数)は、システム設定の「期限超過通知」タブで変更する
(入力チェックは settings_form.py、保存先は instance/overdue_settings.json)。
メールの送信サーバー・宛先・リンクの基準URL(APP_BASE_URL)はシステム設定の「基本設定」タブ
(instance/config.py)で変更する(この画面では状況だけを表示する)。
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

overdue_bp = Blueprint("overdue", __name__, url_prefix="/overdue")

WEEKDAY_LABELS = ["月", "火", "水", "木", "金", "土", "日"]
ACTION_TEST = "test"
ACTION_SEND = "send"


@overdue_bp.before_request
def _managers_only():
    """期限超過通知の画面・送信はマネージャーのみ(未ログインはログイン画面へ)。

    login_required は OPTIONS を素通しするため使わず、ここで直接確認する。
    """
    if not current_user.is_authenticated:
        return current_app.login_manager.unauthorized()
    if not getattr(current_user, "is_manager", False):
        abort(403)


def _preview_document(html):
    """プレビュー用のHTML(リンクは別タブで開く)。iframe の srcdoc に入れて表示する。"""
    return html.replace("<head>", '<head>\n<base target="_blank">', 1)


def _render(settings):
    """期限超過通知の画面を表示する(実行と状況だけ。設定はシステム設定の「期限超過通知」タブ)。"""
    mail = mailer.settings()
    to, cc, source = service.production_recipients()
    test_to, _cc = mailer.recipients(test=True)
    base_url, link_problem = content.link_base()
    # 今この時点のメールの内容。「今すぐ送信」と同じく保存済みの設定で作る
    preview = content.build(date.today(), settings["comment_count"])
    return render_template(
        "overdue/index.html",
        settings=settings,
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
    )


@overdue_bp.route("/")
def index():
    return _render(settings_store.load())


@overdue_bp.route("/settings", methods=["POST"])
def save_settings():
    """旧URL(設定の保存)。設定はシステム設定に移したため、そちらの保存へ転送する。

    307 で転送するのでフォームの内容はそのまま届き、保存後はシステム設定の「期限超過通知」タブに戻る。
    """
    return redirect(url_for("system.save_overdue"), code=307)


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
        return redirect(url_for("overdue.index"))

    flash("{}を開始しました。結果は「前回の結果」に表示されます"
          "（画面を再読み込みして確認してください）。".format(label), "info")
    return redirect(url_for("overdue.index"))
