"use client";

import { useEffect } from "react";

function parseSortValue(raw: string): { numeric: number | null; text: string } {
  const text = String(raw ?? "").trim();
  const normalizedText = text.replace(/\s+/g, " ");
  const compact = normalizedText.replace(/,/g, "").replace(/%/g, "").trim();
  const numericCandidate = compact.startsWith("(") && compact.endsWith(")")
    ? `-${compact.slice(1, -1)}`
    : compact;
  const numeric = /^[+-]?\d*\.?\d+$/.test(numericCandidate)
    ? Number(numericCandidate)
    : Number.NaN;
  return {
    numeric: Number.isFinite(numeric) ? numeric : null,
    text: normalizedText.toLowerCase(),
  };
}

function sortTableByColumn(table: HTMLTableElement, columnIndex: number): void {
  const tbody = table.tBodies?.[0];
  if (!tbody) {
    return;
  }
  const rows = Array.from(tbody.rows);
  if (rows.length <= 1) {
    return;
  }

  const currentCol = Number(table.dataset.sortCol ?? "-1");
  const currentDir = (table.dataset.sortDir ?? "asc") as "asc" | "desc";
  const nextDir: "asc" | "desc" = currentCol === columnIndex && currentDir === "asc" ? "desc" : "asc";

  const sortableRows = rows.filter((row) => row.cells.length > columnIndex);
  sortableRows.sort((left, right) => {
    const leftCell = left.cells[columnIndex];
    const rightCell = right.cells[columnIndex];
    const leftRaw = leftCell.getAttribute("data-sort-value") ?? leftCell.textContent ?? "";
    const rightRaw = rightCell.getAttribute("data-sort-value") ?? rightCell.textContent ?? "";
    const leftValue = parseSortValue(leftRaw);
    const rightValue = parseSortValue(rightRaw);

    let cmp = 0;
    if (leftValue.numeric !== null && rightValue.numeric !== null) {
      cmp = leftValue.numeric - rightValue.numeric;
    } else {
      cmp = leftValue.text.localeCompare(rightValue.text);
    }
    return nextDir === "asc" ? cmp : -cmp;
  });

  for (const row of sortableRows) {
    tbody.appendChild(row);
  }

  table.dataset.sortCol = String(columnIndex);
  table.dataset.sortDir = nextDir;

  const headerRow = table.tHead?.rows?.[0];
  if (headerRow) {
    Array.from(headerRow.cells).forEach((cell, index) => {
      if (!(cell instanceof HTMLTableCellElement)) {
        return;
      }
      if (index === columnIndex) {
        cell.setAttribute("aria-sort", nextDir === "asc" ? "ascending" : "descending");
      } else {
        cell.setAttribute("aria-sort", "none");
      }
    });
  }
}

export default function TableEnhancer() {
  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null;
      if (!target) {
        return;
      }
      const th = target.closest("th");
      if (!(th instanceof HTMLTableCellElement)) {
        return;
      }
      if (!th.closest("thead")) {
        return;
      }

      // Keep explicit React sort buttons untouched.
      if (th.querySelector("button")) {
        return;
      }
      if (th.getAttribute("data-no-sort") === "true") {
        return;
      }

      const tr = th.parentElement;
      if (!(tr instanceof HTMLTableRowElement)) {
        return;
      }
      const table = th.closest("table");
      if (!(table instanceof HTMLTableElement)) {
        return;
      }
      if (!table.tBodies?.[0]) {
        return;
      }
      const columnIndex = Array.from(tr.cells).indexOf(th);
      if (columnIndex < 0) {
        return;
      }

      sortTableByColumn(table, columnIndex);
    };

    document.addEventListener("click", onClick);
    return () => {
      document.removeEventListener("click", onClick);
    };
  }, []);

  return null;
}
