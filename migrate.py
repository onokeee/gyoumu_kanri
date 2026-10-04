"""既存DBを最新のモデル定義に合わせる移行スクリプト。

実行: python migrate.py                 (確認のみ: python migrate.py --check)
      python migrate.py --db 別のDBのパス (instance/app.db 以外を対象にする場合)

コードを新しいものに差し替えたあと、**実運用中のDBを消さずに**このスクリプトを
1回実行すれば、不足しているテーブル・列が追加されて動くようになる。

やること:
  1. モデルにあってDBに無い「テーブル」を作成 (db.create_all)
  2. モデルにあってDBに無い「列」を ALTER TABLE ADD COLUMN で追加
     ※SQLiteでは列の削除・型変更ができないため、追加のみ行う
  3. DBにだけ残っている未使用列は、そのまま放置(読み書きしないので無害)

既存データは一切削除・変更しない。何度実行しても安全(冪等)。
"""
import os
import sys

from sqlalchemy import inspect, text

from app import create_app
from app.extensions import db
import app.models  # noqa: F401  モデルを読み込んでメタデータを埋める


def collect_changes(insp):
    """不足しているテーブル・列を洗い出す。"""
    db_tables = set(insp.get_table_names())
    missing_tables = []
    missing_columns = []   # (table, column, ddl_type, nullable)

    for table in db.metadata.sorted_tables:
        if table.name not in db_tables:
            missing_tables.append(table.name)
            continue
        have = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in have:
                continue
            ddl_type = col.type.compile(db.engine.dialect)
            missing_columns.append((table.name, col.name, ddl_type, col.nullable))
    return missing_tables, missing_columns


def unused_columns(insp):
    """DBにだけ残っている列(無害だが参考表示)。"""
    result = []
    db_tables = set(insp.get_table_names())
    for table in db.metadata.sorted_tables:
        if table.name not in db_tables:
            continue
        have = {c["name"] for c in insp.get_columns(table.name)}
        want = {c.name for c in table.columns}
        for name in sorted(have - want):
            result.append((table.name, name))
    return result


def _db_override():
    """--db でDBパスが指定されていればそのパスを返す。"""
    if "--db" in sys.argv:
        index = sys.argv.index("--db")
        if index + 1 < len(sys.argv):
            return sys.argv[index + 1]
    return None


def _build_app(path):
    """対象DB用のアプリを用意する。

    Flask-SQLAlchemy は init_app 時に接続先を確定するため、あとから
    SQLALCHEMY_DATABASE_URI を書き換えても効かない。--db 指定時は
    専用のアプリを組み立てて、既定のDB(instance/app.db)には一切触れない。
    """
    if not path:
        return create_app()  # 通常はアプリ本体(= instance/app.db)を対象にする

    from flask import Flask

    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///{}".format(
        os.path.abspath(path)
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    with app.app_context():
        db.create_all()  # 指定DBに対して不足テーブルを作成
    return app


def main():
    check_only = "--check" in sys.argv
    app = _build_app(_db_override())

    with app.app_context():
        print("対象DB:", db.engine.url)  # 実際に接続しているDBを表示する
        insp = inspect(db.engine)
        missing_tables, missing_columns = collect_changes(insp)

        # create_all 済みなので、ここで残っている missing_tables は基本無いはず
        if missing_tables:
            print("作成されたテーブル:", ", ".join(missing_tables))

        if not missing_columns:
            print("不足している列はありません。DBは最新の状態です。")
        else:
            print("不足している列: {} 件".format(len(missing_columns)))
            for table, col, ddl_type, nullable in missing_columns:
                print("  - {}.{} ({})".format(table, col, ddl_type))

            if check_only:
                print("\n--check のため変更していません。"
                      "実行するには: python migrate.py")
                return

            added, skipped = 0, []
            for table, col, ddl_type, nullable in missing_columns:
                if not nullable:
                    # SQLiteは NOT NULL 列を後から追加できない(既定値が必要)
                    skipped.append("{}.{}".format(table, col))
                    continue
                with db.engine.begin() as conn:
                    conn.execute(text(
                        'ALTER TABLE "{}" ADD COLUMN "{}" {}'.format(table, col, ddl_type)
                    ))
                added += 1
                print("  追加: {}.{}".format(table, col))
            print("列を {} 件追加しました。".format(added))
            if skipped:
                print("★手動対応が必要(NOT NULL列のため自動追加不可):",
                      ", ".join(skipped))

        extras = unused_columns(insp)
        if extras:
            print("\n参考: DBにだけ残る未使用列(読み書きしないので無害)")
            for table, col in extras:
                print("  - {}.{}".format(table, col))

        # 最終確認
        insp2 = inspect(db.engine)
        _, still_missing = collect_changes(insp2)
        print("\n結果:", "OK（モデル定義と一致しました）" if not still_missing
              else "★まだ不足があります: {}".format(still_missing))


if __name__ == "__main__":
    main()
