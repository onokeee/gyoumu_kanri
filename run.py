"""開発用の起動スクリプト(Flask開発サーバー)。

【開発・動作確認(自分のPC)】
    python run.py
    -> http://127.0.0.1:8050 をブラウザで開く(ポートは instance/config.py の SERVER_PORT)
    ※定期メール(週報・期限超過通知)の自動送信は行われない(画面からの手動送信は使える)

【本番(サーバーとして他PCから接続させる場合)】
    python serve.py
    -> waitress で起動し、定期メールの自動送信も行う(serve.py を参照)
"""
import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    # host=0.0.0.0 にすると同一ネットワーク(LAN)内の他PCからもアクセス可能
    # instance/ (システム設定の画面から保存する instance/config.py など)の変更では
    # 自動再起動しない(再起動が必要な項目は、本番と同じく手動の再起動で反映する)
    app.run(host="0.0.0.0", port=int(app.config.get("SERVER_PORT") or 8050), debug=True,
            exclude_patterns=[os.path.join(app.instance_path, "*")])
