/* 表の並び替え(共通)。
 *
 * 使い方: <table class="table sortable"> にして、ヘッダに
 *   <th data-type="num">…</th>   … 数値として並び替え(既定は文字列)
 *   <th data-nosort>…</th>       … 並び替え対象外
 * を付ける。セルの表示と並び替えキーが違う場合は <td data-sort="キー"> を指定する。
 *
 * 画面に出ている行をその場で並び替えるだけなので、絞り込み条件はそのまま保持される。
 */
(function () {
  "use strict";

  function keyOf(row, index) {
    var td = row.cells[index];
    if (!td) return "";
    var v = td.dataset.sort !== undefined ? td.dataset.sort : td.textContent;
    return (v || "").trim();
  }

  function isEmpty(v) {
    return v === "" || v === "―" || v === "-";
  }

  function toNumber(v) {
    var n = parseFloat(v.replace(/[^0-9.\-]/g, ""));
    return isNaN(n) ? 0 : n;
  }

  /* 並び替え対象の行(「該当なし」等の colspan 行は除く) */
  function dataRows(tbody) {
    return Array.prototype.filter.call(tbody.rows, function (r) {
      return !Array.prototype.some.call(r.cells, function (c) {
        return c.colSpan > 1;
      });
    });
  }

  function sortBy(table, index, type, dir) {
    var tbody = table.tBodies[0];
    var rows = dataRows(tbody);
    rows.sort(function (r1, r2) {
      var a = keyOf(r1, index);
      var b = keyOf(r2, index);
      var ea = isEmpty(a);
      var eb = isEmpty(b);
      // 空欄は方向によらず常に最後
      if (ea || eb) return ea && eb ? 0 : ea ? 1 : -1;
      var c = type === "num" ? toNumber(a) - toNumber(b) : a.localeCompare(b, "ja");
      return c * dir;
    });
    rows.forEach(function (r) {
      tbody.appendChild(r);
    });
  }

  function setup(table) {
    var thead = table.tHead;
    if (!thead || !thead.rows.length || !table.tBodies.length) return;
    var headRow = thead.rows[0];

    Array.prototype.forEach.call(headRow.cells, function (th, index) {
      if (th.dataset.nosort !== undefined) return;
      th.classList.add("sortable-th");
      th.title = "クリックで並び替え";

      var ind = document.createElement("span");
      ind.className = "sort-ind";
      th.appendChild(ind);

      th.addEventListener("click", function () {
        var dir = th.dataset.dir === "asc" ? -1 : 1;

        // 他の列の状態表示をリセット
        Array.prototype.forEach.call(headRow.cells, function (other) {
          if (other === th) return;
          delete other.dataset.dir;
          var oi = other.querySelector(".sort-ind");
          if (oi) oi.textContent = "";
        });

        th.dataset.dir = dir === 1 ? "asc" : "desc";
        ind.textContent = dir === 1 ? " ▲" : " ▼";
        sortBy(table, index, th.dataset.type || "text", dir);
      });
    });
  }

  function init() {
    document.querySelectorAll("table.sortable").forEach(setup);
  }

  // 読み込み途中なら DOMContentLoaded を待ち、既に読み込み済みなら即実行する
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
