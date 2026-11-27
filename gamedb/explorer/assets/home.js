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
  let handheldRetail = 0;
  let handheldArchive = 0;
  for (const link of document.querySelectorAll(".handheld-grid .catalog-card")) {
    const platform = link.dataset.catalog;
    const published = capabilities[`${platform}Retail`] !== false;
    link.href = published ? `/catalog/${platform}` : link.dataset.archive;
    handheldRetail += Number(published);
    handheldArchive += Number(!published);
  }
  const count = document.querySelector(".handheld-section .catalog-count");
  count.textContent = [
    handheldRetail && `${handheldRetail} V2 ${handheldRetail === 1 ? "catalog" : "catalogs"}`,
    handheldArchive && `${handheldArchive} V1 ${handheldArchive === 1 ? "library" : "libraries"}`,
  ].filter(Boolean).join(" · ");
  count.hidden = false;
  document.querySelector("#no-retail-catalogs").hidden = total + handheldRetail > 0;
}

showCatalogs();
fetch("/api/capabilities")
  .then(response => response.ok ? response.json() : {})
  .then(showCatalogs)
  .catch(() => {});
