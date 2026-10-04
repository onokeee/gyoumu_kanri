/* 絞り込みフォームの自動送信(共通)。
 *
 * 使い方: <form method="get" class="auto-filter"> にすると、
 * 中のチェックボックス・選択・入力欄が変わった時点で自動送信され、
 * 「絞り込み」ボタンを押さなくても結果が更新される。
 *
 * テキスト入力は change(Enter または フォーカスを外したとき)で反映する。
 * 1文字ごとに再読み込みすると入力しづらいため、意図的に input では送信しない。
 *
 * JavaScript が無効な環境では <noscript> の送信ボタンが表示され、従来どおり操作できる。
 */
(function () {
  "use strict";

  function setup(form) {
    // change はバブリングするのでフォームで一括して拾う
    form.addEventListener("change", function (event) {
      var el = event.target;
      if (el && el.matches("input, select, textarea")) {
        form.submit();
      }
    });
  }

  function init() {
    document.querySelectorAll("form.auto-filter").forEach(setup);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
