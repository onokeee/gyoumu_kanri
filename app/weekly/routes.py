"""週報(自動作成・メール送信)の画面と手動実行。マネージャーのみ。

GET  /weekly/          週報の画面(次回の自動送信・前回の結果・メール/AIの設定状況・
                       今すぐ作成・現在の設定の概要とファイル名/件名のプレビュー)
POST /weekly/run       今すぐ作成: download=Wordをダウンロード / test=テスト送信 / send=本番送信
GET  /weekly/preview   入力中のファイル名・件名のプレビュー(JSON。システム設定の「週報」タブで使う)
POST /weekly/settings  旧URL。システム設定の保存(POST /system/settings/weekly)へ転送する

週報の設定(曜日・時刻・対象者・見本など)は、システム設定の「週報」タブで変更する
(入力チェックは settings_form.py、保存先は instance/weekly_settings.json)。
メールの送信サーバー・宛先、AIの接続先・キーはシステム設定の「基本設定」タブ
(instance/config.py)で変更する(この画面では状況だけを表示する)。
"""
import re
from datetime import date, datetime
from urllib.parse import quote

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user

from app import ai_client, mailer
from app.utils import get_active_users, parse_date
from app.weekly import service, settings_store
from app.weekly.rules import (
    PERIOD_RULES,
    WEEKDAY_LABELS,
    next_run,
    period_for,
    period_label,
    preview_names,
)

weekly_bp = Blueprint("weekly", __name__, url_prefix="/weekly")

DOCX_MIMETYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
# 「今すぐ作成」で指定できる期間の上限(日数)
RUN_MAX_DAYS = 366


@weekly_bp.before_request
def _managers_only():
    """週報の画面・作成はマネージャーのみ(未ログインはログイン画面へ)。

    login_required は OPTIONS を素通しするため使わず、ここで直接確認する。
    """
    if not current_user.is_authenticated:
        return current_app.login_manager.unauthorized()
    if not getattr(current_user, "is_manager", False):
        abort(403)


def _render(settings):
    """週報の画面を表示する(実行と状況だけ。設定はシステム設定の「週報」タブ)。"""
    today = date.today()
    users = get_active_users()
    selected = [u for u in users if settings_store.is_target(settings, u)]
    run_from, run_to = period_for(today, settings["period_rule"])

    upcoming = next_run(settings, datetime.now())
    upcoming_period = None
    if upcoming is not None:
        upcoming_period = period_label(*period_for(upcoming.date(), settings["period_rule"]))

    mail = mailer.settings()
    test_to, _cc = mailer.recipients(test=True)
    return render_template(
        "weekly/index.html",
        settings=settings,
        selected_users=selected,
        selected_count=len(selected),
        weekday_labels=WEEKDAY_LABELS,
        period_rules=PERIOD_RULES,
        preview=preview_names(settings, today),
        upcoming=upcoming,
        upcoming_period=upcoming_period,
        last=settings["last_result"],
        run_from=run_from,
        run_to=run_to,
        mail=mail,
        mail_problem=mailer.check(test=False),
        test_problem=mailer.check(test=True),
        test_to_count=len(test_to),
        test_to_is_from=not mail["test_to"],
        ai_enabled=ai_client.is_configured(),
        ai_status=ai_client.status_label(),
        sending=service.is_sending(),
    )


@weekly_bp.route("/")
def index():
    return _render(settings_store.load())


@weekly_bp.route("/settings", methods=["POST"])
def save_settings():
    """旧URL(設定の保存)。設定はシステム設定に移したため、そちらの保存へ転送する。

    307 で転送するのでフォームの内容はそのまま届き、保存後はシステム設定の「週報」タブに戻る。
    """
    return redirect(url_for("system.save_weekly"), code=307)


@weekly_bp.route("/preview")
def preview():
    """入力中のパターンで、今日作成した場合のファイル名・件名を返す。"""
    settings = settings_store.load()
    for key in ("filename_pattern", "subject_pattern"):
        if key in request.args:
            settings[key] = request.args.get(key, "")
    if request.args.get("period_rule") in PERIOD_RULES:
        settings["period_rule"] = request.args["period_rule"]
    return jsonify(preview_names(settings, date.today()))


def _docx_response(data, filename, start, end):
    """Wordファイルを添付として返す(日本語のファイル名は RFC 5987 の filename* で渡す)。"""
    fallback = "weekly_report_{}-{}.docx".format(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
    if re.fullmatch(r"[A-Za-z0-9._ ()\-]+", filename):
        fallback = filename
    disposition = "attachment; filename=\"{}\"; filename*=UTF-8''{}".format(
        fallback, quote(filename, safe=""))
    return Response(data, mimetype=DOCX_MIMETYPE,
                    headers={"Content-Disposition": disposition})


@weekly_bp.route("/run", methods=["POST"])
def run_now():
    action = request.form.get("action", "")
    if action not in service.DELIVER_CHOICES:
        abort(400)

    settings = settings_store.load()
    default_from, default_to = period_for(date.today(), settings["period_rule"])
    start = parse_date(request.form.get("start")) or default_from
    end = parse_date(request.form.get("end")) or default_to
    if end < start:
        start, end = end, start
    if (end - start).days + 1 > RUN_MAX_DAYS:
        flash("期間は{}日以内で指定してください。".format(RUN_MAX_DAYS), "danger")
        return redirect(url_for("weekly.index"))

    app = current_app._get_current_object()

    if action == service.DELIVER_DOWNLOAD:
        result = service.run_weekly(
            app, start, end, settings_store.TRIGGER_MANUAL, service.DELIVER_DOWNLOAD)
        if not result["ok"]:
            flash(result["message"], "danger")
            return redirect(url_for("weekly.index"))
        return _docx_response(result["data"], result["filename"], start, end)

    if action == service.DELIVER_TEST:
        trigger, label = settings_store.TRIGGER_TEST, "テスト送信"
    else:
        trigger, label = settings_store.TRIGGER_MANUAL, "本番の宛先への送信"

    if not service.start_background(app, start, end, trigger, action):
        flash("別の送信を処理中です。完了してから、もう一度実行してください。", "warning")
        return redirect(url_for("weekly.index"))

    flash("{}を開始しました（期間 {}）。結果は「前回の結果」に表示されます"
          "（作成に数十秒〜数分かかる場合があります。画面を再読み込みして確認してください）。"
          .format(label, period_label(start, end)), "info")
    return redirect(url_for("weekly.index"))
