"""営業日カレンダー(土日と日本の祝日・休日。純粋な Python だけで計算する)。

外部のライブラリや祝日データのファイルは使わず、「国民の祝日に関する法律」の
ルールから計算する。DBにもFlaskにも依存しないため、どこからでも使える。

  is_holiday(d)                    : 祝日・休日(振替休日・国民の休日を含む)か
  holiday_name(d)                  : 祝日・休日の名前(該当しなければ None)
  is_business_day(d)               : 営業日(月〜金で、祝日・休日でない日)か
  business_days_ago(past, today)   : past より後〜today まで(両端のうち today を含む)の
                                     営業日の日数。同じ日なら 0

計算するもの:
  - 日付が決まっている祝日(元日・建国記念の日・天皇誕生日・昭和の日・憲法記念日・
    みどりの日・こどもの日・山の日・文化の日・勤労感謝の日)
  - ハッピーマンデー(成人の日・海の日・敬老の日・スポーツの日〔体育の日〕)
  - 春分の日・秋分の日(1980〜2099年の標準的な計算式。範囲外の年も同じ式で近似する)
  - 振替休日(祝日が日曜日のとき、その後の最も近い祝日でない日。2006年までは翌月曜日)
  - 国民の休日(前日と翌日が祝日である、祝日でない日。日曜日を除く)
  - 一度きりの祝日・休日(2019年の天皇の即位の日・即位礼正殿の儀の行われる日、
    2020・2021年の海の日・スポーツの日・山の日の移動など)
法律の改正の年(成人の日のハッピーマンデー化・天皇誕生日の日付など)も反映する。
祝日法の施行(1948年7月20日)より前の日付は、祝日なしとして扱う。
"""
from datetime import date, datetime, timedelta
from functools import lru_cache

_ONE_DAY = timedelta(days=1)

# 祝日法の施行日・振替休日の導入日・国民の休日の導入日・振替休日の改正日
_LAW_START = date(1948, 7, 20)
_SUBSTITUTE_START = date(1973, 4, 12)
_BRIDGE_START = date(1985, 12, 27)
_SUBSTITUTE_2007 = date(2007, 1, 1)

# 一度きりの祝日・休日(特別法による)
_SPECIAL_DAYS = {
    date(1959, 4, 10): "皇太子明仁親王の結婚の儀",
    date(1989, 2, 24): "昭和天皇の大喪の礼",
    date(1990, 11, 12): "即位礼正殿の儀",
    date(1993, 6, 9): "皇太子徳仁親王の結婚の儀",
    date(2019, 5, 1): "天皇の即位の日",
    date(2019, 10, 22): "即位礼正殿の儀の行われる日",
}

# 2020・2021年は海の日・スポーツの日・山の日が特別法で移動した
_MOVED_DAYS = {
    2020: {"海の日": (7, 23), "スポーツの日": (7, 24), "山の日": (8, 10)},
    2021: {"海の日": (7, 22), "スポーツの日": (7, 23), "山の日": (8, 8)},
}


def _to_date(value):
    """datetime は日付部分だけにする(date はそのまま)。"""
    if isinstance(value, datetime):
        return value.date()
    return value


def _nth_monday(year, month, nth):
    """その月の第 nth 月曜日。"""
    first = date(year, month, 1)
    offset = (0 - first.weekday()) % 7  # 0 = 月曜日
    return first + timedelta(days=offset + 7 * (nth - 1))


def vernal_equinox_day(year):
    """春分の日の日付(3月の日)。1980〜2099年の標準的な計算式。"""
    n = year - 1980
    return int(20.8431 + 0.242194 * n) - n // 4


def autumnal_equinox_day(year):
    """秋分の日の日付(9月の日)。1980〜2099年の標準的な計算式。"""
    n = year - 1980
    return int(23.2488 + 0.242194 * n) - n // 4


def _national_holidays(year):
    """その年の「国民の祝日」(振替休日・国民の休日を除く) {date: 名前}。"""
    days = {}

    def add(month, day, name):
        d = date(year, month, day)
        if d >= _LAW_START:
            days[d] = name

    moved = _MOVED_DAYS.get(year, {})

    add(1, 1, "元日")
    if year >= 2000:
        d = _nth_monday(year, 1, 2)
        add(d.month, d.day, "成人の日")
    elif year >= 1949:
        add(1, 15, "成人の日")
    if year >= 1967:
        add(2, 11, "建国記念の日")
    if year >= 2020:
        add(2, 23, "天皇誕生日")
    if year >= 1949:
        add(3, vernal_equinox_day(year), "春分の日")
    if year >= 2007:
        add(4, 29, "昭和の日")
    elif year >= 1989:
        add(4, 29, "みどりの日")
    else:
        add(4, 29, "天皇誕生日")
    add(5, 3, "憲法記念日")
    if year >= 2007:
        add(5, 4, "みどりの日")
    add(5, 5, "こどもの日")
    if "海の日" in moved:
        add(*moved["海の日"], "海の日")
    elif year >= 2003:
        d = _nth_monday(year, 7, 3)
        add(d.month, d.day, "海の日")
    elif year >= 1996:
        add(7, 20, "海の日")
    if "山の日" in moved:
        add(*moved["山の日"], "山の日")
    elif year >= 2016:
        add(8, 11, "山の日")
    if year >= 2003:
        d = _nth_monday(year, 9, 3)
        add(d.month, d.day, "敬老の日")
    elif year >= 1966:
        add(9, 15, "敬老の日")
    add(9, autumnal_equinox_day(year), "秋分の日")
    if "スポーツの日" in moved:
        add(*moved["スポーツの日"], "スポーツの日")
    elif year >= 2000:
        d = _nth_monday(year, 10, 2)
        add(d.month, d.day, "スポーツの日" if year >= 2020 else "体育の日")
    elif year >= 1966:
        add(10, 10, "体育の日")
    add(11, 3, "文化の日")
    add(11, 23, "勤労感謝の日")
    if 1989 <= year <= 2018:
        add(12, 23, "天皇誕生日")

    for d, name in _SPECIAL_DAYS.items():
        if d.year == year:
            days[d] = name
    return days


@lru_cache(maxsize=256)
def _holidays_of_year(year):
    """その年の祝日・休日(振替休日・国民の休日を含む) {date: 名前}。"""
    national = _national_holidays(year)
    result = dict(national)

    # 振替休日: 祝日が日曜日のとき
    #   2007年から: その後の最も近い「祝日でない日」
    #   2006年まで: 翌日(月曜日)が祝日でなければ、その翌日
    for d in sorted(national):
        if d.weekday() != 6 or d < _SUBSTITUTE_START:
            continue
        substitute = d + _ONE_DAY
        if d >= _SUBSTITUTE_2007:
            while substitute in national:
                substitute += _ONE_DAY
        elif substitute in national:
            continue
        if substitute.year == year:
            result.setdefault(substitute, "振替休日")

    # 国民の休日: 前日と翌日が祝日で、その日自体は祝日でない日(日曜日・振替休日を除く)
    for d in sorted(national):
        between = d + _ONE_DAY
        if (between >= _BRIDGE_START and between.year == year
                and between not in result and between.weekday() != 6
                and (between + _ONE_DAY) in national):
            result[between] = "国民の休日"
    return result


def holiday_name(d):
    """祝日・休日の名前(振替休日・国民の休日を含む)。該当しなければ None。"""
    d = _to_date(d)
    return _holidays_of_year(d.year).get(d)


def is_holiday(d):
    """祝日・休日(振替休日・国民の休日を含む)か。土日であることは問わない。"""
    return holiday_name(d) is not None


def is_business_day(d):
    """営業日(月〜金で、祝日・休日でない日)か。"""
    d = _to_date(d)
    return d.weekday() < 5 and not is_holiday(d)


def business_days_ago(past_date, today):
    """past_date より後〜today までの営業日の日数(past_date < d <= today)。

    同じ日(または past_date が today より後)なら 0。
    例: 金曜日 → 次の月曜日(祝日でない)は 1。
    """
    past_date, today = _to_date(past_date), _to_date(today)
    if past_date >= today:
        return 0
    count = 0
    d = past_date + _ONE_DAY
    while d <= today:
        if is_business_day(d):
            count += 1
        d += _ONE_DAY
    return count
