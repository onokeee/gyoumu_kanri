"""基本設定(instance/config.py)の入力チェック・保存・画面表示用の値。

項目の定義は config_fields.py(1か所)にあり、ここではそれに従って処理する。

保存の流れ(save):
  1. instance/config.py を読み、画面を開いたときから変わっていないか確かめる(版の比較)
  2. すべての項目を検証する。誤りが1つでもあれば何も書かない(入力は画面に残す。秘密の値は除く)
  3. 値が変わった項目だけを instance/config.py に書く(app/instance_config.py の update_config。
     元のファイルは instance/config.py.bak に残す)
  4. 再起動が不要な項目は、実行中のアプリの設定(current_app.config)にもすぐ反映する。
     SECRET_KEY / SERVER_HOST / SERVER_PORT はファイルにだけ書き、再起動後に反映される

秘密の値(SECRET_KEY / ADMIN_PASSWORD / AI_API_KEY / MAIL_PASSWORD)は、画面・ログ・
メッセージのどこにも出さない(画面には「設定あり／未設定」だけを表示する)。
"""
import re
import secrets
from collections import namedtuple
from email.utils import parseaddr
from urllib.parse import urlsplit

from app import ai_client, instance_config, mailer
from app.config import Config
from app.instance_config import ConfigConflictError, ConfigFileError, same_value
from app.system.config_fields import (
    FIELD_MAP,
    FIELDS,
    GROUPS,
    SECRET_KEYS,
    TYPE_ADDRESS,
    TYPE_ADDRESSES,
    TYPE_BOOL,
    TYPE_INT,
    TYPE_SECRET,
    TYPE_SECRET_KEY,
    TYPE_TEXT,
    TYPE_URL,
    documented_keys,
)

TEXT_MAX = 500           # 1行の文字列・URLの最大文字数
SECRET_MAX = 500         # パスワード・キーの最大文字数
ADDRESS_MAX_COUNT = 100  # アドレスの一覧の最大件数

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_ADDR = r"[^\s@<>()\[\],;:\"\\]+@[^\s@<>()\[\],;:\"\\.][^\s@<>()\[\],;:\"\\]*"
# 「name@example.com」または「表示名 <name@example.com>」(表示名に , ; " < > は使えない。
# アドレスの部分は半角英数字・記号だけ。表示名は送信時に app/mailer.py が符号化する)
_ADDRESS_RE = re.compile(r"[^<>,;\"\x00-\x1f\x7f]*<{0}>|{0}".format(_ADDR))
_ADDRESS_SPLIT = re.compile(r"[\r\n,;]+")
# 「その他」の項目で値を表示しない(秘密の値の可能性がある)キー
_SECRET_LIKE = re.compile(r"KEY|PASS|SECRET|TOKEN|CREDENTIAL", re.IGNORECASE)

# 保存の結果
STATUS_OK = "ok"
STATUS_UNCHANGED = "unchanged"
STATUS_INVALID = "invalid"
STATUS_CONFLICT = "conflict"
STATUS_ERROR = "error"

# changed         : ファイルで値を変えた項目
# restart_changed : そのうち再起動後に反映される項目
# applied         : 実行中のアプリに反映した(値が変わった)項目
SaveResult = namedtuple("SaveResult", "status errors state changed restart_changed applied message")

MSG_CONFLICT = ("画面を開いた後に、設定ファイル（instance/config.py）が更新されています"
                "（ほかの人の保存・直接の編集）。最新の内容を表示しましたので、もう一度変更してください。")


# --------------------------------------------------------------------------- #
# 既定値・現在の値
# --------------------------------------------------------------------------- #
def defaults(app):
    """app/config.py の既定値(create_app で控えたもの。無ければ Config クラス)。"""
    stored = app.extensions.get("config_defaults")
    if stored is not None:
        return stored
    return {name: getattr(Config, name) for name in dir(Config) if name.isupper()}


def effective(app, file_values):
    """各項目の値(ファイルに書かれていればその値、無ければ既定値)。"""
    base = defaults(app)
    return {f.key: file_values[f.key] if f.key in file_values else base.get(f.key)
            for f in FIELDS}


def running_value(app, key):
    """実行中のアプリの値。SECRET_KEY が起動時の一時的な鍵なら空として扱う。"""
    if key == "SECRET_KEY" and app.extensions.get("secret_key_temporary"):
        return ""
    return app.config.get(key)


def _differs(field, file_value, run_value):
    if field.type in (TYPE_SECRET, TYPE_SECRET_KEY):
        return str(file_value or "") != str(run_value or "")
    return not same_value(file_value, run_value)


def pending_fields(app, file_values):
    """ファイルの値と実行中の値が違う項目(再起動すると反映される)。"""
    values = effective(app, file_values)
    return [f for f in FIELDS if _differs(f, values[f.key], running_value(app, f.key))]


def mask_secrets(app, text):
    """メッセージに秘密の値(パスワード・キー)が含まれていたら伏せ字にする。"""
    text = str(text or "")
    for key in SECRET_KEYS:
        value = app.config.get(key)
        if isinstance(value, str) and len(value) >= 4 and value in text:
            text = text.replace(value, "***")
    return text


# --------------------------------------------------------------------------- #
# 入力チェック
# --------------------------------------------------------------------------- #
def _valid_address(text):
    """メールアドレス1件の簡単な形式チェック(local@domain、または 表示名 <local@domain>)。"""
    if not text or len(text) > 254 or _CONTROL.search(text):
        return False
    if not _ADDRESS_RE.fullmatch(text):
        return False
    addr = text[text.rfind("<") + 1:-1] if text.endswith(">") else text
    if not addr.isascii():
        return False
    # 送信時(app/mailer.py・smtplib)の解釈と同じアドレスになること(表示名の書き方によっては別の
    # アドレスと解釈されるため)
    if parseaddr(text)[1] != addr:
        return False
    domain = addr.rpartition("@")[2]
    return ".." not in domain and not domain.endswith(".")


def _parse_text(field, raw):
    value = raw.strip()
    if _CONTROL.search(value):
        return None, "改行・制御文字は使えません。"
    if len(value) > TEXT_MAX:
        return None, "{}文字以内で入力してください。".format(TEXT_MAX)
    if field.pattern and value and not re.fullmatch(field.pattern, value):
        return None, field.pattern_help or "形式が正しくありません。"
    return value, None


def _parse_url(field, raw):
    value = raw.strip()
    if not value:
        return "", None
    if _CONTROL.search(value) or any(ch.isspace() for ch in value):
        return None, "空白・改行を含まないURLを入力してください。"
    if len(value) > TEXT_MAX:
        return None, "{}文字以内で入力してください。".format(TEXT_MAX)
    try:
        parts = urlsplit(value)
        valid = parts.scheme.lower() in ("http", "https") and bool(parts.hostname)
        parts.port  # ポート番号が不正なら ValueError
    except ValueError:
        valid = False
    if not valid:
        return None, "http:// または https:// で始まるURLを入力してください。"
    if field.no_query and (parts.query or parts.fragment):
        return None, "「?」「#」以降を付けずに入力してください。"
    return value, None


def _parse_int(field, raw):
    value = raw.strip()
    message = "{}〜{}の整数で入力してください。".format(field.min, field.max)
    if not (value.isascii() and value.isdigit()) or len(value) > 9:
        return None, message
    number = int(value)
    if not field.min <= number <= field.max:
        return None, message
    return number, None


def _parse_address(field, raw):
    value = raw.strip()
    if not value:
        return "", None
    if not _valid_address(value):
        return None, "メールアドレスの形式が正しくありません（例: name@example.com）。"
    return value, None


def _parse_addresses(field, raw):
    items = [item.strip() for item in _ADDRESS_SPLIT.split(raw or "")]
    items = [item for item in items if item]
    bad = [item for item in items if not _valid_address(item)]
    if bad:
        return None, "メールアドレスの形式が正しくありません: {}".format(
            "、".join(item[:80] for item in bad[:3]))
    if len(items) > ADDRESS_MAX_COUNT:
        return None, "アドレスは{}件までにしてください。".format(ADDRESS_MAX_COUNT)
    return list(dict.fromkeys(items)), None


_PARSERS = {
    TYPE_TEXT: _parse_text,
    TYPE_URL: _parse_url,
    TYPE_INT: _parse_int,
    TYPE_ADDRESS: _parse_address,
    TYPE_ADDRESSES: _parse_addresses,
}


def _parse_secret(field, form, current_value):
    """秘密の値。空欄なら変更しない、「空にする」なら空、入力があればその値。"""
    raw = form.get(field.key, "")
    confirm = form.get(field.key + "_confirm", "") if field.confirm else ""
    clear = form.get("clear_" + field.key) == "1"
    if clear:
        if raw or confirm:
            return None, "新しい値の入力と「空にする」は同時に指定できません。", clear
        return "", None, clear
    if not raw:
        if confirm:
            return None, "新しいパスワードを両方の欄に入力してください。", clear
        return current_value, None, clear  # 変更しない
    if _CONTROL.search(raw):
        return None, "改行・制御文字は使えません。", clear
    if len(raw) > SECRET_MAX:
        return None, "{}文字以内で入力してください。".format(SECRET_MAX), clear
    if field.min_length and len(raw) < field.min_length:
        return None, "{}文字以上で入力してください。".format(field.min_length), clear
    if field.confirm and raw != confirm:
        return None, "確認のための入力が一致しません。", clear
    return raw, None, clear


def _destination(key, value):
    """秘密の値を送る接続先としての値(同じ接続先なら同じ値。AI_API_URL はスキーム・ホスト・ポート)。"""
    if key == "AI_API_URL":
        url = str(value or "").strip() or ai_client.DEFAULT_API_URL
        try:
            parts = urlsplit(url)
            port = parts.port or {"http": 80, "https": 443}.get(parts.scheme.lower())
            return parts.scheme.lower(), (parts.hostname or "").lower(), port
        except ValueError:
            return url
    if key == "MAIL_SMTP_PORT":
        try:
            return int(value or 25)
        except (TypeError, ValueError):
            return value
    if key == "MAIL_SMTP_SERVER":
        return str(value or "").strip().lower()
    return str(value or "").strip()


def _check_secret_destinations(form, current, values, errors):
    """接続先を変えるのに、保存済みの秘密の値をそのまま使おうとしていないか。

    画面に表示しない値(APIキー・パスワード)が、新しい接続先へ送られないようにする。
    """
    for field in FIELDS:
        if not field.bound_to or field.key in errors:
            continue
        kept = not form.get(field.key, "") and form.get("clear_" + field.key) != "1"
        if not kept or not _is_set(current.get(field.key)):
            continue
        moved = [FIELD_MAP[key] for key in field.bound_to
                 if key in values and _destination(key, values[key]) != _destination(key, current.get(key))]
        if moved:
            errors[field.key] = (
                "{}を変更するときは、{}を入力し直すか「空にする」を指定してください"
                "（保存済みの値は新しい接続先には使いません）。".format(
                    "・".join(f.label for f in moved), field.label))
            values.pop(field.key, None)


def parse(form, current):
    """フォームの入力を検証する。

    current : 今の値(ファイルの値。無ければ既定値)。秘密の値を変更しないときや、
              フォームに項目が無いときに使う
    戻り値: (values, errors, state)
      values : 全項目の保存後の値 {KEY: 値}
      errors : 誤りのある項目 {KEY: メッセージ}
      state  : 再表示用の入力(秘密の値は含めない)
    """
    values, errors, state = {}, {}, {}
    for field in FIELDS:
        key = field.key
        if field.type == TYPE_SECRET_KEY:
            generate = form.get("generate_" + key) == "1"
            state["generate_" + key] = generate
            values[key] = secrets.token_hex(32) if generate else current.get(key)
            continue
        if field.type == TYPE_SECRET:
            value, error, clear = _parse_secret(field, form, current.get(key))
            state["clear_" + key] = clear
        elif field.type == TYPE_BOOL:
            # チェックボックスの前に hidden の "0" を置いている(項目が無い = 変更しない)
            posted = form.getlist(key)
            value, error = ("1" in posted) if posted else current.get(key), None
            state[key] = bool(value)
        elif key not in form:
            value, error = current.get(key), None
            state[key] = _display(field, value)
        else:
            raw = form.get(key, "")
            state[key] = raw
            value, error = _PARSERS[field.type](field, raw)
        if error:
            errors[key] = error
        else:
            values[key] = value
    _check_secret_destinations(form, current, values, errors)
    return values, errors, state


# --------------------------------------------------------------------------- #
# 保存
# --------------------------------------------------------------------------- #
def _apply_live(app, file_values):
    """再起動が不要な項目に、ファイルの値を実行中のアプリの設定へ反映する。値が変わった項目を返す。"""
    final = effective(app, file_values)
    applied = []
    for field in FIELDS:
        if field.restart_required:
            continue
        if not same_value(app.config.get(field.key), final[field.key]):
            applied.append(field.key)
        app.config[field.key] = final[field.key]
    return applied


def save(app, form, username):
    """基本設定を保存する。戻り値: SaveResult(メッセージに秘密の値は含めない)。

    保存後(変更が無かった場合も)、再起動が不要な項目はファイルの値を実行中のアプリに反映する
    (ファイルを直接編集した値も、ここで保存すると反映される)。
    """
    def result(status, errors=None, state=None, changed=(), restart_changed=(), applied=(),
               message=""):
        return SaveResult(status, errors or {}, state, list(changed), list(restart_changed),
                          list(applied), message)

    with instance_config.lock:
        try:
            info = instance_config.read_config(app.instance_path)
        except ConfigFileError as exc:
            return result(STATUS_ERROR, message=str(exc))
        if form.get("version", "") != info["version"]:
            return result(STATUS_CONFLICT, message=MSG_CONFLICT)

        current = effective(app, info["values"])
        values, errors, state = parse(form, current)
        if errors:
            return result(STATUS_INVALID, errors=errors, state=state)

        changes = {f.key: values[f.key] for f in FIELDS
                   if not same_value(values[f.key], current.get(f.key))}
        if not changes:
            applied = _apply_live(app, info["values"])
            if applied:
                app.logger.info("システム設定（基本設定）: ファイルの値を実行中の設定に反映しました: %s（%s）",
                                ", ".join(applied), username)
            return result(STATUS_UNCHANGED, applied=applied)

        try:
            new_values = instance_config.update_config(
                app.instance_path, changes, username, expected_version=info["version"])
        except ConfigConflictError:
            return result(STATUS_CONFLICT, message=MSG_CONFLICT)
        except ConfigFileError as exc:
            app.logger.warning("システム設定（基本設定）を保存できませんでした: %s", exc)
            return result(STATUS_ERROR, state=state, message=str(exc))

        # 再起動が不要な項目は、実行中のアプリにもすぐ反映する
        applied = _apply_live(app, new_values)
        changed = [f.key for f in FIELDS if f.key in changes]
        restart_changed = [key for key in changed if FIELD_MAP[key].restart_required]
        app.logger.info("システム設定（基本設定）を変更しました: %s（%s）",
                        ", ".join(changed), username)
        return result(STATUS_OK, changed=changed, restart_changed=restart_changed,
                      applied=applied)


# --------------------------------------------------------------------------- #
# 画面表示用の値
# --------------------------------------------------------------------------- #
def _display(field, value):
    """入力欄に表示する値(秘密の値には使わない)。"""
    if field.type == TYPE_BOOL:
        return bool(value)
    if field.type == TYPE_ADDRESSES:
        if isinstance(value, str):
            items = re.split(r"[,;]", value)
        elif isinstance(value, (list, tuple)):
            items = [str(item) for item in value]
        else:
            items = []
        return "\n".join(item.strip() for item in items if item.strip())
    if value is None:
        return ""
    return str(value)


def _is_set(value):
    return value not in (None, "", [], ())


def _other_rows(app, file_values):
    """定義の無いキー(読み取り専用で「その他」に表示)。"""
    documented, fixed = documented_keys()
    base = defaults(app)
    keys = [(key, "config.example.py / app/config.py") for key in documented
            if key not in FIELD_MAP]
    keys += [(key, "instance/config.py だけに記載") for key in file_values
             if key not in FIELD_MAP and key not in fixed and key not in documented]
    rows = []
    for key, source in keys:
        in_file = key in file_values
        value = file_values[key] if in_file else base.get(key)
        hidden = bool(_SECRET_LIKE.search(key))
        text = repr(value) if (in_file or key in base) else ""
        rows.append({
            "key": key,
            "source": source,
            "in_file": in_file,
            "is_set": _is_set(value),
            "hidden": hidden,
            "value": "" if hidden else (text if len(text) <= 120 else text[:117] + "..."),
        })
    return rows


def context(app, state=None, errors=None):
    """基本設定タブの表示用の値。state / errors は保存エラーで再表示するときの入力と誤り。"""
    errors = errors or {}
    try:
        info = instance_config.read_config(app.instance_path)
        file_error = None
    except ConfigFileError as exc:
        info, file_error = None, str(exc)

    if info is not None:
        file_values = info["values"]
        current = effective(app, file_values)
        pending = pending_fields(app, file_values)
    else:
        file_values = {}
        current = {f.key: app.config.get(f.key) for f in FIELDS}
        pending = []
    pending_keys = {f.key for f in pending}

    groups = []
    for group_key, group_label in GROUPS:
        rows = []
        for field in (f for f in FIELDS if f.group == group_key):
            value = current.get(field.key)
            if field.type == TYPE_SECRET_KEY and info is None:
                value = running_value(app, field.key)
            row = {
                "field": field,
                "is_set": _is_set(value),
                "in_file": field.key in file_values,
                "pending": field.key in pending_keys,
                "error": errors.get(field.key),
                # キー名に clear などを使わない(Jinja の row.clear が dict.clear メソッドになるため)
                "clear_checked": bool(state and state.get("clear_" + field.key)),
                "generate_checked": bool(state and state.get("generate_" + field.key)),
                "value": "",
            }
            if not field.secret:
                if state is not None and field.key in state:
                    row["value"] = state[field.key]
                else:
                    row["value"] = _display(field, value)
            rows.append(row)
        groups.append({"key": group_key, "label": group_label, "rows": rows})

    test_to, _cc = mailer.recipients(test=True)
    return {
        "file_error": file_error,
        "can_save": info is not None,
        "exists": bool(info and info["exists"]),
        "version": info["version"] if info else "",
        "groups": groups,
        "other": _other_rows(app, file_values),
        "pending": pending,
        "pending_secret_key": "SECRET_KEY" in pending_keys,
        "error_count": len(errors),
        "mail_test_problem": mailer.check(test=True),
        "mail_test_to_count": len(test_to),
        "mail_test_to_is_from": not mailer.settings()["test_to"],
        "ai_enabled": ai_client.is_configured(),
        "ai_status": ai_client.status_label(),
    }
