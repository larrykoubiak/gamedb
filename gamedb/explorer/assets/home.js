const catalogSections = document.querySelectorAll(".catalog-section");
const visibleCard = ".catalog-card:not([hidden])";

function showCatalogs(capabilities = {}) {
  let total = 0;
  for (const section of catalogSections) {
    const matrix = section.querySelector(".system-matrix");
    for (const link of matrix.querySelectorAll(".catalog-card")) {
      const platform = link.pathname.split("/").at(-1);
      link.hidden = capabilities[`${platform}Retail`] === false;
    }
    const rows = Array.from(matrix.tBodies[0].rows);
    for (const row of rows) row.hidden = !row.querySelector(visibleCard);

    const header = matrix.tHead.rows[0];
    const columns = matrix.querySelectorAll("col");
    for (let index = 1; index < header.cells.length; index++) {
      const empty = !rows.some(row => row.cells[index].querySelector(visibleCard));
      header.cells[index].hidden = empty;
      columns[index].hidden = empty;
      for (const row of rows) row.cells[index].hidden = empty;
    }

    const available = matrix.querySelectorAll(visibleCard).length;
    const count = section.querySelector(".catalog-count");
    count.textContent = `${available} ${available === 1 ? "system" : "systems"}`;
    count.hidden = false;
    section.hidden = available === 0;
    total += available;
  }
  document.querySelector("#no-retail-catalogs").hidden = total > 0;
}

showCatalogs();
fetch("/api/capabilities")
  .then(response => response.ok ? response.json() : {})
  .then(showCatalogs)
  .catch(() => {});
