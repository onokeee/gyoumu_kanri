"""スキルテストの問題プールの集計と補充(マネージャー向け)。

補充(start_topup)は、指定したスキルの各レベルの「有効な問題」が目標数
(設定 pool_target_per_level)に届くまで、AIで問題を作ってプールに保存する。
AIの呼び出しには時間がかかるため、別スレッドで実行する(画面はすぐに戻る)。
補充は同時に1つだけ。結果は「前回の補充の結果」(instance/skilltest_settings.json)に残す。
"""
import math
import threading

from sqlalchemy import case, func

from app import ai_client
from app.extensions import db
from app.models.skill import Skill
from app.models.skilltest import SkillTestAnswer, SkillTestQuestion
from app.skilltest import generator, settings_store
from app.skilltest.service import is_testable

# 補充は同時に1つだけ(AIの呼び出しが重ならないように)
_topup_lock = threading.Lock()
_running = {"skill_name": ""}


def is_running():
    """問題の補充を実行中か。"""
    return _topup_lock.locked()


def running_skill_name():
    """補充を実行中のスキル名(実行中でなければ空)。"""
    return _running["skill_name"] if is_running() else ""


def counts_by_skill():
    """スキル・レベルごとの問題数: {skill_id: {level: {"active": n, "inactive": m}}}。"""
    rows = (
        db.session.query(
            SkillTestQuestion.skill_id, SkillTestQuestion.level,
            SkillTestQuestion.is_active, func.count(SkillTestQuestion.id))
        .group_by(SkillTestQuestion.skill_id, SkillTestQuestion.level,
                  SkillTestQuestion.is_active)
        .all()
    )
    result = {}
    for skill_id, level, active, count in rows:
        per_level = result.setdefault(skill_id, {})
        cell = per_level.setdefault(level, {"active": 0, "inactive": 0})
        cell["active" if active else "inactive"] += count
    return result


def usage_by_question(skill_id):
    """問題ごとの出題数と正解数: {question_id: {"served": n, "correct": m}}。"""
    rows = (
        db.session.query(
            SkillTestAnswer.question_id,
            func.count(SkillTestAnswer.id),
            func.sum(case((SkillTestAnswer.is_correct.is_(True), 1), else_=0)))
        .join(SkillTestQuestion, SkillTestAnswer.question_id == SkillTestQuestion.id)
        .filter(SkillTestQuestion.skill_id == skill_id,
                SkillTestAnswer.served_at.isnot(None))
        .group_by(SkillTestAnswer.question_id)
        .all()
    )
    return {qid: {"served": served or 0, "correct": int(correct or 0)}
            for qid, served, correct in rows}


def _topup(app, skill_id):
    """補充の本体(_topup_lock を持った状態で呼ぶ)。結果を「前回の補充の結果」に残す。"""
    with app.app_context():
        name = "ID {}".format(skill_id)
        try:
            skill = db.session.get(Skill, skill_id)
            if skill is None or not is_testable(skill):
                ok, message = False, "対象外のスキルです（有効なテクニカルスキルだけ補充できます）。"
            elif not ai_client.is_configured():
                name = skill.name
                ok, message = False, ("AI（ChatGPT互換API）が未設定のため問題を作成できません。"
                                      "システム設定の「基本設定」タブで AI_API_KEY または AI_API_URL を設定してください。")
            else:
                name = skill.name
                settings = settings_store.load()
                target = settings["pool_target_per_level"]
                parts, added_total, error = [], 0, None
                for level in settings_store.tested_levels(settings, skill.max_level):
                    active = SkillTestQuestion.query.filter_by(
                        skill_id=skill.id, level=level, is_active=True).count()
                    need = target - active
                    if need <= 0:
                        parts.append("Lv{} 追加なし（{}問）".format(level, active))
                        continue
                    created, error = generator.generate(
                        skill, level, need,
                        max_calls=int(math.ceil(need / float(generator.CHUNK_SIZE))) + 2)
                    added_total += len(created)
                    parts.append("Lv{} +{}（{}問）".format(level, len(created), active + len(created)))
                    if error:
                        break
                summary = "「{}」: {} ／ 計{}問を追加".format(name, "、".join(parts), added_total)
                if error:
                    ok, message = False, "{} ／ 途中で止まりました: {}".format(summary, error)
                else:
                    ok, message = True, summary
        except Exception as exc:
            app.logger.exception("スキルテストの問題の補充に失敗しました")
            db.session.rollback()
            ok, message = False, "「{}」の問題の補充中にエラーが発生しました: {}".format(name, exc)

        try:
            settings_store.set_last_result(settings_store.TRIGGER_MANUAL, ok, message)
        except Exception:
            app.logger.exception("スキルテストの補充の結果を保存できませんでした")
        return {"ok": ok, "message": message}


def start_topup(app, skill):
    """補充を別スレッドで始める。既に補充中なら何もせず False を返す。"""
    if not _topup_lock.acquire(blocking=False):
        return False
    _running["skill_name"] = skill.name
    skill_id = skill.id

    def worker():
        try:
            _topup(app, skill_id)
        except Exception:
            app.logger.exception("スキルテストの問題の補充でエラーが発生しました")
        finally:
            _running["skill_name"] = ""
            _topup_lock.release()

    try:
        threading.Thread(target=worker, name="skilltest-topup", daemon=True).start()
    except Exception:
        _running["skill_name"] = ""
        _topup_lock.release()
        raise
    return True


def run_topup(app, skill_id):
    """補充を呼び出したスレッドで最後まで実行する(動作確認用。補充中なら終わるまで待つ)。"""
    with _topup_lock:
        return _topup(app, skill_id)
