/* スキルテスト(受験画面)。
 *
 * 一覧画面: <form class="skilltest-start" data-confirm="確認文"> の送信前に確認し、
 *           「問題を準備しています」の表示(#skilltestOverlay)を出す(AIで問題を作る間の待ち)。
 *
 * 出題画面(.skilltest-question):
 *   ・残り時間の表示(data-remaining 秒から数える)。0 になったら、その時点の選択で自動送信する
 *     (時間はサーバーで計っているので、ここでの表示は目安。再読み込みしても戻らない)
 *   ・ほかのタブ/ウィンドウへの切り替え(visibilitychange / blur)を data-blur-url に送って記録する
 *     (再読み込み・リンクでの画面遷移は数えない)
 *   ・問題文の選択・コピー・右クリックを抑止する(軽い対策。完全には防げない)
 *   ・二重送信の防止
 */
(function () {
  "use strict";

  function setupStartForms() {
    var overlay = document.getElementById("skilltestOverlay");
    document.querySelectorAll("form.skilltest-start").forEach(function (form) {
      form.addEventListener("submit", function (event) {
        if (form.dataset.sending === "1") {
          event.preventDefault();
          return;
        }
        var message = form.dataset.confirm;
        if (message && !window.confirm(message)) {
          event.preventDefault();
          return;
        }
        form.dataset.sending = "1";
        if (overlay) overlay.classList.remove("d-none");
        // ほかの「受験する」も押せないようにする(送信そのものは止めない)
        window.setTimeout(function () {
          document.querySelectorAll("form.skilltest-start button").forEach(function (b) {
            b.disabled = true;
          });
        }, 0);
      });
    });
    // 戻るボタンで一覧に戻ったときに待ち表示が残らないようにする
    window.addEventListener("pageshow", function () {
      if (overlay) overlay.classList.add("d-none");
      document.querySelectorAll("form.skilltest-start").forEach(function (form) {
        form.dataset.sending = "";
        form.querySelectorAll("button").forEach(function (b) {
          b.disabled = false;
        });
      });
    });
  }

  function format(sec) {
    var m = Math.floor(sec / 60);
    var s = sec % 60;
    return m + ":" + (s < 10 ? "0" : "") + s;
  }

  function setupQuestion(root) {
    var form = document.getElementById("skilltestAnswerForm");
    var timer = document.getElementById("skilltestTimer");
    var button = document.getElementById("skilltestSubmit");
    var blurNote = document.getElementById("skilltestBlurNote");
    var blurCount = document.getElementById("skilltestBlurCount");
    var remaining = parseInt(root.dataset.remaining, 10);
    if (isNaN(remaining) || remaining < 0) remaining = 0;
    var endAt = Date.now() + remaining * 1000;
    var submitting = false;
    var away = false;
    var reported = 0;

    function lock() {
      submitting = true;
      window.setTimeout(function () {
        if (button) button.disabled = true;
      }, 0);
    }

    // 時間切れ: その時点の選択で送信する(未選択なら時間切れとして記録される)
    function autoSubmit() {
      if (submitting || !form) return;
      lock();
      form.submit();
    }

    if (form) {
      form.addEventListener("submit", function (event) {
        if (submitting) {
          event.preventDefault();
          return;
        }
        lock();
      });
    }

    function tick() {
      var left = Math.max(0, Math.ceil((endAt - Date.now()) / 1000));
      if (timer) {
        timer.textContent = format(left);
        timer.classList.toggle("text-danger", left <= 10);
      }
      if (left <= 0) {
        autoSubmit();
        return;
      }
      window.setTimeout(tick, 250);
    }
    tick();

    // 画面から離れたことを記録する(タブ・ウィンドウの切り替え)。
    // 再読み込み・リンクでの画面遷移でもページを閉じる時に visibilitychange(hidden) が起きるため、
    // すぐには送らず少し待ち、その間にページを閉じた(pagehide)ら送らない
    // (閉じられたページでは待ちの処理は実行されない)。送信中(回答・自動送信)も数えない。
    var BLUR_DELAY_MS = 300;
    var leaving = false;
    var pending = null;

    function send() {
      pending = null;
      if (submitting || leaving) return;
      reported += 1;
      if (blurNote) blurNote.classList.remove("d-none");
      if (blurCount) blurCount.textContent = String(reported);
      var url = root.dataset.blurUrl;
      if (!url) return;
      var data = new FormData();
      data.append("seq", root.dataset.seq || "");
      try {
        if (navigator.sendBeacon && navigator.sendBeacon(url, data)) return;
      } catch (e) {
        /* sendBeacon が使えなければ fetch で送る */
      }
      if (window.fetch) {
        window.fetch(url, { method: "POST", body: data, credentials: "same-origin", keepalive: true })
          .catch(function () {});
      }
    }
    function report() {
      if (submitting || leaving || away) return;
      away = true;
      if (pending === null) pending = window.setTimeout(send, BLUR_DELAY_MS);
    }
    function back() {
      away = false;
    }
    function leave() {
      leaving = true;
      if (pending !== null) {
        window.clearTimeout(pending);
        pending = null;
      }
    }
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) report();
      else back();
    });
    window.addEventListener("blur", report);
    window.addEventListener("focus", back);
    window.addEventListener("pagehide", leave);
    // 戻る・進むボタンでページが復元された場合は、再び記録する
    window.addEventListener("pageshow", function () {
      leaving = false;
      away = false;
    });

    // 問題文・選択肢の選択・コピー・右クリックを抑止する(軽い対策)
    root.querySelectorAll(".skilltest-noselect").forEach(function (area) {
      ["copy", "cut", "contextmenu", "dragstart", "selectstart"].forEach(function (name) {
        area.addEventListener(name, function (event) {
          event.preventDefault();
        });
      });
    });
    document.addEventListener("keydown", function (event) {
      var key = (event.key || "").toLowerCase();
      if ((event.ctrlKey || event.metaKey) && (key === "c" || key === "x" || key === "p" || key === "s")) {
        event.preventDefault();
      }
    });
  }

  function init() {
    setupStartForms();
    var root = document.querySelector(".skilltest-question");
    if (root) setupQuestion(root);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
