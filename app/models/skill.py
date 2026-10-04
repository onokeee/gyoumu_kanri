"""スキル管理(スキルマップ)モデル。

Katzの3区分(テクニカル/コンセプチュアル/ヒューマン)でメンバーの到達度を管理する。
到達度はマネージャーが設定・更新する(本人の自己評価は持たない)。
未評価(スパース)は SkillRating レコード未作成 = レベル0(未習得)として扱う。
"""
from datetime import datetime

from app.extensions import db

# --- スキル区分(Katzの3スキル) ---
SKILL_TECHNICAL = "テクニカル"
SKILL_CONCEPTUAL = "コンセプチュアル"
SKILL_HUMAN = "ヒューマン"
SKILL_TYPE_CHOICES = [SKILL_TECHNICAL, SKILL_CONCEPTUAL, SKILL_HUMAN]
SKILL_TYPE_LABELS = {
    SKILL_TECHNICAL: "テクニカルスキル",
    SKILL_CONCEPTUAL: "コンセプチュアルスキル",
    SKILL_HUMAN: "ヒューマンスキル",
}
SKILL_TYPE_COLORS = {
    SKILL_TECHNICAL: "primary",
    SKILL_CONCEPTUAL: "success",
    SKILL_HUMAN: "info",
}

# --- 到達尺度(区分ごと。リストの index = レベル値) ---
# テクニカルは6段階＋未習得(0〜6)。
# コンセプチュアル/ヒューマンは未習得＋5段階(0〜5)。
SKILL_SCALES = {
    SKILL_TECHNICAL: [
        "未習得",
        "簡単なものが作れる",
        "少し難しいものも作れる",
        "難しいものもつくれる",
        "大体何でも作れる",
        "指導できる",
        "勉強会を開催できる",
    ],
    SKILL_CONCEPTUAL: [
        "未習得",
        "指示があれば対応できる",
        "自分の担当範囲を把握して動ける",
        "業務全体を俯瞰し問題点を指摘できる",
        "課題を構造化し解決策を立案できる",
        "全体最適の視点で方針を示し牽引できる",
    ],
    SKILL_HUMAN: [
        "未習得",
        "挨拶・報連相が確実にできる",
        "周囲と協調して作業を進められる",
        "後輩の相談に乗り指導できる",
        "チームの合意形成や調整ができる",
        "他チーム・関係者を巻き込み人を動かせる",
    ],
}

# レベル別のバッジ色(0=未習得は淡色、上位ほど濃く)
SKILL_LEVEL_COLORS = {
    0: "light",
    1: "secondary",
    2: "info",
    3: "primary",
    4: "primary",
    5: "success",
    6: "success",
}

# 「単独で実務可能」とみなす到達度の下限(スキル保有状況の指標で使用)
SKILL_PROFICIENT_LEVEL = 2


def scale_for(skill_type):
    return SKILL_SCALES.get(skill_type, SKILL_SCALES[SKILL_TECHNICAL])


def level_label(skill_type, level):
    scale = scale_for(skill_type)
    return scale[level] if 0 <= level < len(scale) else str(level)


class Skill(db.Model):
    __tablename__ = "skills"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    skill_type = db.Column(
        db.String(16), nullable=False, default=SKILL_TECHNICAL, index=True
    )
    category = db.Column(db.String(64))  # テクニカル項目のグルーピング(任意)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    ratings = db.relationship(
        "SkillRating",
        back_populates="skill",
        cascade="all, delete-orphan",
        order_by="SkillRating.id",
    )
    # このスキルを必要とする業務の要件(必要レベル付き)。横軸「業務」ビューで使う
    operation_reqs = db.relationship(
        "OperationSkill",
        back_populates="skill",
        cascade="all, delete-orphan",
    )

    @property
    def type_label(self):
        return SKILL_TYPE_LABELS.get(self.skill_type, self.skill_type)

    @property
    def type_color(self):
        return SKILL_TYPE_COLORS.get(self.skill_type, "secondary")

    @property
    def max_level(self):
        return len(scale_for(self.skill_type)) - 1

    @property
    def level_labels(self):
        return scale_for(self.skill_type)

    def rating_for(self, user):
        """指定ユーザーの到達度レコードを返す(未評価ならNone)。"""
        if user is None:
            return None
        return next((r for r in self.ratings if r.user_id == user.id), None)

    def level_of(self, user):
        """指定ユーザーの到達度(未評価は0)。"""
        r = self.rating_for(user)
        return r.level if r else 0

    def holder_count(self, min_level=SKILL_PROFICIENT_LEVEL):
        """一定レベル以上を保有するメンバー数(スキル保有状況の指標)。"""
        return sum(1 for r in self.ratings if r.level >= min_level)

    def __repr__(self):
        return f"<Skill {self.id} {self.skill_type}:{self.name}>"


class SkillRating(db.Model):
    __tablename__ = "skill_ratings"
    __table_args__ = (
        db.UniqueConstraint("skill_id", "user_id", name="uq_skill_user"),
    )

    id = db.Column(db.Integer, primary_key=True)
    skill_id = db.Column(db.Integer, db.ForeignKey("skills.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    level = db.Column(db.Integer, nullable=False, default=0)
    note = db.Column(db.String(200))
    rated_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    rated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    created_at = db.Column(db.DateTime, default=datetime.now)

    skill = db.relationship("Skill", back_populates="ratings")
    user = db.relationship(
        "User", foreign_keys=[user_id], back_populates="skill_ratings"
    )
    rater = db.relationship("User", foreign_keys=[rated_by_id])

    @property
    def level_label(self):
        return level_label(self.skill.skill_type, self.level)

    @property
    def level_color(self):
        return SKILL_LEVEL_COLORS.get(self.level, "secondary")

    @property
    def is_unrated(self):
        return self.level == 0

    def __repr__(self):
        return f"<SkillRating skill={self.skill_id} user={self.user_id} lv={self.level}>"
