"""スキルテストの問題(4択)をAIで作成し、検証して問題プールに保存する。

AIの接続はアプリ共通の app/ai_client.py の chat() を使う(接続先・キーは instance/config.py)。
1回の呼び出しで作る問題は最大 CHUNK_SIZE 問。足りなければ数回に分けて呼び出す。

AIの応答は信用せず、次をすべて満たす問題だけを保存する:
  ・問題文が空でなく、長すぎない
  ・選択肢がちょうど4つで、どれも空でなく、長すぎず、互いに異なる
  ・正解の位置(answer_index)が 0〜3 の整数
  ・「すべて正しい」「どれでもない」などの選択肢を含まない
  ・同じスキルの既存の問題(有効・無効とも)や、同じ応答の中の問題と内容が重複しない
    (全角/半角・大文字/小文字・空白・句読点の違いは同じとみなす)
応答の前後にコードブロック(```json … ```)や説明文が付いていても、JSONの配列を取り出して読む。
"""
import json
import math
import re
import time
import unicodedata

from flask import current_app

from app import ai_client
from app.extensions import db
from app.models.skill import SKILL_TECHNICAL, level_label
from app.models import skilltest as skilltest_models
from app.models.skilltest import SOURCE_AI, SkillTestQuestion

# 1回のAI呼び出しで作る問題数の上限
CHUNK_SIZE = 10

# 1問あたりの長さの上限(文字数)
QUESTION_MAX = 500
CHOICE_MAX = 200
EXPLANATION_MAX = 1000

# 重複を避けるためにAIへ伝える既存の問題の数と、1問あたりの文字数
AVOID_SAMPLES = 30
AVOID_SAMPLE_CHARS = 60

# レベル(1〜4)ごとの難易度の目安(到達尺度の文言とあわせてAIに伝える)
DIFFICULTY = {
    1: "入門レベル。基本的な用語・概念・操作を正しく理解しているかを問う。",
    2: "初級レベル。基本を組み合わせた簡単な応用や、よくある場面での正しいやり方を問う。",
    3: "中級レベル。設計上の選択、問題の原因の切り分け、注意点など、実践での判断を問う。",
    4: "上級レベル。複数の要素にまたがる深い理解と、状況に応じた最適な判断を問う。",
}

# 使わせない選択肢(「すべて正しい」「どれでもない」の類)
_FORBIDDEN_CHOICE = re.compile(
    r"(すべて|全て|全部|いずれも|どれも)(が)?(正しい|誤り|誤っている|正解|当てはまる|該当する|該当しない)"
    r"|どれでもない|いずれでもない|どれも当てはまらない|上記(の)?(すべて|全て|いずれ|どれ)"
    r"|all of the above|none of the above",
    re.IGNORECASE,
)

# 重複判定で無視する文字(空白・句読点・括弧・引用符など)
_IGNORABLE = re.compile(r"[\s、。，．,.!！?？・:：;；「」『』（）()\[\]【】{}<>＜＞\"'`“”‘’]+")


def normalize_text(text):
    """重複判定用に文章を正規化する(NFKC・小文字化・空白と句読点の除去)。"""
    value = unicodedata.normalize("NFKC", str(text or "")).lower()
    return _IGNORABLE.sub("", value)


def model_label():
    """問題に記録するAIのモデル名(instance/config.py の AI_MODEL。空なら既定のモデル名)。"""
    name = str(current_app.config.get("AI_MODEL") or "").strip() or ai_client.DEFAULT_MODEL
    return name[:64]


def build_messages(skill, level, count, avoid=()):
    """AIに送るメッセージ(OpenAI形式)を作る。"""
    label = level_label(skill.skill_type or SKILL_TECHNICAL, level)
    lines = [
        "次の条件で、4択の問題を{}問作成してください。".format(count),
        "",
        "■スキル",
        "名称: {}".format(skill.name),
        "カテゴリ: {}".format(skill.category or "（なし）"),
        "説明: {}".format((skill.description or "（なし）").strip()),
        "",
        "■難易度: レベル{}（1〜4の4段階）".format(level),
        "このレベルの目安: 「{}」人なら正解できる水準".format(label),
        "出題の方針: {}".format(DIFFICULTY.get(level, DIFFICULTY[4])),
        "",
        "■守ること",
        "・特定の組織の事情に依存しない、一般に通用する知識・技能を問う",
        "・正解はちょうど1つ。ほかの3つは、もっともらしいが明確に誤りの選択肢にする",
        "・「すべて正しい」「どれでもない」のような選択肢は使わない",
        "・4つの選択肢はすべて異なる内容にする",
        "・問題文は200文字程度まで、選択肢は60文字程度までに簡潔にまとめる",
        "・正解の位置（answer_index）が特定の位置に偏らないようにする",
        "・explanation には、正解の理由を簡潔に書く",
    ]
    samples = [s for s in avoid if s][:AVOID_SAMPLES]
    if samples:
        lines.append("・次の既存の問題と同じ内容の問題は作らない:")
        for text in samples:
            one_line = " ".join(str(text).split())
            lines.append("  - {}".format(one_line[:AVOID_SAMPLE_CHARS]))
    lines += [
        "",
        "■出力形式",
        "JSONの配列だけを出力する（前後に説明文を付けない）。各要素の形は次のとおり。",
        '[{"question": "問題文", "choices": ["選択肢1", "選択肢2", "選択肢3", "選択肢4"], '
        '"answer_index": 0, "explanation": "解説"}]',
        "answer_index は正解の選択肢の位置（0〜3の整数）。",
    ]
    return [
        {"role": "system",
         "content": ("あなたは、技術スキルの理解度を確認するための4択問題を作る出題者です。"
                     "指示された条件を守り、JSONの配列だけを出力してください。")},
        {"role": "user", "content": "\n".join(lines)},
    ]


def _extract_json_array(text):
    """AIの応答からJSONの配列を取り出す(コードブロックや前後の文章があっても読む)。"""
    body = str(text or "").strip()
    fence = re.match(r"^```[A-Za-z0-9_-]*\s*\n?(.*?)\n?```\s*$", body, re.DOTALL)
    if fence:
        body = fence.group(1).strip()
    try:
        data = json.loads(body)
    except ValueError:
        start, end = body.find("["), body.rfind("]")
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(body[start:end + 1])
        except ValueError:
            return None
    if isinstance(data, dict):
        # {"questions": [...]} の形で返ってきた場合も受け付ける
        for value in data.values():
            if isinstance(value, list):
                return value
        return None
    return data if isinstance(data, list) else None


# 保存しない制御文字(改行・タブ以外。Excel出力や画面表示で問題になるため除く)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean(value):
    """制御文字と前後の空白を除いた文字列(文字列でなければ None)。"""
    if not isinstance(value, str):
        return None
    return _CONTROL.sub("", value.replace("\r\n", "\n").replace("\r", "\n")).strip()


def validate_item(item):
    """AIが作った1問を検証する。正しければ整えた辞書、不正なら None。"""
    if not isinstance(item, dict):
        return None
    question = _clean(item.get("question"))
    if not question or len(question) > QUESTION_MAX:
        return None
    choices = item.get("choices")
    if not isinstance(choices, list) or len(choices) != 4:
        return None
    cleaned = []
    for choice in choices:
        text = _clean(choice)
        if not text or len(text) > CHOICE_MAX or _FORBIDDEN_CHOICE.search(text):
            return None
        cleaned.append(text)
    if len({normalize_text(c) for c in cleaned}) != 4 or any(not normalize_text(c) for c in cleaned):
        return None
    index = item.get("answer_index")
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index <= 3:
        return None
    explanation = item.get("explanation", "")
    if explanation is None:
        explanation = ""
    explanation = _clean(explanation)
    if explanation is None:
        return None
    if len(explanation) > EXPLANATION_MAX:
        explanation = explanation[:EXPLANATION_MAX]
    return {"question": question, "choices": cleaned, "answer_index": index,
            "explanation": explanation}


def parse_response(text):
    """AIの応答を読み、検証を通った問題の一覧を返す: (問題のリスト, エラー)。"""
    items = _extract_json_array(text)
    if items is None:
        return [], "AIの応答をJSONの配列として読み取れませんでした。"
    valid = [v for v in (validate_item(item) for item in items) if v is not None]
    return valid, None


def existing_keys(skill_id):
    """そのスキルの既存の問題(有効・無効とも)の正規化した問題文の集合。"""
    rows = db.session.query(SkillTestQuestion.question).filter_by(skill_id=skill_id).all()
    return {normalize_text(r[0]) for r in rows}


def _avoid_samples(skill_id, level):
    """重複を避けるためにAIへ伝える既存の問題文(新しい順)。"""
    rows = (
        db.session.query(SkillTestQuestion.question)
        .filter_by(skill_id=skill_id, level=level)
        .order_by(SkillTestQuestion.id.desc())
        .limit(AVOID_SAMPLES)
        .all()
    )
    return [r[0] for r in rows]


def generate(skill, level, count, max_calls=None, stop_at=None):
    """AIで問題を作り、検証を通ったものを問題プールに保存する(呼び出したスレッドで実行)。

    count     : 作りたい問題数(足りなければ CHUNK_SIZE 問ずつ数回に分けて呼び出す)
    max_calls : AIを呼び出す回数の上限(省略時は 必要回数＋1。重複・不正で減った分の補い)
    stop_at   : この時刻(time.monotonic())を過ぎたら次の呼び出しをしない(受験者を待たせすぎない)
    戻り値: (保存した SkillTestQuestion のリスト, エラーメッセージ または None)
    AIに接続できない・応答が無いなどのエラーが起きたら、その時点で止める
    (それまでに保存した問題は残る)。応答の形式が不正なだけなら、回数の上限まで続ける。
    """
    created = []
    if count <= 0:
        return created, None
    if max_calls is None:
        max_calls = int(math.ceil(count / float(CHUNK_SIZE))) + 1
    keys = existing_keys(skill.id)
    model = model_label()
    last_error = None
    calls = 0
    while len(created) < count and calls < max_calls:
        if stop_at is not None and time.monotonic() >= stop_at:
            return created, "時間内に必要な数の問題を作成できませんでした。"
        calls += 1
        want = min(CHUNK_SIZE, count - len(created))
        text, error = ai_client.chat(build_messages(skill, level, want, _avoid_samples(skill.id, level)))
        if error:
            return created, error
        items, parse_error = parse_response(text)
        if parse_error:
            last_error = parse_error
            continue
        added = 0
        for item in items:
            if len(created) >= count:
                break
            key = normalize_text(item["question"])
            if not key or key in keys:
                continue
            keys.add(key)
            question = SkillTestQuestion(
                skill_id=skill.id,
                level=level,
                question=item["question"],
                choices=json.dumps(item["choices"], ensure_ascii=False),
                answer_index=item["answer_index"],
                explanation=item["explanation"],
                source=SOURCE_AI,
                model=model,
                is_active=True,
                created_at=skilltest_models._now(),
            )
            db.session.add(question)
            created.append(question)
            added += 1
        # 呼び出しごとに保存する(後で失敗しても、ここまでの問題は残す)
        db.session.commit()
        if added == 0:
            last_error = "AIの応答に使える問題がありませんでした（形式の不備・重複）。"
    if len(created) < count:
        return created, last_error or "必要な数の問題を作成できませんでした。"
    return created, None
