"""スキルテスト(AIが作る4択問題で、メンバーのテクニカルスキルの到達度を確認する)のモデル。

すべて新しいテーブル(既存のテーブルは変更しない)。履歴は削除せずに残す。

  SkillTestQuestion : 問題プール(スキル・レベルごとの4択問題。AIが作成し、マネージャーが有効/無効を切り替える)
  SkillTestAttempt  : 受験1回分(状態・期限・採点結果・到達度の自動登録の結果・離脱回数・設定の控え)
  SkillTestAnswer   : 受験の1問分(出題した問題・選択肢の並びの控え・回答・所要時間・時間切れ・離脱回数)

回答には出題時点の問題文・選択肢(並べ替えた順)・正解の位置を控えとして保存する。
後から問題を無効にしたり内容が変わったりしても、受験履歴はそのまま読める。

日時はすべてこのモジュールの _now() から取る(app/skilltest/service.py も _now() 経由)。
動作確認では _now() を差し替えると、制限時間・期限・再受験の間隔などを時刻を固定して確かめられる。
"""
import json
from datetime import datetime

from app.extensions import db

# --- 受験の状態 ---
ATTEMPT_IN_PROGRESS = "in_progress"  # 受験中
ATTEMPT_FINISHED = "finished"        # 全問に回答して終了
ATTEMPT_EXPIRED = "expired"          # 制限時間(全体)を過ぎて自動で終了(未回答は時間切れ)

ATTEMPT_STATUS_LABELS = {
    ATTEMPT_IN_PROGRESS: "受験中",
    ATTEMPT_FINISHED: "終了",
    ATTEMPT_EXPIRED: "時間切れで終了",
}
ATTEMPT_STATUS_COLORS = {
    ATTEMPT_IN_PROGRESS: "primary",
    ATTEMPT_FINISHED: "success",
    ATTEMPT_EXPIRED: "warning",
}

# --- 問題の作成元 ---
SOURCE_AI = "ai"
SOURCE_LABELS = {SOURCE_AI: "AI"}

# 選択肢の表示記号(index 0〜3)
CHOICE_LETTERS = ["A", "B", "C", "D"]


def _now():
    """現在の日時。スキルテストの時刻はすべてここから取る(動作確認ではこの関数を差し替える)。"""
    return datetime.now()


def choice_letter(index):
    """選択肢の位置(0〜3)を表示用の記号(A〜D)にする。範囲外・None は空文字。"""
    if isinstance(index, int) and 0 <= index < len(CHOICE_LETTERS):
        return CHOICE_LETTERS[index]
    return ""


def _json_list(text):
    """JSON文字列(リスト)を読む。壊れていれば空のリスト。"""
    try:
        value = json.loads(text or "[]")
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


def _json_dict(text):
    """JSON文字列(辞書)を読む。壊れていれば空の辞書。"""
    try:
        value = json.loads(text or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


class SkillTestQuestion(db.Model):
    """問題プールの4択問題(スキル・レベルごと)。"""
    __tablename__ = "skill_test_questions"
    __table_args__ = (
        db.Index("ix_skill_test_questions_skill_level", "skill_id", "level"),
    )

    id = db.Column(db.Integer, primary_key=True)
    skill_id = db.Column(db.Integer, db.ForeignKey("skills.id"), nullable=False, index=True)
    level = db.Column(db.Integer, nullable=False)          # 想定する到達レベル(1〜4)
    question = db.Column(db.Text, nullable=False)          # 問題文
    choices = db.Column(db.Text, nullable=False)           # 選択肢4つ(JSONの配列。作成時の順)
    answer_index = db.Column(db.Integer, nullable=False)   # 正解の位置(choices の 0〜3)
    explanation = db.Column(db.Text)                       # 解説(マネージャーだけが見る)
    source = db.Column(db.String(16), nullable=False, default=SOURCE_AI)
    model = db.Column(db.String(64))                       # 作成したAIのモデル名
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=lambda: _now())

    skill = db.relationship("Skill")

    @property
    def choice_list(self):
        return _json_list(self.choices)

    @property
    def answer_letter(self):
        return choice_letter(self.answer_index)

    @property
    def source_label(self):
        return SOURCE_LABELS.get(self.source, self.source or "")

    def __repr__(self):
        return f"<SkillTestQuestion {self.id} skill={self.skill_id} lv={self.level}>"


class SkillTestAttempt(db.Model):
    """スキルテストの受験1回分。"""
    __tablename__ = "skill_test_attempts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    skill_id = db.Column(db.Integer, db.ForeignKey("skills.id"), nullable=False, index=True)
    status = db.Column(db.String(16), nullable=False, default=ATTEMPT_IN_PROGRESS, index=True)
    started_at = db.Column(db.DateTime, nullable=False, default=lambda: _now())
    finished_at = db.Column(db.DateTime)
    deadline_at = db.Column(db.DateTime, nullable=False)   # 全体の期限(各問の制限時間の合計＋余裕)
    total = db.Column(db.Integer, nullable=False, default=0)    # 問題数
    correct = db.Column(db.Integer, nullable=False, default=0)  # 正解数(終了時に確定)
    # レベルごとの結果(JSONの配列: level / total / correct / rate / rate_ok / passed)
    level_results = db.Column(db.Text)
    result_level = db.Column(db.Integer)                   # テストで認定したレベル(0〜)
    prev_level = db.Column(db.Integer)                     # 終了時点の到達度(登録前)
    new_level = db.Column(db.Integer)                      # 終了後の到達度(登録しなければ prev と同じ)
    applied = db.Column(db.Boolean, nullable=False, default=False)  # 到達度を自動登録したか
    blur_count = db.Column(db.Integer, nullable=False, default=0)   # 画面から離れた回数(タブ切替など)
    reused_count = db.Column(db.Integer, nullable=False, default=0)  # 受験済みの問題を再出題した数
    settings_snapshot = db.Column(db.Text)                 # 受験開始時の設定の控え(JSON)

    user = db.relationship("User")
    skill = db.relationship("Skill")
    answers = db.relationship(
        "SkillTestAnswer",
        back_populates="attempt",
        cascade="all, delete-orphan",
        order_by="SkillTestAnswer.seq",
    )

    @property
    def is_in_progress(self):
        return self.status == ATTEMPT_IN_PROGRESS

    @property
    def status_label(self):
        return ATTEMPT_STATUS_LABELS.get(self.status, self.status)

    @property
    def status_color(self):
        return ATTEMPT_STATUS_COLORS.get(self.status, "secondary")

    @property
    def level_result_list(self):
        return [r for r in _json_list(self.level_results) if isinstance(r, dict)]

    @property
    def settings_dict(self):
        return _json_dict(self.settings_snapshot)

    @property
    def rate(self):
        """正答率(%。小数1桁)。問題数0なら None。"""
        if not self.total:
            return None
        return round(self.correct * 100.0 / self.total, 1)

    @property
    def answered_count(self):
        return sum(1 for a in self.answers if a.answered_at is not None)

    def __repr__(self):
        return f"<SkillTestAttempt {self.id} user={self.user_id} skill={self.skill_id} {self.status}>"


class SkillTestAnswer(db.Model):
    """受験の1問分(出題時点の控えと回答)。"""
    __tablename__ = "skill_test_answers"
    __table_args__ = (
        db.UniqueConstraint("attempt_id", "seq", name="uq_skill_test_answer_seq"),
    )

    id = db.Column(db.Integer, primary_key=True)
    attempt_id = db.Column(
        db.Integer, db.ForeignKey("skill_test_attempts.id"), nullable=False, index=True
    )
    seq = db.Column(db.Integer, nullable=False)            # 出題順(1〜)
    level = db.Column(db.Integer, nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey("skill_test_questions.id"), index=True)
    question = db.Column(db.Text, nullable=False)          # 問題文の控え
    choices = db.Column(db.Text, nullable=False)           # 選択肢の控え(JSON。画面に出した順)
    correct_index = db.Column(db.Integer, nullable=False)  # 正解の位置の控え(画面に出した順)
    selected_index = db.Column(db.Integer)                 # 選んだ位置(未回答は None)
    is_correct = db.Column(db.Boolean, nullable=False, default=False)
    timed_out = db.Column(db.Boolean, nullable=False, default=False)
    time_limit_sec = db.Column(db.Integer, nullable=False)
    served_at = db.Column(db.DateTime)                     # 初めて画面に出した日時(未表示は None)
    answered_at = db.Column(db.DateTime)                   # 回答(または時間切れ)を確定した日時
    elapsed_sec = db.Column(db.Float)                      # 表示から回答までの秒数
    blur_count = db.Column(db.Integer, nullable=False, default=0)  # この問題の表示中に画面から離れた回数

    attempt = db.relationship("SkillTestAttempt", back_populates="answers")
    source_question = db.relationship("SkillTestQuestion")

    @property
    def choice_list(self):
        return _json_list(self.choices)

    @property
    def is_done(self):
        return self.answered_at is not None

    @property
    def correct_letter(self):
        return choice_letter(self.correct_index)

    @property
    def selected_letter(self):
        return choice_letter(self.selected_index)

    @property
    def result_label(self):
        """マネージャー向けの結果表示。"""
        if self.answered_at is None:
            return "未回答"
        if self.timed_out:
            return "時間切れ"
        return "正解" if self.is_correct else "不正解"

    def __repr__(self):
        return f"<SkillTestAnswer attempt={self.attempt_id} seq={self.seq}>"
