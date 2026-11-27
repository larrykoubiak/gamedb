const catalogSections = document.querySelectorAll(".catalog-section");
const visibleCard = ".catalog-card:not([hidden])";

function showCatalogs(capabilities = {}) {
  let totalRetail = 0;
  for (const section of catalogSections) {
    const matrix = section.querySelector(".system-matrix");
    let retail = 0;
    let archive = 0;
    for (const link of matrix.querySelectorAll(".catalog-card")) {
      const platform = link.dataset.catalog || link.pathname.split("/").at(-1);
      const published = capabilities[`${platform}Retail`] !== false;
      const archiveUrl = link.dataset.archive;
      link.hidden = !published && !archiveUrl;
      if (archiveUrl) {
        link.href = published ? `/catalog/${platform}` : archiveUrl;
        archive += Number(!published);
      }
      retail += Number(published);
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

    const count = section.querySelector(".catalog-count");
    count.textContent = section.classList.contains("handheld-section")
      ? [
          retail && `${retail} V2 ${retail === 1 ? "catalog" : "catalogs"}`,
          archive && `${archive} V1 ${archive === 1 ? "library" : "libraries"}`,
        ].filter(Boolean).join(" · ")
      : `${retail} ${retail === 1 ? "system" : "systems"}`;
    count.hidden = false;
    section.hidden = retail + archive === 0;
    totalRetail += retail;
  }
  document.querySelector("#no-retail-catalogs").hidden = totalRetail > 0;
}

showCatalogs();
fetch("/api/capabilities")
  .then(response => response.ok ? response.json() : {})
  .then(showCatalogs)
  .catch(() => {});
