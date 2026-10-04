"""モデルパッケージ。

ここで各モデルを import しておくことで、
db.create_all() 実行時に全テーブルが認識されるようにする。
新しい機能を追加する際は、
ここに import を追記すること。
"""
from app.models.user import User  # noqa: F401
from app.models.task import (  # noqa: F401
    Task,
    TaskComment,
    TaskStatusChange,
    task_assignees,
)
from app.models.leave import LeaveRequest  # noqa: F401
from app.models.routine import RoutineWork  # noqa: F401
from app.models.skill import Skill, SkillRating  # noqa: F401
from app.models.operation import Operation, OperationSkill  # noqa: F401
from app.models.department import Department, user_departments  # noqa: F401
from app.models.skilltest import (  # noqa: F401
    SkillTestQuestion,
    SkillTestAttempt,
    SkillTestAnswer,
)
