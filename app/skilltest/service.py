"""スキルテストの受験の流れ(開始・出題・回答・離脱の記録・採点・到達度の自動登録)。

ルール(画面・README にも同じことを書いている):
  ・対象は「有効なテクニカルスキル」だけ。判定するレベルは 1〜min(上限 4, スキルの最大レベル)
  ・問題はやさしい順(レベル1→上限)に1問ずつ出す(同じレベルの中はランダム)。戻れない
  ・各問の制限時間はサーバー側で計る(初めて表示した日時 served_at を保存。再読み込みしても
    残り時間は戻らない)。制限時間＋GRACE_SEC 秒を過ぎた回答は時間切れ(不正解)
  ・全体の期限(各問の制限時間の合計＋DEADLINE_MARGIN_MIN 分)を過ぎた受験は、次に触れたとき
    (一覧・出題・回答・管理画面の表示)に自動で終了し、未回答は時間切れとして同じように採点する
  ・採点: レベルLは「Lの正答率が合格ライン以上」かつ「L未満のレベルがすべて合格」のとき合格。
    結果のレベル = 合格した最も高いレベル(レベル1が不合格なら0)
  ・到達度の自動登録: 結果のレベルが現在の到達度より高いときだけ skill_ratings に登録する
    (マネージャーが付けた到達度を下げることはない)。評価者は本人、メモは
    「スキルテストで自動登録（YYYY/MM/DD・正答率NN%）」
  ・受験できるのは有効なメンバー(role=member)だけ。受験中のテストは1人1つ(開くと再開)
  ・同じスキルの再受験は、前回の受験開始から retake_days 日後から

時刻はすべて app/models/skilltest.py の _now() から取る(動作確認で差し替えられるように)。
同じ人の操作(開始・出題・回答・離脱の記録・自動終了)はプロセス内のロックで直列化する。
"""
import json
import math
import random
import threading
import time
from collections import namedtuple
from datetime import timedelta

from flask import current_app
from sqlalchemy import func

from app import ai_client
from app.extensions import db
from app.models import skilltest as skilltest_models
from app.models.skill import SKILL_TECHNICAL, Skill, SkillRating
from app.models.skilltest import (
    ATTEMPT_EXPIRED,
    ATTEMPT_FINISHED,
    ATTEMPT_IN_PROGRESS,
    SkillTestAnswer,
    SkillTestAttempt,
    SkillTestQuestion,
)
from app.models.user import ROLE_MEMBER
from app.skilltest import generator, settings_store

# 制限時間を過ぎてから回答を受け付ける猶予(秒。通信の遅れの分)
GRACE_SEC = 5
# 全体の期限 = 各問の制限時間の合計 ＋ この分数
DEADLINE_MARGIN_MIN = 10
# 選択せずに送られた回答(時間切れの自動送信)を「時間切れ」とみなす、制限時間の手前の秒数
AUTO_SUBMIT_TOLERANCE_SEC = 3
# 離脱回数の上限(異常な送信で数が膨らみすぎないように)
BLUR_MAX = 9999
# 受験開始時に不足分をAIで作るのに使う時間の上限(秒)。過ぎたら新しい呼び出しはせず再出題に回す
START_AI_BUDGET_SEC = 150

# 受験開始の失敗時のメッセージ
MSG_NOT_READY = "問題が準備できません。マネージャーに連絡してください。"

_rng = random.SystemRandom()

# 同じ人の操作を直列化するロック(開始の準備は時間がかかるので別のロック)
_locks_guard = threading.Lock()
_user_locks = {}
_start_locks = {}


def _now():
    """現在の日時(app/models/skilltest.py の _now() を使う。差し替えはそちらで行う)。"""
    return skilltest_models._now()


def _lock_for(table, user_id, factory):
    with _locks_guard:
        lock = table.get(user_id)
        if lock is None:
            lock = table[user_id] = factory()
        return lock


def user_lock(user_id):
    """その人の受験の操作(出題・回答・離脱の記録・自動終了)を直列化するロック。"""
    return _lock_for(_user_locks, user_id, threading.RLock)


def _start_lock(user_id):
    return _lock_for(_start_locks, user_id, threading.Lock)


# --------------------------------------------------------------------------- #
# 対象者・対象スキル
# --------------------------------------------------------------------------- #
def is_test_taker(user):
    """スキルテストを受験できる人か(有効なメンバー。マネージャーはスキル管理の対象外)。"""
    return (user is not None and getattr(user, "is_authenticated", True)
            and bool(getattr(user, "is_active", False))
            and getattr(user, "role", None) == ROLE_MEMBER)


def is_testable(skill):
    """テストの対象スキルか(有効なテクニカルスキル)。"""
    return skill is not None and skill.is_active and skill.skill_type == SKILL_TECHNICAL


def testable_skills():
    """テストの対象スキル(有効なテクニカルスキル。スキルマップと同じ並び)。"""
    return (
        Skill.query.filter_by(skill_type=SKILL_TECHNICAL, is_active=True)
        .order_by(Skill.sort_order, Skill.name)
        .all()
    )


def current_level(user_id, skill_id):
    """今の到達度(未評価は0)。"""
    rating = SkillRating.query.filter_by(user_id=user_id, skill_id=skill_id).first()
    return rating.level if rating else 0


def in_progress_attempt(user_id):
    """受験中のテスト(1人1つ。無ければ None)。"""
    return (
        SkillTestAttempt.query.filter_by(user_id=user_id, status=ATTEMPT_IN_PROGRESS)
        .order_by(SkillTestAttempt.started_at.desc(), SkillTestAttempt.id.desc())
        .first()
    )


def last_attempt(user_id, skill_id):
    """そのスキルの直近の受験(無ければ None)。"""
    return (
        SkillTestAttempt.query.filter_by(user_id=user_id, skill_id=skill_id)
        .order_by(SkillTestAttempt.started_at.desc(), SkillTestAttempt.id.desc())
        .first()
    )


def next_available(attempt, settings):
    """次に受験できる日時(前回の受験開始＋再受験までの日数)。制限が無ければ None。"""
    days = int(settings.get("retake_days") or 0)
    if attempt is None or days <= 0:
        return None
    return attempt.started_at + timedelta(days=days)


# --------------------------------------------------------------------------- #
# 採点と到達度の自動登録
# --------------------------------------------------------------------------- #
def _rate_percent(correct, total):
    return round(correct * 100.0 / total, 1) if total else 0.0


def grade_levels(answers, pass_rate):
    """レベルごとの結果と、結果のレベルを返す: (結果のリスト, 結果のレベル)。

    レベルLの合格 = Lの正答率が合格ライン以上 かつ L未満のレベルがすべて合格。
    """
    results = []
    result_level = 0
    lower_passed = True
    for level in sorted({a.level for a in answers}):
        rows = [a for a in answers if a.level == level]
        total = len(rows)
        correct = sum(1 for a in rows if a.is_correct)
        # 浮動小数の誤差を避けるため整数で比べる(correct/total >= pass_rate/100)
        rate_ok = total > 0 and correct * 100 >= pass_rate * total
        passed = lower_passed and rate_ok
        if passed:
            result_level = level
        lower_passed = passed
        results.append({
            "level": level,
            "total": total,
            "correct": correct,
            "rate": _rate_percent(correct, total),
            "rate_ok": rate_ok,
            "passed": passed,
        })
    return results, result_level


def rating_note(finished_at, correct, total):
    """自動登録した到達度のメモ(200文字以内)。"""
    rate = int(round(correct * 100.0 / total)) if total else 0
    return "スキルテストで自動登録（{}・正答率{}%）".format(
        finished_at.strftime("%Y/%m/%d"), rate)[:200]


def _finish(attempt, now, status):
    """受験を終了し、採点して、必要なら到達度を自動登録する(commit は呼び出し側)。"""
    snapshot = attempt.settings_dict
    pass_rate = int(snapshot.get("pass_rate") or settings_store.DEFAULTS["pass_rate"])
    answers = list(attempt.answers)
    results, result_level = grade_levels(answers, pass_rate)

    attempt.status = status
    attempt.finished_at = now
    attempt.total = len(answers)
    attempt.correct = sum(1 for a in answers if a.is_correct)
    attempt.level_results = json.dumps(results, ensure_ascii=False)
    attempt.result_level = result_level

    rating = SkillRating.query.filter_by(
        skill_id=attempt.skill_id, user_id=attempt.user_id).first()
    prev = rating.level if rating else 0
    attempt.prev_level = prev
    # 受験後にマネージャーになった・無効化された人は登録しない(スキル管理の対象外)
    eligible = is_test_taker(attempt.user)
    if eligible and result_level > prev:
        if rating is None:
            rating = SkillRating(skill_id=attempt.skill_id, user_id=attempt.user_id)
            db.session.add(rating)
        rating.level = result_level
        rating.note = rating_note(now, attempt.correct, attempt.total)
        rating.rated_by_id = attempt.user_id
        rating.rated_at = now
        attempt.applied = True
        attempt.new_level = result_level
    else:
        attempt.applied = False
        attempt.new_level = prev


def _expire(attempt, now):
    """全体の期限を過ぎた受験を終了する。未回答はすべて時間切れ(不正解)として採点する。

    終了日時は「全体の期限」とする(最後の回答がそれより後なら、その回答の日時)。
    放置された受験が後日(一覧・管理画面を開いたときなど)に終了しても、終了日時・
    到達度の登録日時・メモの日付が後日にならないようにする。
    表示したまま未回答の問題の所要秒数は「制限時間＋猶予」までとする。
    """
    end = min(now, attempt.deadline_at)
    answered = [a.answered_at for a in attempt.answers if a.answered_at is not None]
    if answered:
        end = max(end, max(answered))
    for answer in attempt.answers:
        if answer.answered_at is None:
            answer.timed_out = True
            answer.is_correct = False
            if answer.served_at is not None:
                elapsed = max(0.0, (end - answer.served_at).total_seconds())
                answer.elapsed_sec = round(min(elapsed, answer.time_limit_sec + GRACE_SEC), 1)
    _finish(attempt, end, ATTEMPT_EXPIRED)


def _is_past_deadline(attempt, now, grace=0):
    return now > attempt.deadline_at + timedelta(seconds=grace)


def expire_due(user_id=None):
    """全体の期限を過ぎた受験中のテストを終了する(user_id を指定するとその人の分だけ)。

    一覧・出題・管理画面などを開いたときに呼ぶ(終了した件数を返す)。
    """
    now = _now()
    query = SkillTestAttempt.query.filter(
        SkillTestAttempt.status == ATTEMPT_IN_PROGRESS,
        SkillTestAttempt.deadline_at < now,
    )
    if user_id is not None:
        query = query.filter(SkillTestAttempt.user_id == user_id)
    targets = [(a.id, a.user_id) for a in query.all()]
    closed = 0
    for attempt_id, owner_id in targets:
        with user_lock(owner_id):
            db.session.expire_all()
            attempt = db.session.get(SkillTestAttempt, attempt_id)
            if attempt is None or attempt.status != ATTEMPT_IN_PROGRESS:
                continue
            now = _now()
            if not _is_past_deadline(attempt, now):
                continue
            _expire(attempt, now)
            db.session.commit()
            closed += 1
    return closed


# --------------------------------------------------------------------------- #
# 受験の開始(問題の選択・不足分のAI作成・受験済みの問題の再出題)
# --------------------------------------------------------------------------- #
StartOutcome = namedtuple("StartOutcome", "attempt resumed error")


def _served_history(user_id, skill_id):
    """その人がそのスキルで表示された問題: {question_id: 最後に表示した日時}。"""
    rows = (
        db.session.query(SkillTestAnswer.question_id, func.max(SkillTestAnswer.served_at))
        .join(SkillTestAttempt, SkillTestAnswer.attempt_id == SkillTestAttempt.id)
        .filter(
            SkillTestAttempt.user_id == user_id,
            SkillTestAttempt.skill_id == skill_id,
            SkillTestAnswer.served_at.isnot(None),
            SkillTestAnswer.question_id.isnot(None),
        )
        .group_by(SkillTestAnswer.question_id)
        .all()
    )
    return {qid: served for qid, served in rows}


def _usable(question):
    """出題に使える問題か(選択肢が4つ・正解の位置が正しい)。"""
    index = question.answer_index
    return (len(question.choice_list) == 4 and isinstance(index, int)
            and not isinstance(index, bool) and 0 <= index <= 3)


def _active_questions(skill_id, level):
    return [
        q for q in SkillTestQuestion.query.filter_by(
            skill_id=skill_id, level=level, is_active=True).all()
        if _usable(q)
    ]


def _pick_for_level(skill, level, count, served, state):
    """1つのレベルの問題を選ぶ: (問題のリスト, 再出題した数)。

    1. その人に表示したことのない有効な問題(ランダム)
    2. 足りなければ不足分をAIで作る(同期。1回で最大10問ずつ)
    3. まだ足りなければ、その人に表示したのが最も古い問題から再出題する
    """
    active = _active_questions(skill.id, level)
    unseen = [q for q in active if q.id not in served]
    _rng.shuffle(unseen)
    picked = unseen[:count]

    if len(picked) < count and state["ai"]:
        created, error = generator.generate(
            skill, level, count - len(picked), stop_at=state["stop_at"])
        picked += created[:count - len(picked)]
        state["generated"] += len(created)
        if error:
            state["errors"].append("Lv{}: {}".format(level, error))
            if not created:
                # 1問も作れなかった(AIに接続できない等)。残りのレベルでは待たずに諦める
                state["ai"] = False

    reused = 0
    if len(picked) < count:
        picked_ids = {q.id for q in picked}
        seen = sorted(
            (q for q in active if q.id in served and q.id not in picked_ids),
            key=lambda q: (served[q.id], q.id),
        )
        extra = seen[:count - len(picked)]
        reused = len(extra)
        picked += extra
    return picked, reused


def _shuffled_choices(question):
    """選択肢を並べ替える: (並べ替えた選択肢, 並べ替えた後の正解の位置)。"""
    choices = question.choice_list
    order = list(range(len(choices)))
    _rng.shuffle(order)
    return [choices[i] for i in order], order.index(question.answer_index)


def start_attempt(user, skill):
    """受験を始める(受験中のテストがあればそれを返す)。戻り値は StartOutcome。

    attempt : 始めた(または再開する)受験。始められなければ None
    resumed : 受験中のテストを再開する場合 True
    error   : 始められない理由(画面に表示する文言)
    """
    if not is_test_taker(user):
        return StartOutcome(None, False, "スキルテストを受験できるのは、有効なメンバーだけです。")
    if not is_testable(skill):
        return StartOutcome(None, False, "このスキルはスキルテストの対象外です（有効なテクニカルスキルだけが対象）。")

    start_lock = _start_lock(user.id)
    if not start_lock.acquire(blocking=False):
        return StartOutcome(None, False, "問題を準備中です。しばらく待ってから、もう一度開いてください。")
    try:
        expire_due(user.id)
        existing = in_progress_attempt(user.id)
        if existing is not None:
            return StartOutcome(existing, True, None)

        settings = settings_store.load()
        now = _now()
        available = next_available(last_attempt(user.id, skill.id), settings)
        if available is not None and now < available:
            return StartOutcome(None, False, "このスキルは {} から再受験できます。".format(
                available.strftime("%Y/%m/%d %H:%M")))

        levels = settings_store.tested_levels(settings, skill.max_level)
        if not levels:
            return StartOutcome(None, False, "このスキルはテストで判定できるレベルがありません。")
        rows, _total, seconds = settings_store.plan(settings, levels)

        served = _served_history(user.id, skill.id)
        state = {"ai": ai_client.is_configured(), "generated": 0, "errors": [],
                 "stop_at": time.monotonic() + START_AI_BUDGET_SEC}
        picked_by_level = []
        reused_total = 0
        short = []
        for row in rows:
            picked, reused = _pick_for_level(skill, row["level"], row["count"], served, state)
            reused_total += reused
            if len(picked) < row["count"]:
                short.append("Lv{} {}/{}問".format(row["level"], len(picked), row["count"]))
            picked_by_level.append((row, picked))
        if short:
            current_app.logger.warning(
                "スキルテストの問題が不足しています（スキルID %s: %s）%s", skill.id,
                "、".join(short), " ／ ".join(state["errors"]))
            return StartOutcome(None, False, MSG_NOT_READY)

        with user_lock(user.id):
            db.session.expire_all()
            existing = in_progress_attempt(user.id)
            if existing is not None:
                return StartOutcome(existing, True, None)
            now = _now()
            snapshot = {
                "levels": levels,
                "questions_per_level": {str(r["level"]): r["count"] for r in rows},
                "time_limits": {str(r["level"]): r["limit"] for r in rows},
                "pass_rate": settings["pass_rate"],
                "retake_days": settings["retake_days"],
                "max_auto_level": settings["max_auto_level"],
                "grace_sec": GRACE_SEC,
                "deadline_margin_min": DEADLINE_MARGIN_MIN,
            }
            attempt = SkillTestAttempt(
                user_id=user.id,
                skill_id=skill.id,
                status=ATTEMPT_IN_PROGRESS,
                started_at=now,
                deadline_at=now + timedelta(seconds=seconds, minutes=DEADLINE_MARGIN_MIN),
                total=sum(r["count"] for r in rows),
                correct=0,
                applied=False,
                blur_count=0,
                reused_count=reused_total,
                settings_snapshot=json.dumps(snapshot, ensure_ascii=False),
            )
            db.session.add(attempt)
            seq = 0
            for row, picked in picked_by_level:
                _rng.shuffle(picked)  # 同じレベルの中はランダムな順
                for question in picked:
                    seq += 1
                    choices, correct_index = _shuffled_choices(question)
                    attempt.answers.append(SkillTestAnswer(
                        seq=seq,
                        level=row["level"],
                        question_id=question.id,
                        question=question.question,
                        choices=json.dumps(choices, ensure_ascii=False),
                        correct_index=correct_index,
                        is_correct=False,
                        timed_out=False,
                        time_limit_sec=row["limit"],
                        blur_count=0,
                    ))
            db.session.commit()
            return StartOutcome(attempt, False, None)
    finally:
        start_lock.release()


# --------------------------------------------------------------------------- #
# 出題・回答・離脱の記録
# --------------------------------------------------------------------------- #
def _current(attempt):
    """次に答える問題(未確定のうち最初のもの)。全問確定済みなら None。"""
    return next((a for a in attempt.answers if a.answered_at is None), None)


def _elapsed(answer, now):
    return (now - answer.served_at).total_seconds() if answer.served_at else 0.0


def _close_timeout(answer, now, selected=None):
    """時間切れとして確定する(不正解)。"""
    answer.timed_out = True
    answer.is_correct = False
    answer.selected_index = selected
    answer.answered_at = now
    answer.elapsed_sec = round(_elapsed(answer, now), 1)


def _finish_if_done(attempt, now):
    if _current(attempt) is None and attempt.status == ATTEMPT_IN_PROGRESS:
        _finish(attempt, now, ATTEMPT_FINISHED)


def prepare_question(attempt_id, user_id):
    """今の問題を表示できる状態にして返す(初めて表示する問題は served_at を記録する)。

    制限時間＋猶予を過ぎた問題は時間切れとして次へ進む。全体の期限を過ぎていれば終了する。
    戻り値: (受験, 表示する問題 または None〔終了済み〕)
    """
    with user_lock(user_id):
        db.session.expire_all()
        attempt = db.session.get(SkillTestAttempt, attempt_id)
        if attempt is None or attempt.user_id != user_id:
            return None, None
        if attempt.status != ATTEMPT_IN_PROGRESS:
            return attempt, None
        now = _now()
        if _is_past_deadline(attempt, now):
            _expire(attempt, now)
            db.session.commit()
            return attempt, None
        changed = False
        while True:
            answer = _current(attempt)
            if answer is None:
                _finish(attempt, now, ATTEMPT_FINISHED)
                changed = True
                break
            if answer.served_at is None:
                answer.served_at = now
                changed = True
                break
            if _elapsed(answer, now) > answer.time_limit_sec + GRACE_SEC:
                _close_timeout(answer, now)
                changed = True
                continue
            break
        if changed:
            db.session.commit()
        return attempt, answer


def remaining_seconds(attempt, answer, now=None):
    """その問題の残り時間(秒。全体の期限も考慮。0未満は0)。

    秒未満は切り上げる(画面の自動送信が制限時間より早くならないように。遅れた分は猶予の範囲)。
    """
    now = now or _now()
    left = answer.time_limit_sec - _elapsed(answer, now)
    left = min(left, (attempt.deadline_at - now).total_seconds())
    return max(0, int(math.ceil(left)))


# submit_answer の結果
ANSWER_RECORDED = "recorded"    # 回答を記録した
ANSWER_TIMEOUT = "timeout"      # 時間切れとして記録した
ANSWER_NO_CHOICE = "no_choice"  # 選択肢が選ばれていない(時間内。記録しない)
ANSWER_STALE = "stale"          # 今の問題ではない(二重送信・戻るボタンなど。無視)
ANSWER_CLOSED = "closed"        # 受験は終了している(期限切れで今終了した場合も含む)


def submit_answer(attempt_id, user_id, seq, choice):
    """回答を記録する。戻り値: (受験, 結果 ANSWER_〜)。

    seq    : 回答した問題の出題順(画面に出した今の問題と一致しなければ無視)
    choice : 選んだ選択肢の位置(画面に出した順の 0〜3)。未選択は None
    """
    with user_lock(user_id):
        db.session.expire_all()
        attempt = db.session.get(SkillTestAttempt, attempt_id)
        if attempt is None or attempt.user_id != user_id:
            return None, ANSWER_STALE
        if attempt.status != ATTEMPT_IN_PROGRESS:
            return attempt, ANSWER_CLOSED
        now = _now()
        if _is_past_deadline(attempt, now, grace=GRACE_SEC):
            _expire(attempt, now)
            db.session.commit()
            return attempt, ANSWER_CLOSED

        answer = _current(attempt)
        if answer is None:
            _finish(attempt, now, ATTEMPT_FINISHED)
            db.session.commit()
            return attempt, ANSWER_CLOSED
        if answer.seq != seq or answer.served_at is None:
            return attempt, ANSWER_STALE
        if choice is not None and not 0 <= choice < len(answer.choice_list):
            choice = None

        elapsed = _elapsed(answer, now)
        if elapsed > answer.time_limit_sec + GRACE_SEC:
            _close_timeout(answer, now, selected=choice)
            outcome = ANSWER_TIMEOUT
        elif choice is None:
            # 画面の残り時間は「問題の制限時間」と「全体の期限」の短い方。全体の期限で0になった
            # 自動送信なら、受験を終了する(未回答は時間切れ)
            if (attempt.deadline_at - now).total_seconds() <= AUTO_SUBMIT_TOLERANCE_SEC:
                _expire(attempt, now)
                db.session.commit()
                return attempt, ANSWER_CLOSED
            if elapsed < answer.time_limit_sec - AUTO_SUBMIT_TOLERANCE_SEC:
                return attempt, ANSWER_NO_CHOICE
            _close_timeout(answer, now)
            outcome = ANSWER_TIMEOUT
        else:
            answer.selected_index = choice
            answer.is_correct = choice == answer.correct_index
            answer.timed_out = False
            answer.answered_at = now
            answer.elapsed_sec = round(elapsed, 1)
            outcome = ANSWER_RECORDED

        if _current(attempt) is not None and _is_past_deadline(attempt, now):
            # 全体の期限を過ぎてから(猶予の間に)回答した。残りは時間切れとして終了する
            _expire(attempt, now)
        else:
            _finish_if_done(attempt, now)
        db.session.commit()
        return attempt, outcome


def record_blur(attempt_id, user_id, seq):
    """画面から離れた(タブの切り替え・ウィンドウの切り替えなど)ことを記録する。

    受験中だけ数える。表示済みの問題の出題順 seq が送られれば、その問題の回数にも数える。
    """
    with user_lock(user_id):
        db.session.expire_all()
        attempt = db.session.get(SkillTestAttempt, attempt_id)
        if attempt is None or attempt.user_id != user_id:
            return False
        if attempt.status != ATTEMPT_IN_PROGRESS:
            return False
        attempt.blur_count = min((attempt.blur_count or 0) + 1, BLUR_MAX)
        answer = next((a for a in attempt.answers if a.seq == seq), None)
        if answer is not None and answer.served_at is not None:
            answer.blur_count = min((answer.blur_count or 0) + 1, BLUR_MAX)
        db.session.commit()
        return True


# --------------------------------------------------------------------------- #
# 画面用のまとめ
# --------------------------------------------------------------------------- #
def member_overview(user):
    """メンバーのテスト一覧の行(スキルごとの現在の到達度・前回の受験・次に受験できる日時)。"""
    settings = settings_store.load()
    now = _now()
    running = in_progress_attempt(user.id)
    ratings = {r.skill_id: r for r in SkillRating.query.filter_by(user_id=user.id).all()}
    rows = []
    for skill in testable_skills():
        last = last_attempt(user.id, skill.id)
        available = next_available(last, settings)
        levels = settings_store.tested_levels(settings, skill.max_level)
        rating = ratings.get(skill.id)
        level = rating.level if rating else 0
        if running is not None and running.skill_id == skill.id:
            state = "resume"
        elif running is not None:
            state = "busy"          # 別のスキルを受験中
        elif available is not None and now < available:
            state = "wait"          # 再受験の間隔をあけている
        else:
            state = "ready"
        rows.append({
            "skill": skill,
            "level": level,
            "rating": rating,
            "last": last,
            "available": available,
            "state": state,
            "top_level": levels[-1] if levels else 0,
            "capped": bool(levels) and level >= levels[-1],
        })
    return rows, running
