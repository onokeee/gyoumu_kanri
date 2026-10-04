"""本番用の起動スクリプト(waitress)。

    python serve.py
    -> メンバーは http://(サーバーのIPアドレス):8050 でアクセス

・以前の「waitress-serve --host=0.0.0.0 --port=8050 --call app:create_app」の代わりに使う。
・待ち受けのアドレス・ポートは instance/config.py の SERVER_HOST / SERVER_PORT。
・定期メール(週報・期限超過通知)の自動送信スケジューラを起動するのは、このスクリプトだけ。
  開発用の run.py や seed.py・migrate.py では自動送信は行われない。
"""
from waitress import serve

from app import create_app
from app.scheduler import start_scheduler


def main():
    app = create_app()
    start_scheduler(app)
    host = str(app.config.get("SERVER_HOST") or "0.0.0.0")
    port = int(app.config.get("SERVER_PORT") or 8050)
    print("定期メール（週報・期限超過通知）の自動送信スケジューラを起動しました。", flush=True)
    serve(app, host=host, port=port)


if __name__ == "__main__":
    main()
