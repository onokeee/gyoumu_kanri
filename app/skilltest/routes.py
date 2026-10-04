"""スキルテストの画面。

メンバー(有効な role=member のみ。マネージャーは受験できない):
  GET  /skilltest/                         テストの一覧(現在の到達度・前回の受験・次に受験できる日時・ルール)
  POST /skilltest/start/<skill_id>         受験を始める(受験中のテストがあれば再開)
  GET  /skilltest/attempt/<id>             出題(1問ずつ。戻れない)
  POST /skilltest/attempt/<id>/answer      回答
  POST /skilltest/attempt/<id>/blur        画面から離れたことの記録(JavaScript から送る)
  GET  /skilltest/attempt/<id>/result      結果(レベルごとの正解数と結果のレベルだけ。正解は見せない)

マネージャーのみ(メンバーは403):
  GET  /skilltest/admin                    受験履歴(全員。メンバー・スキル・状態で絞り込み)
  GET  /skilltest/admin/attempt/<id>       受験の詳細(全問の問題・選択肢・正解・回答・所要時間・離脱回数)
  GET  /skilltest/admin/pool               問題プール(スキル・レベルごとの問題数、補充)
  GET  /skilltest/admin/pool/<skill_id>    スキルごとの問題の一覧(有効/無効の切り替え)
  POST /skilltest/admin/pool/<skill_id>/topup        問題の補充(バックグラウンド)
  POST /skilltest/admin/questions/<id>/toggle        問題の有効/無効の切り替え
  GET  /skilltest/admin/settings, POST 同じURL       旧URL。設定はシステム設定の「スキルテスト」タブへ移した
                                                     (GET はそのタブへ、POST はその保存へ転送する)

受験の操作はすべて本人の受験だけが対象(他人の受験は404)。
"""
from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user

from app import ai_client
from app.extensions import db
from app.models.skill import (
    SKILL_LEVEL_COLORS,
    SKILL_TECHNICAL,
    Skill,
    scale_for,
)
from app.models.skilltest import (
    ATTEMPT_EXPIRED,
    ATTEMPT_FINISHED,
    ATTEMPT_IN_PROGRESS,
    ATTEMPT_STATUS_LABELS,
    CHOICE_LETTERS,
    SkillTestAttempt,
    SkillTestQuestion,
)
from app.models.user import ROLE_MEMBER, User
from app.skilltest import pool, service, settings_store

skilltest_bp = Blueprint("skilltest", __name__, url_prefix="/skilltest")

# 問題一覧の絞り込み(有効/無効)
STATE_ACTIVE = "active"
STATE_INACTIVE = "inactive"


@skilltest_bp.before_request
def _guard():
    """ログイン必須。管理画面(admin_〜)はマネージャー、それ以外は受験できるメンバーだけ。

    login_required は OPTIONS を素通しするため使わず、ここで直接確認する。
    """
    if not current_user.is_authenticated:
        return current_app.login_manager.unauthorized()
    endpoint = request.endpoint or ""
    if not endpoint:
        return None  # 存在しないURL(404)
    if endpoint.startswith("skilltest.admin"):
        if not getattr(current_user, "is_manager", False):
            abort(403)
        return None
    if service.is_test_taker(current_user):
        return None
    if getattr(current_user, "is_manager", False) and endpoint == "skilltest.index" \
            and request.method == "GET":
        flash("マネージャーはスキル管理の対象外のため、スキルテストは受験できません。"
              "スキルテスト管理を表示します。", "info")
        return redirect(url_for("skilltest.admin_attempts"))
    abort(403)


def _tech_scale():
    return scale_for(SKILL_TECHNICAL)


def _rules(settings):
    """ルール説明用の値(テクニカルスキルの判定レベル・問題数・制限時間・期限)。"""
    levels = settings_store.tested_levels(settings, len(_tech_scale()) - 1)
    rows, total, seconds = settings_store.plan(settings, levels)
    return {
        "levels": levels,
        "rows": rows,
        "total": total,
        "minutes": int(round(seconds / 60.0)),
        "deadline_minutes": int(round(seconds / 60.0)) + service.DEADLINE_MARGIN_MIN,
        "pass_rate": settings["pass_rate"],
        "retake_days": settings["retake_days"],
        "top_level": levels[-1] if levels else 0,
        "grace_sec": service.GRACE_SEC,
    }


def _no_store(response):
    """出題画面などをブラウザにキャッシュさせない(戻るボタンで前の問題を出さない)。"""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


# --------------------------------------------------------------------------- #
# メンバー
# --------------------------------------------------------------------------- #
@skilltest_bp.route("/")
def index():
    me = current_user._get_current_object()
    service.expire_due(me.id)
    rows, running = service.member_overview(me)
    settings = settings_store.load()
    history = (
        SkillTestAttempt.query.filter_by(user_id=me.id)
        .order_by(SkillTestAttempt.started_at.desc(), SkillTestAttempt.id.desc())
        .limit(100)
        .all()
    )
    return render_template(
        "skilltest/index.html",
        rows=rows,
        running=running,
        history=history,
        rules=_rules(settings),
        scale=_tech_scale(),
        level_colors=SKILL_LEVEL_COLORS,
    )


@skilltest_bp.route("/start/<int:skill_id>", methods=["POST"])
def start(skill_id):
    skill = db.session.get(Skill, skill_id)
    if skill is None:
        abort(404)
    outcome = service.start_attempt(current_user._get_current_object(), skill)
    if outcome.error:
        flash(outcome.error, "danger" if outcome.error == service.MSG_NOT_READY else "warning")
        return redirect(url_for("skilltest.index"))
    if outcome.resumed:
        flash("受験中のテスト（{}）を再開します。".format(outcome.attempt.skill.name), "info")
    return redirect(url_for("skilltest.question", attempt_id=outcome.attempt.id))


@skilltest_bp.route("/attempt/<int:attempt_id>")
def question(attempt_id):
    attempt, item = service.prepare_question(attempt_id, current_user.id)
    if attempt is None:
        abort(404)
    if item is None:
        return redirect(url_for("skilltest.result", attempt_id=attempt.id))
    remaining = service.remaining_seconds(attempt, item)
    response = make_response(render_template(
        "skilltest/question.html",
        attempt=attempt,
        item=item,
        choices=item.choice_list,
        letters=CHOICE_LETTERS,
        remaining=remaining,
        answered=sum(1 for a in attempt.answers if a.answered_at is not None),
        scale=_tech_scale(),
    ))
    return _no_store(response)


@skilltest_bp.route("/attempt/<int:attempt_id>/answer", methods=["POST"])
def answer(attempt_id):
    seq = request.form.get("seq", type=int)
    raw = (request.form.get("choice") or "").strip()
    choice = int(raw) if raw.isdecimal() else None
    attempt, outcome = service.submit_answer(attempt_id, current_user.id, seq, choice)
    if attempt is None:
        abort(404)
    if outcome == service.ANSWER_NO_CHOICE:
        flash("選択肢を選んでから「回答する」を押してください（残り時間は進んでいます）。", "warning")
    elif outcome == service.ANSWER_TIMEOUT:
        flash("制限時間を過ぎたため、時間切れとして記録しました。", "warning")
    elif outcome == service.ANSWER_STALE:
        flash("この問題には回答済みです（前の問題には戻れません）。今の問題を表示します。", "info")
    if attempt.status != ATTEMPT_IN_PROGRESS:
        if attempt.status == ATTEMPT_EXPIRED:
            flash("全体の制限時間を過ぎたため、テストを終了しました（未回答は時間切れ）。", "warning")
        return redirect(url_for("skilltest.result", attempt_id=attempt.id))
    return redirect(url_for("skilltest.question", attempt_id=attempt.id))


@skilltest_bp.route("/attempt/<int:attempt_id>/blur", methods=["POST"])
def blur(attempt_id):
    attempt = db.session.get(SkillTestAttempt, attempt_id)
    if attempt is None or attempt.user_id != current_user.id:
        abort(404)
    service.record_blur(attempt_id, current_user.id, request.form.get("seq", type=int))
    return ("", 204)


@skilltest_bp.route("/attempt/<int:attempt_id>/result")
def result(attempt_id):
    me = current_user._get_current_object()
    attempt = db.session.get(SkillTestAttempt, attempt_id)
    if attempt is None or attempt.user_id != me.id:
        abort(404)
    if attempt.status == ATTEMPT_IN_PROGRESS:
        service.expire_due(me.id)
        db.session.expire_all()
        attempt = db.session.get(SkillTestAttempt, attempt_id)
        if attempt.status == ATTEMPT_IN_PROGRESS:
            return redirect(url_for("skilltest.question", attempt_id=attempt.id))
    settings = settings_store.load()
    available = None
    latest = service.last_attempt(me.id, attempt.skill_id)
    if latest is not None and latest.id == attempt.id:
        available = service.next_available(attempt, settings)
    return _no_store(make_response(render_template(
        "skilltest/result.html",
        attempt=attempt,
        level_results=attempt.level_result_list,
        scale=_tech_scale(),
        level_colors=SKILL_LEVEL_COLORS,
        available=available,
        now=service._now(),
    )))


# --------------------------------------------------------------------------- #
# マネージャー: 受験履歴
# --------------------------------------------------------------------------- #
def _int_arg(name):
    value = request.args.get(name, "").strip()
    return int(value) if value.isdecimal() else None


@skilltest_bp.route("/admin")
def admin_attempts():
    service.expire_due()
    filters = {
        "user_id": _int_arg("user_id"),
        "skill_id": _int_arg("skill_id"),
        "status": request.args.get("status", ""),
    }
    if filters["status"] not in ATTEMPT_STATUS_LABELS:
        filters["status"] = ""

    query = SkillTestAttempt.query
    if filters["user_id"]:
        query = query.filter(SkillTestAttempt.user_id == filters["user_id"])
    if filters["skill_id"]:
        query = query.filter(SkillTestAttempt.skill_id == filters["skill_id"])
    if filters["status"]:
        query = query.filter(SkillTestAttempt.status == filters["status"])
    attempts = query.order_by(
        SkillTestAttempt.started_at.desc(), SkillTestAttempt.id.desc()).all()

    # 絞り込みの選択肢: 受験したことのある人＋今のメンバー / テクニカルスキル
    taker_ids = {row[0] for row in db.session.query(SkillTestAttempt.user_id).distinct()}
    users = [
        u for u in User.query.order_by(User.display_name).all()
        if u.id in taker_ids or (u.is_active and u.role == ROLE_MEMBER)
    ]
    skills = (
        Skill.query.filter_by(skill_type=SKILL_TECHNICAL)
        .order_by(Skill.is_active.desc(), Skill.sort_order, Skill.name)
        .all()
    )
    return render_template(
        "skilltest/admin_attempts.html",
        attempts=attempts,
        filters=filters,
        users=users,
        skills=skills,
        status_labels=ATTEMPT_STATUS_LABELS,
        scale=_tech_scale(),
        level_colors=SKILL_LEVEL_COLORS,
    )


@skilltest_bp.route("/admin/attempt/<int:attempt_id>")
def admin_attempt(attempt_id):
    attempt = db.session.get(SkillTestAttempt, attempt_id)
    if attempt is None:
        abort(404)
    if attempt.status == ATTEMPT_IN_PROGRESS:
        service.expire_due(attempt.user_id)
        db.session.expire_all()
        attempt = db.session.get(SkillTestAttempt, attempt_id)
    return render_template(
        "skilltest/admin_attempt.html",
        attempt=attempt,
        level_results=attempt.level_result_list,
        snapshot=attempt.settings_dict,
        letters=CHOICE_LETTERS,
        scale=_tech_scale(),
        level_colors=SKILL_LEVEL_COLORS,
        status_finished=ATTEMPT_FINISHED,
    )


# --------------------------------------------------------------------------- #
# マネージャー: 問題プール
# --------------------------------------------------------------------------- #
@skilltest_bp.route("/admin/pool")
def admin_pool():
    settings = settings_store.load()
    counts = pool.counts_by_skill()
    skills = (
        Skill.query.filter_by(skill_type=SKILL_TECHNICAL)
        .order_by(Skill.is_active.desc(), Skill.sort_order, Skill.name)
        .all()
    )
    levels = settings_store.tested_levels(settings, len(_tech_scale()) - 1)
    rows = []
    for skill in skills:
        per_level = counts.get(skill.id, {})
        rows.append({
            "skill": skill,
            "testable": service.is_testable(skill),
            "cells": [
                {
                    "level": lv,
                    "active": per_level.get(lv, {}).get("active", 0),
                    "inactive": per_level.get(lv, {}).get("inactive", 0),
                    "need": settings_store.questions_for(settings, lv),
                }
                for lv in levels
            ],
            "total": sum(c["active"] + c["inactive"] for c in per_level.values()),
        })
    return render_template(
        "skilltest/admin_pool.html",
        rows=rows,
        levels=levels,
        settings=settings,
        target=settings["pool_target_per_level"],
        last=settings["last_result"],
        running=pool.is_running(),
        running_name=pool.running_skill_name(),
        ai_enabled=ai_client.is_configured(),
        ai_status=ai_client.status_label(),
        scale=_tech_scale(),
    )


@skilltest_bp.route("/admin/pool/<int:skill_id>")
def admin_pool_skill(skill_id):
    skill = db.session.get(Skill, skill_id)
    if skill is None:
        abort(404)
    level = _int_arg("level")
    state = request.args.get("state", "")
    if state not in (STATE_ACTIVE, STATE_INACTIVE):
        state = ""
    query = SkillTestQuestion.query.filter_by(skill_id=skill.id)
    if level:
        query = query.filter(SkillTestQuestion.level == level)
    if state:
        query = query.filter(SkillTestQuestion.is_active.is_(state == STATE_ACTIVE))
    questions = query.order_by(SkillTestQuestion.level, SkillTestQuestion.id).all()
    settings = settings_store.load()
    return render_template(
        "skilltest/admin_pool_skill.html",
        skill=skill,
        questions=questions,
        usage=pool.usage_by_question(skill.id),
        counts=pool.counts_by_skill().get(skill.id, {}),
        levels=settings_store.tested_levels(settings, skill.max_level) or [1, 2, 3, 4],
        filters={"level": level, "state": state},
        testable=service.is_testable(skill),
        letters=CHOICE_LETTERS,
        scale=scale_for(skill.skill_type),
        running=pool.is_running(),
        ai_enabled=ai_client.is_configured(),
        target=settings["pool_target_per_level"],
    )


@skilltest_bp.route("/admin/pool/<int:skill_id>/topup", methods=["POST"])
def admin_topup(skill_id):
    skill = db.session.get(Skill, skill_id)
    if skill is None:
        abort(404)
    back = url_for("skilltest.admin_pool_skill", skill_id=skill.id) \
        if request.form.get("back") == "skill" else url_for("skilltest.admin_pool")
    if not service.is_testable(skill):
        flash("有効なテクニカルスキルだけ補充できます。", "warning")
        return redirect(back)
    if not ai_client.is_configured():
        flash("AI（ChatGPT互換API）が未設定のため、問題を作成できません。", "danger")
        return redirect(back)
    app = current_app._get_current_object()
    if not pool.start_topup(app, skill):
        flash("別の補充を処理中です。完了してから、もう一度実行してください。", "warning")
        return redirect(back)
    flash("「{}」の問題の補充を開始しました。数分かかることがあります。結果は問題プールの"
          "「前回の補充の結果」に表示されます（画面を再読み込みして確認してください）。".format(skill.name),
          "info")
    return redirect(back)


@skilltest_bp.route("/admin/questions/<int:question_id>/toggle", methods=["POST"])
def admin_toggle_question(question_id):
    question = db.session.get(SkillTestQuestion, question_id)
    if question is None:
        abort(404)
    question.is_active = not question.is_active
    db.session.commit()
    flash("問題 #{} を{}にしました。".format(
        question.id, "有効" if question.is_active else "無効（今後は出題しない）"), "info")
    params = {"skill_id": question.skill_id}
    level = request.form.get("level", "")
    state = request.form.get("state", "")
    if level.isdecimal():
        params["level"] = int(level)
    if state in (STATE_ACTIVE, STATE_INACTIVE):
        params["state"] = state
    return redirect(url_for("skilltest.admin_pool_skill", **params)
                    + "#q{}".format(question.id))


# --------------------------------------------------------------------------- #
# マネージャー: 設定(旧URL)
# --------------------------------------------------------------------------- #
@skilltest_bp.route("/admin/settings", methods=["GET", "POST"])
def admin_settings():
    """旧URL。設定はシステム設定の「スキルテスト」タブに移した。

    GET はそのタブへ移動し、POST は 307 でそのタブの保存へ転送する(フォームの内容はそのまま届く)。
    入力チェックは settings_form.py、保存先は instance/skilltest_settings.json のまま。
    """
    if request.method == "POST":
        return redirect(url_for("system.save_skilltest"), code=307)
    return redirect(url_for("system.settings", tab="skilltest"))
