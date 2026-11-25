const matrix = document.querySelector(".system-matrix");

fetch("/api/capabilities")
  .then(response => response.ok ? response.json() : {})
  .then(capabilities => {
    for (const link of matrix.querySelectorAll(".catalog-card")) {
      const platform = link.pathname.split("/").at(-1);
      link.hidden = capabilities[`${platform}Retail`] === false;
    }
    for (const row of matrix.tBodies[0].rows) {
      row.hidden = !row.querySelector(".catalog-card:not([hidden])");
    }
    matrix.hidden = !matrix.querySelector(".catalog-card:not([hidden])");
    document.querySelector("#no-retail-catalogs").hidden = !matrix.hidden;
  })
  .catch(() => {
    // The links remain usable when the availability check fails.
  });
