"""業務(Operation)モデルと、業務ごとの必要スキル(OperationSkill)。

スキルマップの縦軸=スキル項目に対し、横軸を『ヒト』だけでなく『業務』でも見られる。
業務に必要なスキルは OperationSkill で持ち、必要到達レベルは
ヒトのスキル到達度(SkillRating)と同じ到達尺度(scale_for)を使う。
"""
from datetime import datetime

from app.extensions import db


class OperationSkill(db.Model):
    """業務に必要なスキルと、その必要到達レベル。

    レベルはスキル区分ごとの到達尺度(ヒトのスキル管理と同じ)。
    レベル0(不要)はレコードを作らない(スパース)。
    """
    __tablename__ = "operation_skills"

    operation_id = db.Column(
        db.Integer, db.ForeignKey("operations.id"), primary_key=True
    )
    skill_id = db.Column(
        db.Integer, db.ForeignKey("skills.id"), primary_key=True
    )
    level = db.Column(db.Integer, nullable=False, default=0)

    operation = db.relationship("Operation", back_populates="skill_reqs")
    skill = db.relationship("Skill", back_populates="operation_reqs")

    def __repr__(self):
        return f"<OperationSkill op={self.operation_id} skill={self.skill_id} lv={self.level}>"


class Operation(db.Model):
    __tablename__ = "operations"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.Text)  # 業務内容の詳細(スキルマップのマウスオーバー表示)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

    # この業務に必要なスキル(必要レベル付き)。level>=1 のみ保持(スパース)。
    skill_reqs = db.relationship(
        "OperationSkill",
        back_populates="operation",
        cascade="all, delete-orphan",
    )

    def req_for(self, skill):
        """指定スキルの必要レベル・レコードを返す(未設定ならNone)。"""
        sid = skill.id if hasattr(skill, "id") else skill
        return next((r for r in self.skill_reqs if r.skill_id == sid), None)

    def required_level(self, skill):
        r = self.req_for(skill)
        return r.level if r else 0

    def __repr__(self):
        return f"<Operation {self.id}: {self.name}>"
