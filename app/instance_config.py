"""環境ごとの設定ファイル(instance/config.py)の自動作成。

環境によって変わる値(秘密鍵・管理者パスワード・LDAP/AI/メールの接続先など)は、
すべて instance/config.py の1か所にまとめる。instance/ はDB(app.db)と同じ
フォルダで Git管理外のため、パスワードやキーがリポジトリに入ることはない。

create_app() は起動のたびに ensure_instance_config() を呼ぶ。
  - instance/config.py が既にあれば何もしない(決して上書きしない)
  - 無ければ、リポジトリ直下の見本 config.example.py をもとに作成する
      ・SECRET_KEY     : ランダムな値(secrets.token_hex(32))
      ・ADMIN_PASSWORD : ランダムな値(secrets.token_urlsafe(12))。導入先ごとに異なる
      ・AI_API_URL / AI_API_KEY / AI_MODEL :
          旧「AI接続設定」画面で保存した値がDBに残っていれば、1回だけ引き継ぐ
          (DBは読み取り専用で開き、一切書き込まない。失敗したら引き継がない)

作成時はファイルの場所だけを1行表示する(パスワードやキーの値は表示しない)。
"""
import os
import pathlib
import re
import secrets
import sqlite3
from datetime import datetime

CONFIG_FILENAME = "config.py"

# 見本ファイル(リポジトリ直下。Git管理下で、実際の値は書かない)
TEMPLATE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.example.py"
)

# 見本ファイルが見つからない場合の最小限の内容
_FALLBACK_TEMPLATE = (
    "# 業務管理システム 環境ごとの設定ファイル\n"
    "# 項目の説明はリポジトリ直下の config.example.py を参照してください。\n"
    "# ここに書かれていない項目は app/config.py の既定値が使われます。\n"
)


def _read_old_ai_settings(db_path):
    """旧「AI接続設定」画面の値(ai_settings テーブル)を読み取り専用で取得する。

    DB・テーブル・行が無い場合や、読み取りに失敗した場合は空の辞書を返す。
    """
    if not os.path.isfile(db_path):
        return {}
    try:
        uri = pathlib.Path(db_path).resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        try:
            found = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ai_settings'"
            ).fetchone()
            if found is None:
                return {}
            row = conn.execute(
                "SELECT api_url, api_key, model FROM ai_settings ORDER BY id LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
    except Exception:
        return {}
    if row is None:
        return {}

    values = {}
    for key, value in zip(("AI_API_URL", "AI_API_KEY", "AI_MODEL"), row):
        value = (value or "").strip() if isinstance(value, str) else ""
        if value:
            values[key] = value
    return values


def _set_value(text, key, value):
    """設定ファイルの本文で `KEY = ...` の値を置き換える(無ければ末尾に追記)。

    値は repr() で書き出すので、引用符などを含んでも安全に記述できる。
    行末のコメントはそのまま残す。
    """
    pattern = re.compile(
        r"^({}\s*=\s*)(\"[^\"\n]*\"|'[^'\n]*')".format(re.escape(key)), re.MULTILINE
    )
    new_text, count = pattern.subn(lambda m: m.group(1) + repr(value), text, count=1)
    if count:
        return new_text
    if not new_text.endswith("\n"):
        new_text += "\n"
    return new_text + "{} = {}\n".format(key, repr(value))


def _build_content(db_path):
    """新しく作る instance/config.py の内容を組み立てる。"""
    try:
        with open(TEMPLATE_PATH, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        text = _FALLBACK_TEMPLATE

    values = {
        "SECRET_KEY": secrets.token_hex(32),
        "ADMIN_PASSWORD": secrets.token_urlsafe(12),
    }
    # 旧画面のAI接続設定を1回だけ引き継ぐ(空の項目は見本の値のまま)
    values.update(_read_old_ai_settings(db_path))

    for key, value in values.items():
        text = _set_value(text, key, value)

    header = "# 自動作成: {}(config.example.py をもとに作成)\n".format(
        datetime.now().strftime("%Y/%m/%d %H:%M")
    )
    return header + text


def _notice(message):
    """起動時のお知らせを1行表示する(表示できない環境でも起動は止めない)。"""
    try:
        print(message, flush=True)
    except Exception:
        pass


def ensure_instance_config(instance_path):
    """instance/config.py が無ければ作成する。作成した場合は True を返す。

    既にある場合は何もしない(内容の確認・上書きもしない)。
    作成に失敗した場合は1行表示して False を返す(app/config.py の既定値で起動を続ける)。
    """
    path = os.path.join(instance_path, CONFIG_FILENAME)
    if os.path.exists(path):
        return False

    content = _build_content(os.path.join(instance_path, "app.db"))
    try:
        # "x" = 新規作成専用。同時に別プロセスが作成していても上書きしない
        with open(path, "x", encoding="utf-8", newline="\n") as f:
            f.write(content)
    except FileExistsError:
        return False
    except OSError as exc:
        _notice("設定ファイルを作成できませんでした: {} ({})".format(path, exc))
        return False

    _notice("設定ファイルを作成しました（管理者パスワード等はこのファイルで確認・変更）: {}"
            .format(path))
    return True
