"""週報(自動作成・メール送信)の設定画面と手動実行。マネージャーのみ。

GET  /weekly/          設定画面(次回の自動送信・前回の結果・メール/AIの設定状況・各設定)
POST /weekly/settings  設定の保存(instance/weekly_settings.json。DBは使わない)
POST /weekly/run       今すぐ作成: download=Wordをダウンロード / test=テスト送信 / send=本番送信
GET  /weekly/preview   入力中のファイル名・件名のプレビュー(JSON)

メールの送信サーバー・宛先、AIの接続先・キーは instance/config.py で設定する
(この画面では読み取り専用で状況だけを表示する)。
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
    PLACEHOLDER_HELP,
    SAMPLE_PLACEHOLDER_HELP,
    WEEKDAY_LABELS,
    build_filename,
    build_subject,
    next_run,
    parse_hhmm,
    period_for,
    period_label,
)

weekly_bp = Blueprint("weekly", __name__, url_prefix="/weekly")

DOCX_MIMETYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
# 「今すぐ作成」で指定できる期間の上限(日数)
RUN_MAX_DAYS = 366


@weekly_bp.before_request
def _managers_only():
    """週報の設定・作成はマネージャーのみ(未ログインはログイン画面へ)。

    login_required は OPTIONS を素通しするため使わず、ここで直接確認する。
    """
    if not current_user.is_authenticated:
        return current_app.login_manager.unauthorized()
    if not getattr(current_user, "is_manager", False):
        abort(403)


def _preview(settings, today):
    """今日作成した場合のファイル名・件名(画面のプレビュー用)。"""
    start, end = period_for(today, settings["period_rule"])
    return {
        "period": period_label(start, end),
        "filename": build_filename(settings["filename_pattern"], start, end, today),
        "subject": build_subject(settings["subject_pattern"], start, end, today),
    }


def _render(settings, status=200):
    """設定画面を表示する(保存エラー時は入力中の値で再表示する)。"""
    today = date.today()
    users = get_active_users()
    # IDとログインIDの両方が一致する人だけを選択済みにする(IDが再利用された別人は選ばない)
    selected_ids = {u.id for u in users if settings_store.is_target(settings, u)}
    run_from, run_to = period_for(today, settings["period_rule"])

    upcoming = next_run(settings, datetime.now())
    upcoming_period = None
    if upcoming is not None:
        upcoming_period = period_label(*period_for(upcoming.date(), settings["period_rule"]))

    mail = mailer.settings()
    test_to, _cc = mailer.recipients(test=True)
    return render_template(
        "weekly/settings.html",
        settings=settings,
        users=users,
        selected_ids=selected_ids,
        selected_count=sum(1 for u in users if u.id in selected_ids),
        weekday_labels=WEEKDAY_LABELS,
        period_rules=PERIOD_RULES,
        placeholders=PLACEHOLDER_HELP,
        sample_placeholders=SAMPLE_PLACEHOLDER_HELP,
        preview=_preview(settings, today),
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
    ), status


@weekly_bp.route("/")
def settings_view():
    return _render(settings_store.load())


def _text(name, single_line=False):
    """フォームのテキスト(改行を統一。1行項目は改行を除く)。"""
    value = (request.form.get(name) or "").replace("\r\n", "\n").replace("\r", "\n")
    if single_line:
        value = " ".join(value.split("\n")).strip()
    return value


@weekly_bp.route("/settings", methods=["POST"])
def save_settings():
    errors = []
    values = {"enabled": request.form.get("enabled") == "1"}

    weekday = request.form.get("weekday", "")
    if weekday.isdecimal() and 0 <= int(weekday) <= 6:
        values["weekday"] = int(weekday)
    else:
        errors.append("送信する曜日を選択してください。")

    at = parse_hhmm(request.form.get("time"))
    if at is not None:
        values["time"] = at.strftime("%H:%M")
    else:
        errors.append("送信する時刻を「時:分」（例: 08:00）で入力してください。")

    rule = request.form.get("period_rule", "")
    if rule in PERIOD_RULES:
        values["period_rule"] = rule
    else:
        errors.append("対象期間のルールを選択してください。")

    # 対象者のチェックボックスの値は「ユーザーID:ログインID」(画面表示後のID再利用による取り違え防止)
    active = {u.id: u for u in get_active_users()}
    chosen = {}
    invalid = False
    for raw in request.form.getlist("target_user_ids"):
        user_id, _sep, username = raw.partition(":")
        user = active.get(int(user_id)) if user_id.isdecimal() else None
        if user is None or user.username != username:
            invalid = True
            continue
        chosen[user.id] = user.username
    if invalid:
        errors.append("対象者に有効でないユーザーが含まれています。画面を開き直して選び直してください。")
    values["target_user_ids"] = sorted(chosen)
    values["target_usernames"] = {str(i): name for i, name in chosen.items()}

    for key in ("team_sample", "person_sample", "guidelines", "mail_body"):
        values[key] = _text(key).strip("\n")
    values["filename_pattern"] = _text("filename_pattern", single_line=True)
    values["subject_pattern"] = _text("subject_pattern", single_line=True)
    if not values["filename_pattern"]:
        errors.append("ファイル名のパターンを入力してください。")
    if not values["subject_pattern"]:
        errors.append("メール件名のパターンを入力してください。")
    for key, label in (("team_sample", "チーム全体の見本"), ("person_sample", "個人の見本"),
                       ("guidelines", "書く際の注意点"), ("mail_body", "メール本文")):
        if len(values[key]) > settings_store.TEXT_MAX:
            errors.append("{}は{}文字以内にしてください。".format(label, settings_store.TEXT_MAX))

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
        current_app.logger.exception("週報の設定を保存できませんでした")
        flash("設定を保存できませんでした: {}".format(exc), "danger")
        current = settings_store.load()
        current.update(values)
        return _render(current, status=500)

    flash("週報の設定を保存しました。", "success")
    return redirect(url_for("weekly.settings_view"))


@weekly_bp.route("/preview")
def preview():
    """入力中のパターンで、今日作成した場合のファイル名・件名を返す。"""
    settings = settings_store.load()
    for key in ("filename_pattern", "subject_pattern"):
        if key in request.args:
            settings[key] = request.args.get(key, "")
    if request.args.get("period_rule") in PERIOD_RULES:
        settings["period_rule"] = request.args["period_rule"]
    return jsonify(_preview(settings, date.today()))


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
        return redirect(url_for("weekly.settings_view"))

    app = current_app._get_current_object()

    if action == service.DELIVER_DOWNLOAD:
        result = service.run_weekly(
            app, start, end, settings_store.TRIGGER_MANUAL, service.DELIVER_DOWNLOAD)
        if not result["ok"]:
            flash(result["message"], "danger")
            return redirect(url_for("weekly.settings_view"))
        return _docx_response(result["data"], result["filename"], start, end)

    if action == service.DELIVER_TEST:
        trigger, label = settings_store.TRIGGER_TEST, "テスト送信"
    else:
        trigger, label = settings_store.TRIGGER_MANUAL, "本番の宛先への送信"

    if not service.start_background(app, start, end, trigger, action):
        flash("別の送信を処理中です。完了してから、もう一度実行してください。", "warning")
        return redirect(url_for("weekly.settings_view"))

    flash("{}を開始しました（期間 {}）。結果は「前回の結果」に表示されます"
          "（作成に数十秒〜数分かかる場合があります。画面を再読み込みして確認してください）。"
          .format(label, period_label(start, end)), "info")
    return redirect(url_for("weekly.settings_view"))
