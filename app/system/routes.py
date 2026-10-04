"""システム設定の画面。マネージャーのみ(未ログインはログイン画面へ、メンバーは403)。

GET  /system/settings?tab=<タブ>     設定画面(タブ: config / weekly / overdue / skilltest)
POST /system/settings/config         基本設定の保存(instance/config.py)
POST /system/settings/weekly         週報の設定の保存(instance/weekly_settings.json)
POST /system/settings/overdue        期限超過通知の設定の保存(instance/overdue_settings.json)
POST /system/settings/skilltest      スキルテストの設定の保存(instance/skilltest_settings.json)
POST /system/settings/test-mail      メール接続テスト(保存済みの設定で、テスト送信の宛先へ短いメール)
POST /system/settings/test-ai        AI接続テスト(保存済みの設定で、短い問い合わせを1回)

タブごとに別のフォーム・保存ボタンを持ち、保存後は同じタブに戻る(?tab= で開くタブを指定)。
入力に誤りがあれば何も保存せず、入力中の内容(秘密の値は除く)を残して同じタブを再表示する。
"""
from datetime import datetime

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

from app import ai_client, mailer
from app.overdue import settings_form as overdue_form
from app.overdue import settings_store as overdue_store
from app.skilltest import settings_form as skilltest_form
from app.skilltest import settings_store as skilltest_store
from app.system import config_form
from app.weekly import settings_form as weekly_form
from app.weekly import settings_store as weekly_store

system_bp = Blueprint("system", __name__, url_prefix="/system")

TAB_CONFIG = "config"
TAB_WEEKLY = "weekly"
TAB_OVERDUE = "overdue"
TAB_SKILLTEST = "skilltest"

# (キー, 表示名, アイコン)
TABS = (
    (TAB_CONFIG, "基本設定（config）", "bi-sliders"),
    (TAB_WEEKLY, "週報", "bi-file-earmark-text"),
    (TAB_OVERDUE, "期限超過通知", "bi-alarm"),
    (TAB_SKILLTEST, "スキルテスト", "bi-patch-check"),
)
TAB_KEYS = tuple(key for key, _label, _icon in TABS)

# 機能ごとの設定(画面のJSONファイル): タブ → (入力チェック・表示のモジュール, 保存先のモジュール)
FEATURES = {
    TAB_WEEKLY: (weekly_form, weekly_store),
    TAB_OVERDUE: (overdue_form, overdue_store),
    TAB_SKILLTEST: (skilltest_form, skilltest_store),
}

# AI接続テストで送る問い合わせ(短く、応答も短くなるもの)
AI_TEST_MESSAGES = [
    {"role": "user", "content": "接続テストです。「OK」とだけ返してください。"},
]
AI_REPLY_MAX = 80


@system_bp.before_request
def _managers_only():
    """システム設定はマネージャーのみ(未ログインはログイン画面へ)。

    login_required は OPTIONS を素通しするため使わず、ここで直接確認する。
    """
    if not current_user.is_authenticated:
        return current_app.login_manager.unauthorized()
    if not getattr(current_user, "is_manager", False):
        abort(403)


def _tab_url(tab):
    return url_for("system.settings", tab=tab)


def _render(tab, status=200, config_state=None, config_errors=None, inputs=None):
    """設定画面を表示する。

    config_state / config_errors : 基本設定の入力エラーで再表示するときの入力と誤り
    inputs                       : 機能の設定の入力エラーで再表示するときの {タブ: 設定}
    """
    app = current_app._get_current_object()
    inputs = inputs or {}
    contexts = {}
    for key, (form_module, store) in FEATURES.items():
        settings = inputs[key] if key in inputs else store.load()
        contexts[key] = form_module.context(settings)
    return render_template(
        "system/settings.html",
        tab=tab,
        tabs=TABS,
        cfg=config_form.context(app, state=config_state, errors=config_errors),
        wk=contexts[TAB_WEEKLY],
        od=contexts[TAB_OVERDUE],
        st=contexts[TAB_SKILLTEST],
    ), status


@system_bp.route("/")
def index():
    return redirect(_tab_url(TAB_CONFIG))


@system_bp.route("/settings")
def settings():
    tab = request.args.get("tab", "")
    if tab not in TAB_KEYS:
        tab = TAB_CONFIG
    return _render(tab)


# --------------------------------------------------------------------------- #
# 基本設定(instance/config.py)
# --------------------------------------------------------------------------- #
@system_bp.route("/settings/config", methods=["POST"])
def save_config():
    app = current_app._get_current_object()
    result = config_form.save(app, request.form, current_user.username)

    if result.status == config_form.STATUS_INVALID:
        flash("入力内容に誤りがあります（{}件）。各項目のメッセージを確認してください。"
              "設定は保存していません。".format(len(result.errors)), "danger")
        return _render(TAB_CONFIG, status=400,
                       config_state=result.state, config_errors=result.errors)
    if result.status == config_form.STATUS_CONFLICT:
        flash(result.message, "warning")
        return redirect(_tab_url(TAB_CONFIG))
    if result.status == config_form.STATUS_ERROR:
        flash("基本設定を保存できませんでした: {}".format(result.message), "danger")
        return _render(TAB_CONFIG, status=500, config_state=result.state)
    if result.status == config_form.STATUS_UNCHANGED:
        message = "変更された項目はありません（設定ファイルは更新していません）。"
        if result.applied:
            message += "設定ファイルの値を実行中の設定に反映しました: {}。".format("、".join(result.applied))
        flash(message, "info")
        return redirect(_tab_url(TAB_CONFIG))

    message = "基本設定を保存しました（変更: {}）。変更前の内容は instance/config.py.bak に残しています。".format(
        "、".join(result.changed))
    live = [key for key in result.changed if key not in result.restart_changed]
    if live:
        message += "{} はすぐに反映しました。".format("、".join(live))
    others = [key for key in result.applied if key not in result.changed]
    if others:
        message += "設定ファイルを直接編集した {} も実行中の設定に反映しました。".format("、".join(others))
    flash(message, "success")
    if result.restart_changed:
        notice = "{} はサーバーの再起動後に反映されます。".format("、".join(result.restart_changed))
        if "SECRET_KEY" in result.restart_changed:
            notice += "再起動すると全員がログアウトされます。"
        flash(notice, "warning")
    return redirect(_tab_url(TAB_CONFIG))


@system_bp.route("/settings/test-mail", methods=["POST"])
def test_mail():
    """保存済みの設定で、テスト送信の宛先(MAIL_TEST_TO。空なら差出人)へ短いメールを送る。"""
    app = current_app._get_current_object()
    subject = "【接続テスト】{}".format(app.config.get("APP_NAME") or "業務管理システム")
    text = (
        "このメールは、{} の「システム設定」のメール接続テストで送信しました。\n"
        "送信日時: {}\n"
        "実行した人: {}\n"
        "\n"
        "返信は不要です。\n"
    ).format(app.config.get("APP_NAME") or "業務管理システム",
             datetime.now().strftime("%Y/%m/%d %H:%M"), current_user.display_name)
    ok, message = mailer.send(subject, text, test=True)
    message = config_form.mask_secrets(app, message)
    if ok:
        flash("メール接続テスト: OK（{}）".format(message), "success")
    else:
        flash("メール接続テスト: 失敗しました。{}".format(message), "danger")
    return redirect(_tab_url(TAB_CONFIG))


@system_bp.route("/settings/test-ai", methods=["POST"])
def test_ai():
    """保存済みの設定で、AIに短い問い合わせを1回送る。"""
    app = current_app._get_current_object()
    reply, error = ai_client.chat(AI_TEST_MESSAGES)
    if error:
        flash("AI接続テスト: 失敗しました。{}".format(config_form.mask_secrets(app, error)), "danger")
    else:
        reply = " ".join(str(reply).split())
        if len(reply) > AI_REPLY_MAX:
            reply = reply[:AI_REPLY_MAX] + "…"
        flash("AI接続テスト: OK（応答: {}）".format(config_form.mask_secrets(app, reply)), "success")
    return redirect(_tab_url(TAB_CONFIG))


# --------------------------------------------------------------------------- #
# 機能ごとの設定(週報・期限超過通知・スキルテスト)
# --------------------------------------------------------------------------- #
def _save_feature(tab):
    """機能の設定を保存する(入力チェックと保存先は各機能のモジュール)。"""
    form_module, store = FEATURES[tab]
    values, errors = form_module.parse(request.form)
    if errors:
        for message in errors:
            flash(message, "danger")
        # 入力中の内容を残したまま再表示する(保存はしない)
        return _render(tab, status=400,
                       inputs={tab: form_module.with_input(store.load(), values)})
    try:
        store.save(values)
    except OSError as exc:
        current_app.logger.exception("%sの設定を保存できませんでした", form_module.LABEL)
        flash("設定を保存できませんでした: {}".format(exc), "danger")
        return _render(tab, status=500,
                       inputs={tab: form_module.with_input(store.load(), values)})
    flash(form_module.SAVED_MESSAGE, "success")
    return redirect(_tab_url(tab))


@system_bp.route("/settings/weekly", methods=["POST"])
def save_weekly():
    return _save_feature(TAB_WEEKLY)


@system_bp.route("/settings/overdue", methods=["POST"])
def save_overdue():
    return _save_feature(TAB_OVERDUE)


@system_bp.route("/settings/skilltest", methods=["POST"])
def save_skilltest():
    return _save_feature(TAB_SKILLTEST)
