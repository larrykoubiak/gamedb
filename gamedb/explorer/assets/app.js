const state = {
  systems: [],
  selectedSystem: null,
  page: 1,
  pageSize: 100,
  query: "",
  requestId: 0,
  releaseDetails: new Map(),
};

const tree = document.querySelector("#system-tree");
const filter = document.querySelector("#system-filter");
const tableWrap = document.querySelector("#game-table-wrap");
const tableBody = document.querySelector("#game-table-body");
const empty = document.querySelector("#game-empty");
const pagination = document.querySelector("#pagination");
const gameFilter = document.querySelector("#game-filter");

async function requestJson(url) {
  const response = await fetch(url);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `Request failed: ${response.status}`);
  return payload;
}

function groupSystems(systems) {
  return systems.reduce((groups, system) => {
    if (!groups.has(system.manufacturer)) groups.set(system.manufacturer, []);
    groups.get(system.manufacturer).push(system);
    return groups;
  }, new Map());
}

function renderTree(search = "") {
  const normalized = search.trim().toLowerCase();
  const visible = state.systems.filter(system =>
    `${system.manufacturer} ${system.name}`.toLowerCase().includes(normalized)
  );
  const groups = groupSystems(visible);
  tree.replaceChildren();

  for (const [manufacturer, systems] of groups) {
    const details = document.createElement("details");
    details.className = "manufacturer";
    details.open = Boolean(normalized) || systems.some(system => system.id === state.selectedSystem?.id);
    const summary = document.createElement("summary");
    summary.textContent = manufacturer;
    details.append(summary);

    for (const system of systems) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "system-button";
      if (system.id === state.selectedSystem?.id) button.classList.add("active");
      const name = document.createElement("span");
      name.textContent = system.name;
      const count = document.createElement("span");
      count.textContent = system.gameCount.toLocaleString();
      button.append(name, count);
      button.addEventListener("click", () => {
        state.query = "";
        gameFilter.value = "";
        selectSystem(system);
      });
      details.append(button);
    }
    tree.append(details);
  }

  if (!groups.size) {
    const empty = document.createElement("div");
    empty.className = "loading-row";
    empty.textContent = "No matching systems.";
    tree.append(empty);
  }
}

function cell(value, className = "") {
  const element = document.createElement("td");
  element.className = className;
  element.textContent = value;
  return element;
}

function values(values) {
  return values?.length ? values.join(", ") : "—";
}

function scoreText(score) {
  return score > 0 ? `+${score}` : String(score);
}

function appendBreakdown(container, breakdown) {
  const list = document.createElement("ul");
  if (!breakdown?.length) {
    const item = document.createElement("li");
    item.textContent = "No preference rules matched; score is neutral.";
    list.append(item);
  } else {
    for (const reason of breakdown) {
      const item = document.createElement("li");
      const value = reason.matched_value ? ` (${reason.matched_value})` : "";
      item.textContent = `${reason.description}${value}: ${scoreText(reason.score)}`;
      item.className = reason.score >= 0 ? "positive-score" : "negative-score";
      list.append(item);
    }
  }
  container.append(list);
}

function renderReleaseDetails(container, releases) {
  container.replaceChildren();
  const heading = document.createElement("div");
  heading.className = "release-detail-heading";
  heading.textContent = `${releases.length.toLocaleString()} ranked release${releases.length === 1 ? "" : "s"}`;
  container.append(heading);

  const wrap = document.createElement("div");
  wrap.className = "release-table-wrap";
  const table = document.createElement("table");
  table.className = "release-table";
  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (const label of ["Result", "Source title", "Packages and hashes", "Facts", "Score"]) {
    const th = document.createElement("th");
    th.scope = "col";
    th.textContent = label;
    headRow.append(th);
  }
  head.append(headRow);
  table.append(head);
  const body = document.createElement("tbody");

  for (const release of releases) {
    const row = document.createElement("tr");
    if (release.selected) row.className = "selected-release";
    const result = document.createElement("td");
    const resultBadge = document.createElement("span");
    resultBadge.className = release.selected ? "winner-badge" : "rank-badge";
    resultBadge.textContent = release.selected ? "Selected" : `Rank ${release.rank}`;
    result.append(resultBadge);
    row.append(result, cell(release.sourceTitle, "release-title-cell"));

    const packages = document.createElement("td");
    packages.className = "packages-cell";
    for (const pkg of release.packages) {
      const packageBlock = document.createElement("div");
      packageBlock.className = "package-block";
      const archive = document.createElement("div");
      archive.className = "package-name";
      archive.textContent = `${pkg.sourceCollection} · ${pkg.archiveName}`;
      packageBlock.append(archive);
      if (pkg.contentSignature) {
        const signature = document.createElement("div");
        signature.className = "signature-line";
        signature.textContent = `package signature ${pkg.contentSignature}`;
        packageBlock.append(signature);
      }
      for (const file of pkg.files) {
        const fileLine = document.createElement("div");
        fileLine.className = "file-hash";
        const name = document.createElement("span");
        const size = file.size == null ? "?" : file.size.toLocaleString();
        name.textContent = `${file.name} · ${size} bytes`;
        const hash = document.createElement("code");
        hash.textContent = file.sha1 ? `SHA-1 ${file.sha1}` : `CRC ${file.crc || "unknown"}`;
        fileLine.append(name, hash);
        packageBlock.append(fileLine);
      }
      packages.append(packageBlock);
    }
    row.append(packages);

    const facts = document.createElement("td");
    facts.className = "release-facts";
    const factLines = [
      ["region", release.regions],
      ["language", release.languages],
      ["version", release.versions],
      ["revision", release.revisions],
      ["date", release.releaseDates],
      ["dump", [...release.dumpStatuses, ...release.dumpModifications]],
    ];
    for (const [label, factValues] of factLines) {
      if (!factValues.length) continue;
      const line = document.createElement("div");
      line.textContent = `${label}: ${factValues.join(", ")}`;
      facts.append(line);
    }
    if (!facts.childElementCount) facts.textContent = "—";
    row.append(facts);

    const score = document.createElement("td");
    score.className = "release-score-cell";
    const value = document.createElement("span");
    value.className = `score${release.score < 0 ? " negative" : ""}`;
    value.textContent = scoreText(release.score);
    score.append(value);
    const explanation = document.createElement("details");
    explanation.className = "score-details";
    const summary = document.createElement("summary");
    summary.textContent = "Breakdown";
    explanation.append(summary);
    appendBreakdown(explanation, release.breakdown);
    score.append(explanation);
    row.append(score);
    body.append(row);
  }
  table.append(body);
  wrap.append(table);
  container.append(wrap);
}

async function toggleReleaseDetails(game, row, detailRow, button) {
  const opening = detailRow.hidden;
  detailRow.hidden = !opening;
  button.textContent = opening ? "⌄" : "›";
  button.setAttribute("aria-expanded", String(opening));
  row.classList.toggle("expanded", opening);
  if (!opening || detailRow.dataset.loaded) return;

  const container = detailRow.querySelector(".release-details");
  container.textContent = "Loading ranked releases and hashes…";
  try {
    let releases = state.releaseDetails.get(game.titleId);
    if (!releases) {
      releases = await requestJson(`/api/titles/${game.titleId}/releases`);
      state.releaseDetails.set(game.titleId, releases);
    }
    renderReleaseDetails(container, releases);
    detailRow.dataset.loaded = "true";
  } catch (error) {
    container.className = "release-details error-row";
    container.textContent = error.message;
  }
}

function showMessage(message, className = "empty-state") {
  tableWrap.hidden = true;
  tableBody.replaceChildren();
  empty.className = className;
  empty.replaceChildren();
  const text = document.createElement("p");
  text.textContent = message;
  empty.append(text);
  empty.hidden = false;
}

function renderGames(payload) {
  tableBody.replaceChildren();

  for (const game of payload.items) {
    const row = document.createElement("tr");
    row.className = "game-row";
    const expandCell = document.createElement("td");
    expandCell.className = "expand-cell";
    const expand = document.createElement("button");
    expand.type = "button";
    expand.className = "expand-button";
    expand.textContent = "›";
    expand.setAttribute("aria-label", `Show all ranked releases for ${game.title}`);
    expand.setAttribute("aria-expanded", "false");
    expandCell.append(expand);
    row.append(expandCell);
    row.append(cell(game.title, "title-cell"));

    const archive = cell(game.archiveName || "No package name", "archive-cell");
    if (game.packageCount > 1) {
      const packages = document.createElement("span");
      packages.className = "cell-note";
      packages.textContent = `${game.packageCount} packages on this release`;
      archive.append(packages);
    }
    row.append(
      archive,
      cell(values(game.regions), "cell-values"),
      cell(values(game.languages), "cell-values"),
      cell(values(game.revisions), "cell-values"),
      cell(values(game.releaseDates), "cell-values"),
      cell(values([...game.dumpStatuses, ...game.dumpModifications]), "cell-values"),
    );

    const sourceCell = document.createElement("td");
    const source = document.createElement("span");
    source.className = "source-badge";
    source.textContent = game.sourceCollection || "Unknown";
    sourceCell.append(source);
    row.append(sourceCell);

    const scoreCell = document.createElement("td");
    scoreCell.className = "score-cell";
    const score = document.createElement("span");
    score.className = "score";
    score.textContent = scoreText(game.score);
    if (game.score < 0) score.classList.add("negative");
    scoreCell.append(score);

    const details = document.createElement("details");
    details.className = "score-details";
    const summary = document.createElement("summary");
    summary.textContent = "Breakdown";
    details.append(summary);
    appendBreakdown(details, game.breakdown);
    scoreCell.append(details);
    row.append(scoreCell);

    const choice = document.createElement("td");
    if (game.tieBroken) {
      const tie = document.createElement("span");
      tie.className = "tie-badge";
      tie.textContent = `${game.topScoreTieCount} tied`;
      tie.title = "The displayed release was selected deterministically from equal top scores.";
      choice.append(tie);
    } else {
      const unique = document.createElement("span");
      unique.className = "unique-choice";
      unique.textContent = "Unique";
      choice.append(unique);
    }
    row.append(choice);
    const detailRow = document.createElement("tr");
    detailRow.className = "detail-row";
    detailRow.hidden = true;
    const detailCell = document.createElement("td");
    detailCell.colSpan = 11;
    const detailContainer = document.createElement("div");
    detailContainer.className = "release-details";
    detailCell.append(detailContainer);
    detailRow.append(detailCell);
    const toggle = () => toggleReleaseDetails(game, row, detailRow, expand);
    expand.addEventListener("click", toggle);
    row.addEventListener("click", event => {
      if (event.target.closest("button, details")) return;
      toggle();
    });
    tableBody.append(row, detailRow);
  }

  tableWrap.hidden = !payload.items.length;
  empty.hidden = Boolean(payload.items.length);
  if (!payload.items.length) showMessage("No preferred releases found for this system.");

  const pageCount = Math.max(1, Math.ceil(payload.total / payload.pageSize));
  pagination.hidden = payload.total <= payload.pageSize;
  document.querySelector("#page-label").textContent = `Page ${payload.page} of ${pageCount}`;
  document.querySelector("#previous-page").disabled = payload.page <= 1;
  document.querySelector("#next-page").disabled = payload.page >= pageCount;
  document.querySelector("#system-summary").textContent = state.query
    ? `${payload.total.toLocaleString()} matching titles · preferred release per title`
    : `${state.selectedSystem.gameCount.toLocaleString()} title clusters · preferred release per title`;
}

async function selectSystem(system, page = 1) {
  state.selectedSystem = system;
  state.page = page;
  const requestId = ++state.requestId;
  renderTree(filter.value);
  document.querySelector("#manufacturer-name").textContent = system.manufacturer;
  document.querySelector("#system-name").textContent = system.name;
  document.querySelector("#system-summary").textContent = `${system.gameCount.toLocaleString()} title clusters · preferred release per title`;
  gameFilter.disabled = false;
  showMessage("Loading preferred releases…");

  try {
    const query = encodeURIComponent(state.query);
    const payload = await requestJson(`/api/systems/${system.id}/titles?page=${page}&page_size=${state.pageSize}&q=${query}`);
    if (requestId !== state.requestId) return;
    renderGames(payload);
  } catch (error) {
    if (requestId !== state.requestId) return;
    showMessage(error.message, "error-row");
    pagination.hidden = true;
  }
}

filter.addEventListener("input", () => renderTree(filter.value));
document.querySelector("#previous-page").addEventListener("click", () => selectSystem(state.selectedSystem, state.page - 1));
document.querySelector("#next-page").addEventListener("click", () => selectSystem(state.selectedSystem, state.page + 1));

let gameFilterTimer;
gameFilter.addEventListener("input", () => {
  clearTimeout(gameFilterTimer);
  state.query = gameFilter.value.trim();
  gameFilterTimer = setTimeout(() => {
    if (state.selectedSystem) selectSystem(state.selectedSystem, 1);
  }, 250);
});

async function initialize() {
  try {
    state.systems = await requestJson("/api/systems");
    document.querySelector("#system-count").textContent = `${state.systems.length} systems`;
    renderTree();
    if (state.systems.length) selectSystem(state.systems[0]);
  } catch (error) {
    tree.replaceChildren();
    const message = document.createElement("div");
    message.className = "error-row";
    message.textContent = error.message;
    tree.append(message);
  }
}

initialize();
