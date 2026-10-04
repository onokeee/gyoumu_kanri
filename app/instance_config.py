"""環境ごとの設定ファイル(instance/config.py)の自動作成・読み込み・画面からの更新。

環境によって変わる値(秘密鍵・管理者パスワード・LDAP/AI/メールの接続先など)は、
すべて instance/config.py の1か所にまとめる。instance/ はDB(app.db)と同じ
フォルダで Git管理外のため、パスワードやキーがリポジトリに入ることはない。

■ 自動作成(ensure_instance_config)
create_app() は起動のたびに ensure_instance_config() を呼ぶ。
  - instance/config.py が既にあれば何もしない(決して上書きしない)
  - 無ければ、リポジトリ直下の見本 config.example.py をもとに作成する
      ・SECRET_KEY     : ランダムな値(secrets.token_hex(32))
      ・ADMIN_PASSWORD : ランダムな値(secrets.token_urlsafe(12))。導入先ごとに異なる
      ・AI_API_URL / AI_API_KEY / AI_MODEL :
          旧「AI接続設定」画面で保存した値がDBに残っていれば、1回だけ引き継ぐ
          (DBは読み取り専用で開き、一切書き込まない。失敗したら引き継がない)
作成時はファイルの場所だけを1行表示する(パスワードやキーの値は表示しない)。

■ 読み込み(read_config)
ファイルを Flask の from_pyfile と同じ方法で評価し、大文字の名前の値を返す。

■ 画面からの更新(update_config。システム設定の「基本設定」タブで使う)
  1. 変更する項目の `KEY = ...` の値の部分だけを置き換える(無い項目は末尾に追記)。
     コメント・知らない項目・書式(改行コードを含む)はそのまま残す
  2. 先頭付近の「# 最終更新: ...」の行を1行だけ更新する(無ければ追加)
  3. 新しい内容が Python として正しく、期待どおりの値になることを確かめる
     (変更しない項目の値が変わっていないことも確かめる)
  4. 元のファイルを instance/config.py.bak にコピーしてから、
     一時ファイルに書いて置き換える(os.replace。書き込み途中で壊れたファイルを残さない)
  同時に保存されても壊れないよう、モジュール共通のロックで直列化する。
  エラーメッセージには設定値(パスワード・キーなど)を含めない。
"""
import ast
import codecs
import os
import pathlib
import re
import secrets
import shutil
import sqlite3
import tempfile
import threading
import types
from datetime import datetime

CONFIG_FILENAME = "config.py"
BACKUP_SUFFIX = ".bak"

# 画面から更新したときに書く見出しコメント(1行だけ。毎回置き換える)
HEADER_PREFIX = "# 最終更新:"

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

# 読み込み・更新を直列化するロック(画面からの保存が同時に行われても壊れないように)
lock = threading.RLock()

_UTF8_BOM = "﻿"
# Python の構文で行の区切りになる改行(\r\n / \r / \n)。ast の行番号と同じ数え方で分ける
_LINE_RE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+$")
_CODING_RE = re.compile(r"^[ \t\f]*#.*?coding[:=]")
# 文字コードの指定(PEP 263。1〜2行目のコメント)
_CODING_DECL_RE = re.compile(r"^[ \t\f]*#.*?coding[:=][ \t]*([-\w.]+)")


class ConfigFileError(Exception):
    """instance/config.py を読み込めない・安全に更新できない(メッセージに設定値は含めない)。"""


class ConfigConflictError(ConfigFileError):
    """画面を開いた後に、ほかの保存や直接の編集で instance/config.py が変わっていた。"""


# --------------------------------------------------------------------------- #
# 値の書き方と、`KEY = ...` の置き換え
# --------------------------------------------------------------------------- #
def format_value(value):
    """設定ファイルに書く値の表記(文字列は repr()、一覧はリスト表記)。

    文字列は repr() で書き出すので、引用符や改行などを含んでも安全に記述できる。
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(format_value(item) for item in value) + "]"
    raise TypeError("設定ファイルに書けない種類の値です: {}".format(type(value).__name__))


def _split_lines(text):
    """行に分ける(行末の改行を含む)。ast の行番号と同じ区切り方。"""
    return _LINE_RE.findall(text)


def _binds(node, key):
    """文 node の中で key に代入しているか(入れ子の文も含む)。"""
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id == key and isinstance(child.ctx, ast.Store):
            return True
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                and child.name == key:
            return True
        if isinstance(child, (ast.Import, ast.ImportFrom)):
            for alias in child.names:
                if (alias.asname or alias.name.split(".")[0]) == key:
                    return True
    return False


def _value_node(tree, key):
    """最後に key を決めているトップレベルの文が単純な `KEY = 値` なら、その値の式を返す。

    `KEY = 値`(注釈付きを含む)以外の形(条件付き・複数代入・+= など)で最後に決まる場合や、
    どこでも代入していない場合は None(呼び出し側は末尾に追記する)。
    """
    found = None
    for stmt in tree.body:
        if not _binds(stmt, key):
            continue
        found = None
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 \
                and isinstance(stmt.targets[0], ast.Name) and stmt.targets[0].id == key:
            found = stmt.value
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) \
                and stmt.target.id == key and stmt.value is not None:
            found = stmt.value
    return found


def _char_index(lines, starts, lineno, col_offset):
    """ast の (行番号, UTF-8 のバイト位置) を、本文の文字位置に変換する。"""
    line = lines[lineno - 1]
    prefix = line.encode("utf-8")[:col_offset].decode("utf-8", "ignore")
    return starts[lineno - 1] + len(prefix)


def _newline_of(text):
    """ファイルで使われている改行コード(既定は \\n)。"""
    match = re.search(r"\r\n|\r|\n", text)
    return match.group(0) if match else "\n"


def _set_value(text, key, value, newline=None):
    """設定ファイルの本文で `KEY = ...` の値の部分を置き換える(無ければ末尾に追記)。

    値は format_value() で書き出す(文字列は repr()、一覧はリスト表記)。
    行末のコメントや前後の行、ほかの項目はそのまま残す。
    本文が Python として解釈できない場合や、単純な `KEY = 値` で決まっていない場合は
    末尾に `KEY = 値` を追記する(後の代入が優先されるため)。
    """
    newline = newline or _newline_of(text)
    literal = format_value(value)
    try:
        node = _value_node(ast.parse(text), key)
    except SyntaxError:
        node = None
    if node is not None:
        lines = _split_lines(text)
        starts, position = [], 0
        for line in lines:
            starts.append(position)
            position += len(line)
        begin = _char_index(lines, starts, node.lineno, node.col_offset)
        end = _char_index(lines, starts, node.end_lineno, node.end_col_offset)
        return text[:begin] + literal + text[end:]

    if text and not text.endswith(("\n", "\r")):
        text += newline
    return text + "{} = {}{}".format(key, literal, newline)


def _refresh_header(text, line, newline):
    """「# 最終更新: ...」の行を置き換える(無ければ先頭に追加。文字コード指定の行の後ろ)。"""
    lines = _split_lines(text)
    for index, current in enumerate(lines):
        if current.startswith(HEADER_PREFIX):
            ending = current[len(current.rstrip("\r\n")):] or newline
            lines[index] = line + ending
            return "".join(lines)
    insert_at = 0
    while insert_at < min(2, len(lines)) and (
            lines[insert_at].startswith("#!") or _CODING_RE.match(lines[insert_at])):
        insert_at += 1
    lines.insert(insert_at, line + newline)
    return "".join(lines)


def _clean_label(text):
    """見出しコメントに入れる文字列(文字・数字と . _ @ - だけ。ほかは _ にする)。

    「:」「=」を残さないので、コメントが文字コードの指定(# coding: ...)と解釈されることはない。
    """
    text = re.sub(r"[\x00-\x1f\x7f]", "", str(text or "")).strip()
    return re.sub(r"[^\w.@\-]", "_", text)[:64] or "不明"


def _declared_encoding(text):
    """1〜2行目の文字コードの指定(# coding: ...)。無ければ None。"""
    for line in _split_lines(text)[:2]:
        match = _CODING_DECL_RE.match(line)
        if match:
            return match.group(1)
    return None


# --------------------------------------------------------------------------- #
# 読み込み
# --------------------------------------------------------------------------- #
def config_path(instance_path):
    return os.path.join(instance_path, CONFIG_FILENAME)


def file_version(path):
    """ファイルの版(更新日時とサイズ)。内容から作らないので、設定値の推測には使えない。"""
    try:
        stat = os.stat(path)
    except OSError:
        return "none"
    return "{}-{}".format(stat.st_mtime_ns, stat.st_size)


def evaluate(text, filename):
    """設定ファイルを Flask の from_pyfile と同じ方法で評価し、大文字の名前の値を返す。

    text はファイルの内容(bytes。from_pyfile と同じく文字コードの指定に従って読む)または本文(str)。
    """
    module = types.ModuleType("config")
    module.__file__ = filename
    exec(compile(text, filename, "exec"), module.__dict__)  # noqa: S102 (設定ファイル自体の評価)
    return {name: value for name, value in vars(module).items() if name.isupper()}


def read_config(instance_path):
    """instance/config.py を読み込む。

    戻り値: {"path", "exists", "text", "values", "version", "bom"}
    ファイルが無ければ exists=False・values={}。読めない・評価できない場合は ConfigFileError。
    """
    path = config_path(instance_path)
    version = file_version(path)
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except FileNotFoundError:
        return {"path": path, "exists": False, "text": "", "values": {},
                "version": version, "bom": False}
    except OSError as exc:
        raise ConfigFileError("instance/{} を開けません（{}）。".format(
            CONFIG_FILENAME, exc.__class__.__name__)) from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigFileError("instance/{} を UTF-8 として読み込めません。".format(
            CONFIG_FILENAME)) from exc
    bom = text.startswith(_UTF8_BOM)
    if bom:
        text = text[len(_UTF8_BOM):]
    try:
        values = evaluate(raw, path)  # 起動時(from_pyfile)と同じく、ファイルの内容(bytes)を評価する
    except SyntaxError as exc:
        raise ConfigFileError("instance/{} の {} 行目に書式の誤りがあります。".format(
            CONFIG_FILENAME, exc.lineno)) from exc
    except Exception as exc:
        raise ConfigFileError("instance/{} を評価できません（{}）。".format(
            CONFIG_FILENAME, exc.__class__.__name__)) from exc
    return {"path": path, "exists": True, "text": text, "values": values,
            "version": version, "bom": bom}


def _is_utf8(name):
    try:
        return codecs.lookup(name).name == "utf-8"
    except LookupError:
        return False


def same_value(a, b):
    """設定値が同じか(True と 1 のように型が違うものは別扱い。一覧は要素ごとに比べる)。"""
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(same_value(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


_PLAIN_TYPES = (type(None), bool, int, float, str, list, tuple, dict)


# --------------------------------------------------------------------------- #
# 画面からの更新
# --------------------------------------------------------------------------- #
def _write_atomic(path, data):
    """一時ファイルに書いてから置き換える(書き込み途中で壊れたファイルを残さない)。"""
    folder = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(prefix=".config_", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def update_config(instance_path, changes, username, expected_version=None, now=None):
    """instance/config.py の項目を書き換える(changes = {KEY: 新しい値})。

    expected_version を渡すと、ファイルの版がそれと違う場合は ConfigConflictError
    (画面を開いた後に別の保存・直接の編集があった)。
    戻り値: 書き換え後のファイルの値(大文字の名前の辞書)。
    失敗した場合は ConfigFileError(ファイルは変更しない)。
    """
    with lock:
        current = read_config(instance_path)
        path = current["path"]
        if expected_version is not None and current["version"] != expected_version:
            raise ConfigConflictError(
                "画面を開いた後に instance/{} が更新されています。".format(CONFIG_FILENAME))

        text = current["text"]
        declared = _declared_encoding(text)
        if declared is not None and not _is_utf8(declared):
            raise ConfigFileError(
                "instance/{} の文字コードの指定（coding）が UTF-8 ではないため、画面から更新できません。"
                "ファイルは変更していません。ファイルを直接編集してください。".format(CONFIG_FILENAME))
        newline = _newline_of(text)
        for key, value in changes.items():
            text = _set_value(text, key, value, newline)
        stamp = (now or datetime.now()).strftime("%Y-%m-%d %H:%M")
        text = _refresh_header(
            text, "{} {}（画面から変更: {}）".format(HEADER_PREFIX, stamp, _clean_label(username)),
            newline)

        data = text.encode("utf-8")
        if current["bom"]:
            data = _UTF8_BOM.encode("utf-8") + data

        # 新しい内容が正しく、期待どおりの値になることを確かめてから置き換える
        # (書き込むバイト列そのものを、起動時の from_pyfile と同じ方法で評価する)
        try:
            ast.parse(data)
            values = evaluate(data, path)
        except Exception as exc:
            raise ConfigFileError("更新後の instance/{} を確認できませんでした（{}）。"
                                  "ファイルは変更していません。".format(
                                      CONFIG_FILENAME, exc.__class__.__name__)) from exc
        wrong = [key for key, value in changes.items()
                 if key not in values or not same_value(values[key], value)]
        for key, old in current["values"].items():
            if key in changes or not isinstance(old, _PLAIN_TYPES):
                continue
            if key not in values or not same_value(values[key], old):
                wrong.append(key)
        if wrong:
            raise ConfigFileError(
                "instance/{} の書き方のため、画面から安全に更新できませんでした（{}）。"
                "ファイルは変更していません。ファイルを直接編集してください。".format(
                    CONFIG_FILENAME, "、".join(sorted(set(wrong)))))

        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if current["exists"]:
                shutil.copy2(path, path + BACKUP_SUFFIX)
            _write_atomic(path, data)
        except OSError as exc:
            raise ConfigFileError("instance/{} を保存できませんでした（{}）。".format(
                CONFIG_FILENAME, exc.__class__.__name__)) from exc
        return values


# --------------------------------------------------------------------------- #
# 自動作成
# --------------------------------------------------------------------------- #
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
    path = config_path(instance_path)
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
