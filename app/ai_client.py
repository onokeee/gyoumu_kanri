"""ChatGPT(OpenAI互換)API クライアント(アプリ共通。週報の文章整形・スキルテストの問題作成で使用)。

どの機能からも `from app import ai_client` で使う(機能ごとに接続部分を持たない)。

★将来の差し替えポイント★
独自のOpenAI互換APIに移行する場合は、このファイルの `_call_chat_api()` の中身
だけを書き換える。呼び出し側は `chat()` の戻り値の形 (text, error) にしか
依存していないので、他のコードは変更不要。

接続設定は instance/config.py に記入する(このファイルには書かない):
  AI_API_URL  : エンドポイント(空なら OpenAI公式 DEFAULT_API_URL)
  AI_API_KEY  : APIキー(キー不要の独自APIなら空でよい)
  AI_MODEL    : モデル名
  AI_TIMEOUT  : タイムアウト(秒)
AI_API_KEY と AI_API_URL がどちらも空なら機能は自動的に無効(is_configured() が False)
になり、呼び出し側はAIを使わない動きになる(週報はルールベースの文章、
スキルテストは問題プールにある問題だけで出題)。
APIキーは画面・ログ・エラーメッセージのどこにも表示しない。
"""
import json
import socket
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from flask import current_app

DEFAULT_API_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_TIMEOUT = 60


def _settings():
    """現在の接続設定(instance/config.py の値。未記入の項目は app/config.py の既定値)。"""
    config = current_app.config
    try:
        timeout = int(config.get("AI_TIMEOUT") or DEFAULT_TIMEOUT)
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT
    return {
        "api_url": str(config.get("AI_API_URL") or "").strip(),
        "api_key": str(config.get("AI_API_KEY") or "").strip(),
        "model": str(config.get("AI_MODEL") or "").strip() or DEFAULT_MODEL,
        "timeout": timeout if timeout > 0 else DEFAULT_TIMEOUT,
    }


def is_configured():
    """ChatGPT-APIが使える設定になっているか(キーまたはURLが記入済み)。"""
    values = _settings()
    return bool(values["api_key"] or values["api_url"])


def _endpoint_label(url):
    """接続先の表示用(スキームとホスト名だけ。URL内の認証情報・パス・クエリは表示しない)。"""
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        host = None
    if not host:
        return "（URLを解釈できません）"
    return "{}://{}".format(parts.scheme or "http", host)


def status_label():
    """画面表示用の状態文言(APIキーや接続先URLの詳細は表示しない)。"""
    if not is_configured():
        return ("未設定（instance/config.py の AI_API_KEY "
                "または AI_API_URL に記入すると使えます）")
    values = _settings()
    return "接続先: {} ／ モデル: {}".format(
        _endpoint_label(values["api_url"] or DEFAULT_API_URL), values["model"]
    )


def _mask(text, api_key):
    """エラーメッセージにAPIキーが含まれていた場合に伏せ字にする。"""
    text = str(text or "")
    if api_key and api_key in text:
        text = text.replace(api_key, "***")
    return text


# --------------------------------------------------------------------------- #
# ここから下が差し替え対象(HTTP通信部分)
# --------------------------------------------------------------------------- #
def _call_chat_api(messages):
    """チャット補完APIを呼び出して本文テキストを返す。

    独自APIに差し替える場合は、この関数だけをそのAPIの仕様に合わせて書き換える。
    (認証ヘッダ・リクエスト形式・レスポンスの取り出し方など)
    例外はそのまま送出し、呼び出し元の chat() で文言に変換する。
    """
    values = _settings()
    url = values["api_url"] or DEFAULT_API_URL

    payload = {
        "model": values["model"],
        "messages": messages,
        "temperature": 0.3,
    }
    request_obj = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
    )
    request_obj.add_header("Content-Type", "application/json; charset=utf-8")
    if values["api_key"]:
        request_obj.add_header("Authorization", "Bearer {}".format(values["api_key"]))

    with urllib.request.urlopen(request_obj, timeout=values["timeout"]) as response:
        data = json.loads(response.read().decode("utf-8"))

    # OpenAI互換のレスポンス形式から本文を取り出す
    return data["choices"][0]["message"]["content"]


# --------------------------------------------------------------------------- #
# 呼び出し側が使うのはこの関数だけ
# --------------------------------------------------------------------------- #
def chat(messages):
    """メッセージ列(OpenAI形式の role/content の辞書のリスト)をAIに送る。

    戻り値: (応答の本文, None) / 失敗時は (None, エラーメッセージ)
    """
    if not is_configured():
        return None, ("ChatGPT-APIが未設定です。instance/config.py の AI_API_KEY"
                      "（独自APIの場合は AI_API_URL）を設定してください。")

    values = _settings()
    api_key = values["api_key"]
    try:
        text = _call_chat_api(messages)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "ignore")[:200]
        except Exception:
            pass
        return None, _mask("APIエラー({}): {}".format(exc.code, detail or exc.reason),
                           api_key)
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (socket.timeout, TimeoutError)):
            return None, "APIの応答がタイムアウトしました（{}秒）。".format(values["timeout"])
        return None, _mask("APIに接続できませんでした: {}".format(exc.reason), api_key)
    except (socket.timeout, TimeoutError):
        return None, "APIの応答がタイムアウトしました（{}秒）。".format(values["timeout"])
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        return None, _mask("APIの応答を解釈できませんでした: {}".format(exc), api_key)
    except Exception as exc:  # 想定外
        return None, _mask("AI処理に失敗しました: {}".format(exc), api_key)

    text = (text or "").strip() if isinstance(text, str) else ""
    if not text:
        return None, "AIの応答が空でした。"
    return text, None
