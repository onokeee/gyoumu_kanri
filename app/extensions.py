"""Flask拡張のインスタンスを生成する場所。

ここで生成して各所から import することで、循環参照を避ける。
アプリ本体への紐付け(init_app)は app/__init__.py で行う。
"""
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager

db = SQLAlchemy()
login_manager = LoginManager()

# 未ログイン時に飛ばすログイン画面のエンドポイント
login_manager.login_view = "auth.login"
login_manager.login_message = "ログインしてください。"
login_manager.login_message_category = "warning"
