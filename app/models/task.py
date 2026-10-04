"""タスクモデル。

誰が・何を・いつまでに・どこまで進んでいるか を管理する。
1つのタスクを複数のメンバーに割り当てられる(担当者は多対多)。
やり取りはコメント(TaskComment)で行う。
"""
from datetime import datetime, date

from app.extensions import db

# ステータスの定義(順序は画面の並び順にも使う)
STATUS_TODO = "未着手"
STATUS_DOING = "進行中"
STATUS_HOLD = "保留"
STATUS_DONE = "完了"
STATUS_CHOICES = [STATUS_TODO, STATUS_DOING, STATUS_HOLD, STATUS_DONE]

# ステータスごとのBootstrapバッジ色(画面表示用)
STATUS_COLORS = {
    STATUS_TODO: "secondary",
    STATUS_DOING: "primary",
    STATUS_HOLD: "warning",
    STATUS_DONE: "success",
}

# 優先度の定義
PRIORITY_LOW = "低"
PRIORITY_MID = "中"
PRIORITY_HIGH = "高"
PRIORITY_CHOICES = [PRIORITY_HIGH, PRIORITY_MID, PRIORITY_LOW]

PRIORITY_COLORS = {
    PRIORITY_HIGH: "danger",
    PRIORITY_MID: "info",
    PRIORITY_LOW: "light",
}

# 成果(定量)の単位(見込み・実績で選択)。￥=金額 / ｈ=時間、年・月・日あたり。
OUTCOME_UNITS = ["￥/年", "￥/月", "￥/日", "ｈ/年", "ｈ/月", "ｈ/日"]


def _fmt_num(v):
    """float を入力/表示用の文字列に(整数は小数点なし・末尾ゼロ除去)。"""
    if v is None:
        return ""
    s = ("%.4f" % float(v)).rstrip("0").rstrip(".")
    return s or "0"


def _fmt_amount(v):
    """桁区切り付きの表示用文字列。"""
    if v is None:
        return ""
    s = _fmt_num(abs(v))
    ip, _dot, fp = s.partition(".")
    ip = "{:,}".format(int(ip)) if ip else "0"
    out = ip + ("." + fp if fp else "")
    return ("-" + out) if float(v) < 0 else out


# タスクの規模(=担当者が完了までに要する実働工数の目安。マネージャがスキル/キャパを
# 考慮して選ぶため、能力差は規模選択の時点で反映される)。負荷合算のため実働時間(h)に
# 対応づける(8h/日・40h/週・160h/月換算)。各要素 = (キー, 表示名, 工数h, 目安日数)。
TASK_SCALES = [
    ("1h",     "1時間", 1,    1),
    ("half_d", "半日",  4,    1),
    ("1d",     "1日",   8,    1),
    ("3d",     "3日",   24,   3),
    ("1w",     "1週",   40,   7),
    ("2w",     "2週",   80,   14),
    ("1m",     "1か月", 160,  30),
    ("3m",     "3か月", 480,  91),
    ("half_y", "半期",  960,  182),
    ("1y",     "1年",   1920, 365),
]
TASK_SCALE_KEYS = [s[0] for s in TASK_SCALES]
TASK_SCALE_LABELS = {s[0]: s[1] for s in TASK_SCALES}
TASK_SCALE_HOURS = {s[0]: s[2] for s in TASK_SCALES}
TASK_SCALE_DAYS = {s[0]: s[3] for s in TASK_SCALES}


# タスク ↔ 担当者(複数割り当て)の多対多
task_assignees = db.Table(
    "task_assignees",
    db.Column("task_id", db.Integer, db.ForeignKey("tasks.id"), primary_key=True),
    db.Column("user_id", db.Integer, db.ForeignKey("users.id"), primary_key=True),
)


class Task(db.Model):
    __tablename__ = "tasks"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(16), nullable=False, default=STATUS_TODO, index=True)
    priority = db.Column(db.String(8), nullable=False, default=PRIORITY_MID)
    start_date = db.Column(db.Date)      # 開始日(ガントチャートの開始)
    due_date = db.Column(db.Date)        # 期限(ガントチャートの終了)
    scale = db.Column(db.String(16))     # 規模(TASK_SCALE_KEYS)。実働工数の目安=負荷

    # 成果(定量): 見込み・実績(値＋単位)＋補足
    outcome_quant_estimate = db.Column(db.Float)          # 見込み(値)
    outcome_quant_estimate_unit = db.Column(db.String(8))  # 見込み(単位)
    outcome_quant_actual = db.Column(db.Float)            # 実績(値)
    outcome_quant_actual_unit = db.Column(db.String(8))   # 実績(単位)
    outcome_quant_note = db.Column(db.Text)                # 補足
    # 成果(定性): 見込み・実績
    outcome_qual_estimate = db.Column(db.Text)            # 見込み
    outcome_qual_actual = db.Column(db.Text)              # 実績

    creator_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    creator = db.relationship(
        "User", foreign_keys=[creator_id], back_populates="created_tasks"
    )
    # 担当者(複数)。User.assigned_tasks と多対多で対応
    assignees = db.relationship(
        "User",
        secondary=task_assignees,
        back_populates="assigned_tasks",
        order_by="User.display_name",
    )
    comments = db.relationship(
        "TaskComment",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskComment.created_at",
    )
    status_changes = db.relationship(
        "TaskStatusChange",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskStatusChange.changed_at",
    )

    @property
    def status_color(self):
        return STATUS_COLORS.get(self.status, "secondary")

    @property
    def priority_color(self):
        return PRIORITY_COLORS.get(self.priority, "secondary")

    @property
    def is_done(self):
        return self.status == STATUS_DONE

    @property
    def is_overdue(self):
        """期限切れ(未完了かつ期限が過去)かどうか。"""
        if self.due_date and not self.is_done:
            return self.due_date < date.today()
        return False

    @property
    def assignee_names(self):
        """担当者名(複数は「、」区切り)。未割当は空文字。"""
        return "、".join(u.display_name for u in self.assignees)

    def is_assigned_to(self, user):
        return user is not None and any(u.id == user.id for u in self.assignees)

    # --- 規模(負荷)関連 ---
    @property
    def scale_label(self):
        return TASK_SCALE_LABELS.get(self.scale)

    @property
    def scale_hours(self):
        """規模に対応する実働工数(h)。未設定は0。"""
        return TASK_SCALE_HOURS.get(self.scale, 0)

    @property
    def scale_monthly_hours(self):
        """規模(実働工数)を期間で月換算した、月あたりの目安工数(h)。

        タスクは一過性のため、開始〜期限の期間で月あたりに配分する。
        1か月未満の期間は当月に全量計上(effort / max(月数, 1))。
        期間が未設定なら規模の目安日数で代用する。
        """
        h = self.scale_hours
        if not h:
            return 0.0
        if self.start_date and self.due_date and self.due_date >= self.start_date:
            days = (self.due_date - self.start_date).days + 1
        else:
            days = TASK_SCALE_DAYS.get(self.scale, 30)
        months = max(days / 30.0, 1.0)
        return h / months

    # --- 成果(定量)の表示・入力用ヘルパ ---
    @property
    def outcome_quant_estimate_input(self):
        return _fmt_num(self.outcome_quant_estimate)

    @property
    def outcome_quant_actual_input(self):
        return _fmt_num(self.outcome_quant_actual)

    @property
    def outcome_quant_estimate_label(self):
        if self.outcome_quant_estimate is None:
            return None
        return "{} {}".format(
            _fmt_amount(self.outcome_quant_estimate),
            self.outcome_quant_estimate_unit or "",
        ).strip()

    @property
    def outcome_quant_actual_label(self):
        if self.outcome_quant_actual is None:
            return None
        return "{} {}".format(
            _fmt_amount(self.outcome_quant_actual),
            self.outcome_quant_actual_unit or "",
        ).strip()

    @property
    def has_outcome_actual(self):
        """完了に必要な『成果(実績)』が定量・定性いずれかで入力済みか。"""
        return (
            self.outcome_quant_actual is not None
            or bool((self.outcome_qual_actual or "").strip())
        )

    def __repr__(self):
        return f"<Task {self.id}: {self.title}>"


class TaskStatusChange(db.Model):
    """タスクのステータス変更履歴。ガントの棒を日付で色分けするために使う。"""

    __tablename__ = "task_status_changes"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("tasks.id"), nullable=False, index=True)
    status = db.Column(db.String(16), nullable=False)
    changed_at = db.Column(db.DateTime, default=datetime.now)

    task = db.relationship("Task", back_populates="status_changes")

    def __repr__(self):
        return f"<TaskStatusChange task={self.task_id} {self.status} @{self.changed_at}>"


class TaskComment(db.Model):
    """タスクへのコメント(やり取り)。ログインユーザーは誰でも投稿できる。"""

    __tablename__ = "task_comments"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("tasks.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)

    task = db.relationship("Task", back_populates="comments")
    user = db.relationship("User")

    def __repr__(self):
        return f"<TaskComment {self.id} task={self.task_id}>"
