"""週報の文章づくり(AI整形とルールベースの代替文)。

流れ:
  1. 動きのあった対象者ごとに AI を1回呼ぶ(個人の見本＋注意点＋その人の材料)
     動きの無い対象者は AI を使わず「今週の記載なし」と未完了の担当タスクを載せる
  2. チーム全体で AI を1回呼ぶ(チーム全体の見本＋注意点＋コードで集計した数値＋各人の文章)

AI が未設定、または呼び出しに失敗した部分は、同じ「■見出し／・箇条書き」の形で
ルールベースの文章を作り、文書側で「AI未整形」と注記する。
AI は部分ごと(各人・チーム全体)に毎回呼び出し、失敗した部分だけを代替の文章にする
(一時的なエラーで、残りの部分まで AI未整形 にならないようにするため)。

見本・注意点の差し込み記号 {期間} {氏名} {作成日} は、AIに送る前に置き換える。
"""
from app import ai_client
from app.weekly.rules import period_label

SYSTEM_PROMPT = """あなたはチームの週報を作成する担当者です。次のルールを必ず守ってください。
・【材料】に書かれた事実だけを使う。材料に無いことは書かない・推測しない。
・数値は材料に書かれたとおりに使う。新しい数値を計算・集計しない（合計・平均・割合なども出さない）。
・【見本】の見出し・順序・口調・分量に合わせる。
・【見本】に書かれた事実（案件名・数値・人名・出来事など）は決して使わない。見本は書き方の参考にだけ使う。
・見出しの行は「■」で始め、箇条書きの行は「・」で始める。
・プレーンテキストで書く。Markdown（#、**、-、表など）は使わない。
・書くべき事実が材料に無い項目は、作らずに「特になし」と書く。"""

NOTE_AI_OFF = "AI未整形（AIが未設定のため、集計内容をそのまま記載しています）"
NOTE_AI_FAILED = "AI未整形（AIの呼び出しに失敗したため、集計内容をそのまま記載しています）"
NO_ACTIVITY = "今週の記載なし"
NONE_TEXT = "特になし"


# --------------------------------------------------------------------------- #
# 表記の小道具
# --------------------------------------------------------------------------- #
def _mmdd(d):
    """日付(または日時)を mm/dd に。None は ―。"""
    return d.strftime("%m/%d") if d else "―"


def _money(value):
    return "{:,.0f} ￥/年".format(value)


def _hour(value):
    return "{:,.1f} ｈ/年".format(value)


def _outcome(f):
    """完了タスクの成果(実績)の表記。無ければ空文字。"""
    parts = [p for p in (f["outcome_quant"], f["outcome_qual"]) if p]
    return " ／ ".join(parts)


def _task_line(f):
    """タスク1件の1行表記(タイトル【状態】(優先度・開始・期限・規模))。"""
    info = ["優先度 {}".format(f["priority"] or "―"),
            "開始 {}".format(_mmdd(f["start_date"])),
            "期限 {}".format(_mmdd(f["due_date"]))]
    if f["scale_label"]:
        info.append("規模 {}".format(f["scale_label"]))
    return "{}【{}】（{}）".format(f["title"], f["status"], "・".join(info))


def _section(lines, title, items):
    """材料の1区分を追加する(項目が無ければ「なし」)。"""
    lines.append("[{}]".format(title))
    if items:
        lines.extend("・" + item for item in items)
    else:
        lines.append("・なし")
    lines.append("")


def _fill(text, period, name, created_on):
    """見本・注意点の差し込み記号を置き換える。"""
    return (text or "").replace("{期間}", period).replace("{氏名}", name).replace(
        "{作成日}", created_on.strftime("%Y/%m/%d"))


# --------------------------------------------------------------------------- #
# AIに渡す材料(テキスト)
# --------------------------------------------------------------------------- #
def person_material_text(p, period):
    """1人分の材料をテキストにする。"""
    lines = [
        "氏名: {}".format(p["name"]),
        "期間: {}".format(period),
        "月間負荷: {:.1f}h ／ 余力: {:.1f}h".format(p["total_h"], p["spare"]),
        "",
    ]
    _section(lines, "期間内に完了したタスク（成果は実績）", [
        "{}（完了日 {}）{}".format(
            f["title"], _mmdd(f["completed_on"]),
            " 成果: " + _outcome(f) if _outcome(f) else "")
        for f in p["completed"]
    ])
    _section(lines, "期間内の進捗記載（日付・タスク・記載者・内容）", [
        "{} {}（記載: {}）: {}".format(_mmdd(c["at"]), c["task"], c["author"], c["text"])
        for c in p["comments"]
    ])
    _section(lines, "期間内のステータス変更", [
        "{} {} → {}".format(_mmdd(c["at"]), c["task"], c["status"]) for c in p["changes"]
    ])
    _section(lines, "期間内に新しく登録されたタスク", [
        "{}（登録時の状態: {}）".format(f["title"], f["initial_status"]) for f in p["created"]
    ])
    _section(lines, "担当している未完了のタスク", [_task_line(f) for f in p["open_tasks"]])
    _section(lines, "期限超過の未完了タスク", [
        "{}（期限 {}・{}）".format(f["title"], _mmdd(f["due_date"]), f["status"])
        for f in p["overdue"]
    ])
    _section(lines, "今後7日以内に期限を迎えるタスク", [
        "{}（期限 {}・{}）".format(f["title"], _mmdd(f["due_date"]), f["status"])
        for f in p["due_soon"]
    ])
    _section(lines, "期間内に進捗記載の無い未完了タスク", [f["title"] for f in p["silent"]])
    return "\n".join(lines).strip()


def team_material_text(material, person_texts, period):
    """チーム全体の材料(コードで集計した数値＋各人の文章)をテキストにする。"""
    team = material["team"]
    names = "、".join(p["name"] for p in material["persons"])
    lines = [
        "期間: {}".format(period),
        "対象者: {}名（{}）".format(team["person_count"], names),
        "",
    ]
    _section(lines, "チーム全体の集計（システムで集計済み。複数担当のタスクは1件として数える）", [
        "期間内に完了: {}件".format(team["completed"]),
        "期間内に着手（進行中になった）: {}件".format(team["started"]),
        "期間内に新規登録: {}件".format(team["created"]),
        "現在 進行中: {}件".format(team["doing"]),
        "現在 保留: {}件".format(team["hold"]),
        "現在 未着手: {}件".format(team["todo"]),
        "期限超過（未完了）: {}件".format(team["overdue"]),
        "期間内の進捗記載: {}件".format(team["comments"]),
        "期間内に完了したタスクの成果（実績・年換算の合計）: 金額 {} ／ 時間 {}".format(
            _money(team["money_act"]), _hour(team["hour_act"])),
    ])
    _section(lines, "ヒト別の集計", [
        "{}: 完了 {}件 ／ 進行中 {}件 ／ 期限超過 {}件 ／ 進捗記載 {}件 ／ 月間負荷 {:.1f}h ／ 余力 {:.1f}h"
        .format(r["name"], r["completed"], r["doing"], r["overdue"], r["comments"],
                r["total_h"], r["spare"])
        for r in team["rows"]
    ])
    _section(lines, "期間内に完了したタスク", [
        "{}（担当 {}）{}".format(
            f["title"], f["assignees"] or "未割当",
            " 成果: " + _outcome(f) if _outcome(f) else "")
        for f in team["completed_tasks"]
    ])
    _section(lines, "期限超過の未完了タスク", [
        "{}（担当 {}・期限 {}・{}）".format(
            f["title"], f["assignees"] or "未割当", _mmdd(f["due_date"]), f["status"])
        for f in team["overdue_tasks"]
    ])
    lines.append("[各メンバーの週報（個人分）]")
    for name, text in person_texts:
        lines.append("【{}】".format(name))
        lines.append(text.strip())
        lines.append("")
    return "\n".join(lines).strip()


# --------------------------------------------------------------------------- #
# ルールベースの文章(AIが使えないときの代替)
# --------------------------------------------------------------------------- #
def _block(lines, heading, items):
    lines.append("■" + heading)
    if items:
        lines.extend("・" + item for item in items)
    else:
        lines.append("・" + NONE_TEXT)


def person_rule_text(p):
    """1人分の文章(ルールベース)。"""
    results = []
    for f in p["completed"]:
        outcome = _outcome(f)
        results.append("完了: {}（{}）".format(
            f["title"], "成果: " + outcome if outcome else "完了日 " + _mmdd(f["completed_on"])))
    # 進捗記載はタスクごとにまとめる(登場順)
    by_task = {}
    for c in p["comments"]:
        by_task.setdefault(c["task"], []).append(
            "{} {}（{}）".format(_mmdd(c["at"]), c["text"], c["author"]))
    results.extend("{}: {}".format(title, " ／ ".join(items)) for title, items in by_task.items())

    changes = ["{} {} → {}".format(_mmdd(c["at"]), c["task"], c["status"]) for c in p["changes"]]
    changes.extend("新規登録: {}（{}）".format(f["title"], f["initial_status"]) for f in p["created"])

    issues = ["期限超過: {}（期限 {}・{}）".format(f["title"], _mmdd(f["due_date"]), f["status"])
              for f in p["overdue"]]
    if p["silent"]:
        issues.append("今週の進捗記載なし: {}".format("、".join(f["title"] for f in p["silent"])))

    plans = ["期限が近い: {}（期限 {}）".format(f["title"], _mmdd(f["due_date"])) for f in p["due_soon"]]

    lines = []
    _block(lines, "今週の実績", results)
    _block(lines, "状況の変化", changes)
    _block(lines, "課題・遅れ", issues)
    _block(lines, "来週の予定", plans)
    _block(lines, "負荷", ["月間負荷 {:.1f}h ／ 余力 {:.1f}h".format(p["total_h"], p["spare"])])
    return "\n".join(lines)


def no_activity_text(p):
    """動きの無かった対象者の文章(「今週の記載なし」＋未完了の担当タスク)。"""
    lines = [NO_ACTIVITY]
    _block(lines, "未完了の担当タスク", [
        "{}【{}】（期限 {}）".format(f["title"], f["status"], _mmdd(f["due_date"]))
        for f in p["open_tasks"]
    ])
    return "\n".join(lines)


def team_rule_text(material, period):
    """チーム全体の文章(ルールベース)。"""
    team = material["team"]
    lines = []
    _block(lines, "全体の状況（{}・対象 {}名）".format(period, team["person_count"]), [
        "完了 {}件 ／ 着手 {}件 ／ 新規 {}件 ／ 進行中 {}件 ／ 保留 {}件 ／ 期限超過 {}件".format(
            team["completed"], team["started"], team["created"],
            team["doing"], team["hold"], team["overdue"]),
        "進捗記載 {}件".format(team["comments"]),
    ])
    results = ["成果の合計（年換算）: 金額 {} ／ 時間 {}".format(
        _money(team["money_act"]), _hour(team["hour_act"]))] if team["completed"] else []
    results.extend(
        "{}（担当 {}）{}".format(
            f["title"], f["assignees"] or "未割当",
            ": " + _outcome(f) if _outcome(f) else "")
        for f in team["completed_tasks"]
    )
    _block(lines, "今週完了したタスクと成果", results)
    _block(lines, "課題・遅れ", [
        "期限超過: {}（担当 {}・期限 {}）".format(
            f["title"], f["assignees"] or "未割当", _mmdd(f["due_date"]))
        for f in team["overdue_tasks"]
    ])
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# AI 呼び出し
# --------------------------------------------------------------------------- #
def _messages(sample, guidelines, material_text, instruction):
    content = "\n".join([
        "【見本】（書き方の参考。ここに書かれた事実は使わないこと）",
        sample.strip() or "（見本なし）",
        "",
        "【書く際の注意点】",
        guidelines.strip() or NONE_TEXT,
        "",
        "【材料】（ここに書かれた事実だけを使うこと）",
        material_text,
        "",
        instruction,
    ])
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]


def _clean(text):
    """AIの応答を整える(改行の統一・コードブロック記号の除去・前後の空白除去)。"""
    lines = []
    for line in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.strip().startswith("```"):
            continue
        lines.append(line.rstrip())
    return "\n".join(lines).strip()


class _AiSession:
    """1回の週報作成の間の AI 呼び出し状況(部分ごとに呼び、失敗した部分だけ代替文にする)。"""

    def __init__(self):
        self.configured = ai_client.is_configured()
        self.error = None  # 最初に失敗したときのエラー(前回の結果の表示用)
        self.used = 0
        self.fallback = 0

    def write(self, messages, rule_text):
        """AIで書く。使えなければ rule_text を使う。戻り値: (本文, AIを使ったか, 注記)"""
        if not self.configured:
            self.fallback += 1
            return rule_text, False, NOTE_AI_OFF
        text, error = ai_client.chat(messages)
        text = _clean(text) if error is None else ""
        if text:
            self.used += 1
            return text, True, None
        if self.error is None:
            self.error = error or "AIの応答が空でした。"
        self.fallback += 1
        return rule_text, False, NOTE_AI_FAILED


def write_report(material, settings, created_on):
    """材料から、チーム全体と各人の文章を作る。

    戻り値:
      {"team": {"text", "ai", "note"},
       "persons": [{"name", "text", "ai", "note", "no_activity"}],
       "ai_configured", "ai_error", "ai_used", "ai_fallback"}
    """
    period = period_label(material["start"], material["end"])
    ai = _AiSession()

    persons = []
    for p in material["persons"]:
        if not p["has_activity"]:
            persons.append({"name": p["name"], "text": no_activity_text(p),
                            "ai": False, "note": None, "no_activity": True})
            continue
        messages = _messages(
            _fill(settings["person_sample"], period, p["name"], created_on),
            _fill(settings["guidelines"], period, p["name"], created_on),
            person_material_text(p, period),
            "上の材料だけを使って、{}の週報（個人分）を【見本】の見出し・順序・口調・分量に"
            "合わせて作成してください。氏名の見出しは不要です。".format(p["name"]),
        )
        text, used_ai, note = ai.write(messages, person_rule_text(p))
        persons.append({"name": p["name"], "text": text, "ai": used_ai,
                        "note": note, "no_activity": False})

    team_name = "チーム全体"
    messages = _messages(
        _fill(settings["team_sample"], period, team_name, created_on),
        _fill(settings["guidelines"], period, team_name, created_on),
        team_material_text(material, [(p["name"], p["text"]) for p in persons], period),
        "上の材料だけを使って、チーム全体の週報を【見本】の見出し・順序・口調・分量に"
        "合わせて作成してください。メンバー別の集計表はシステムが別に付けるため、表は作らないでください。",
    )
    text, used_ai, note = ai.write(messages, team_rule_text(material, period))

    return {
        "team": {"text": text, "ai": used_ai, "note": note},
        "persons": persons,
        "ai_configured": ai.configured,
        "ai_error": ai.error,
        "ai_used": ai.used,
        "ai_fallback": ai.fallback,
    }
