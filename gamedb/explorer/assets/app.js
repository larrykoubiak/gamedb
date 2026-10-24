const state = {
  systems: [],
  selectedSystem: null,
  page: 1,
  pageSize: 100,
  query: "",
  requestId: 0,
  releaseDetails: new Map(),
  softwareFacts: new Map(),
  correction: null,
  targetRequestId: 0,
  correctionsEnabled: false,
};

const tree = document.querySelector("#system-tree");
const filter = document.querySelector("#system-filter");
const tableWrap = document.querySelector("#game-table-wrap");
const tableBody = document.querySelector("#game-table-body");
const empty = document.querySelector("#game-empty");
const pagination = document.querySelector("#pagination");
const gameFilter = document.querySelector("#game-filter");

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const body = await response.text();
  let payload;
  try {
    payload = JSON.parse(body);
  } catch (error) {
    throw new Error(
      response.ok
        ? "Explorer returned an invalid response. Reload the page and try again."
        : `Explorer request failed: ${response.status}`
    );
  }
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

function appendArcadeStatus(parent, arcade) {
  if (!arcade) return;
  const status = document.createElement("div");
  const issueLabels = {
    undumped: "DAT lists undumped components",
    missing_sample_inventory: "Sample packaging not implemented",
    missing_sample_definition: "Sample definition missing",
    missing_hdd_definition: "HDD packaging not implemented",
    missing_inventory: "Inventory file missing",
    missing_hash: "Definition lacks a required hash",
  };
  const issues = (arcade.issues || []).map(reason => issueLabels[reason] || reason);
  const readiness = arcade.complete ? "Complete package" : (issues.join(" · ") || "Package unavailable");
  status.textContent = `${readiness} · ${arcade.emulationStatus}`;
  parent.append(status);
  const cores = (arcade.compatibleEmulators || []).map(item => item.name);
  if (cores.length) {
    const compatible = document.createElement("div");
    compatible.textContent = `DAT validated: ${cores.join(", ")}`;
    parent.append(compatible);
  }
}

function scoreText(score) {
  return score > 0 ? `+${score}` : String(score);
}

function mediaUrl(path) {
  return `/media/${path.split("/").map(encodeURIComponent).join("/")}`;
}

function artworkCell(game) {
  const element = document.createElement("td");
  element.className = "art-cell";
  const candidates = ["boxart", "title", "snap", "logo"]
    .map(kind => game.media?.[kind])
    .filter(Boolean);
  if (!candidates.length) {
    const placeholder = document.createElement("span");
    placeholder.className = "art-placeholder";
    placeholder.textContent = "—";
    element.append(placeholder);
    return element;
  }
  const image = document.createElement("img");
  image.className = "game-art";
  image.alt = "";
  image.loading = "lazy";
  image.decoding = "async";
  let index = 0;
  image.src = mediaUrl(candidates[index].path);
  image.addEventListener("error", () => {
    index += 1;
    if (index < candidates.length) image.src = mediaUrl(candidates[index].path);
    else image.remove();
  });
  element.append(image);
  return element;
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

function renderArtworkGallery(container, media, title) {
  const available = [
    ["boxart", "Box art"],
    ["title", "Title screen"],
    ["snap", "Gameplay"],
    ["logo", "Logo"],
  ].filter(([kind]) => media?.[kind]);
  if (!available.length) return;

  const gallery = document.createElement("section");
  gallery.className = "art-gallery";
  gallery.setAttribute("aria-label", `Artwork for ${title}`);
  for (const [kind, label] of available) {
    const item = media[kind];
    const figure = document.createElement("figure");
    const link = document.createElement("a");
    link.href = mediaUrl(item.path);
    link.target = "_blank";
    link.rel = "noopener";
    const image = document.createElement("img");
    image.src = link.href;
    image.alt = `${title} — ${label}`;
    image.loading = "lazy";
    link.append(image);
    const caption = document.createElement("figcaption");
    caption.textContent = `${label} · ${item.matchBasis.replaceAll("_", " ")} · region ${item.regionMatch}`;
    figure.append(link, caption);
    gallery.append(figure);
  }
  container.append(gallery);
}

function renderSoftwareFacts(container, facts) {
  const section = document.createElement("section");
  section.className = "software-facts";
  const heading = document.createElement("div");
  heading.className = "release-detail-heading";
  heading.textContent = "Software metadata";
  section.append(heading);

  if (!facts.length) {
    const missing = document.createElement("p");
    missing.className = "software-facts-empty";
    missing.textContent = "No unambiguous exact-SHA-1 Libretro metadata match.";
    section.append(missing);
    container.append(section);
    return;
  }

  const labels = {
    description: "Description",
    developer: "Developer",
    publisher: "Publisher",
    genre: "Genre",
    franchise: "Franchise",
    player_count: "Players",
    rumble: "Rumble",
    analog: "Analog",
    enhancement_hardware: "Enhancement hardware",
    tags: "Tags",
    origin: "Origin",
  };
  const grid = document.createElement("dl");
  grid.className = "software-fact-grid";
  for (const fact of facts) {
    const term = document.createElement("dt");
    term.textContent = labels[fact.key] || fact.key.replaceAll("_", " ");
    const definition = document.createElement("dd");
    for (const candidate of fact.values) {
      const item = document.createElement("div");
      item.className = "software-fact-value";
      if (candidate.candidateCount > 1) item.classList.add("conflicted");
      const value = document.createElement("span");
      value.className = "software-fact-text";
      value.textContent = candidate.value;
      item.append(value);
      if (candidate.candidateCount > 1) {
        const rank = document.createElement("span");
        rank.className = "fact-rank-badge";
        rank.textContent = `candidate ${candidate.rank}/${candidate.candidateCount}`;
        item.append(rank);
      }
      const evidence = document.createElement("span");
      evidence.className = "software-fact-evidence";
      const contentLabel = candidate.matchedContentCount === 1 ? "content hash" : "content hashes";
      const recordLabel = candidate.sourceRecordCount === 1 ? "RDB row" : "RDB rows";
      const databases = candidate.sourceDatabases.length
        ? ` · ${candidate.sourceDatabases.join(", ")}`
        : "";
      evidence.textContent = `${candidate.matchedContentCount} ${contentLabel} · ${candidate.sourceRecordCount} ${recordLabel}${databases}`;
      evidence.title = `${candidate.sourceProvider} revision ${candidate.sourceRevision}`;
      item.append(evidence);
      definition.append(item);
    }
    grid.append(term, definition);
  }
  section.append(grid);
  container.append(section);
}

function renderReleaseDetails(container, releases, facts, softwareId, media, title) {
  container.replaceChildren();
  renderArtworkGallery(container, media, title);
  renderSoftwareFacts(container, facts);
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
  for (const label of ["Result", "Source title", "Packages and hashes", "Facts", "Score", "Correction"]) {
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
    const sourceTitle = cell(release.sourceTitle, "release-title-cell");
    const identity = document.createElement("span");
    identity.className = "cell-note";
    const identityLabels = {
      exact_sha1: "Exact historical SHA-1",
      parent_clone: "Parent/Clone relationship",
      anchored_title: "Inherited from unique title anchor",
      translation_original_title: "Original title from translation member",
      manual_override: "Maintained manual override",
      manual_correction: "Working or promoted correction",
      title_fallback: "Grouped by title",
    };
    identity.textContent = identityLabels[release.assignmentBasis] || release.assignmentBasis;
    sourceTitle.append(identity);
    row.append(result, sourceTitle);

    const packages = document.createElement("td");
    packages.className = "packages-cell";
    for (const pkg of release.packages) {
      const packageBlock = document.createElement("div");
      packageBlock.className = "package-block";
      const archive = document.createElement("div");
      archive.className = "package-name";
      archive.textContent = `${pkg.sourceCollection} · ${pkg.archiveName}`;
      packageBlock.append(archive);
      const path = document.createElement("div");
      path.className = "source-path";
      path.textContent = pkg.resolvedPath || pkg.sourcePath || "Source path unavailable";
      packageBlock.append(path);
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
        name.textContent = `${file.memberPath || file.name} · ${size} bytes`;
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
    appendArcadeStatus(facts, release.arcade);
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
    if (release.arcade) explanation.append("Completeness and emulation status rank before preference score.");
    score.append(explanation);
    row.append(score);

    const correction = document.createElement("td");
    if (state.correctionsEnabled && release.releaseContentSignature) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "correction-button";
      button.textContent = "Correct…";
      button.addEventListener("click", () => openCorrectionDialog(release, softwareId));
      correction.append(button);
    } else if (state.correctionsEnabled) {
      correction.textContent = "No complete signature";
      correction.className = "cell-note";
    }
    row.append(correction);
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
  container.textContent = "Loading software metadata, ranked releases and hashes…";
  try {
    let releases = state.releaseDetails.get(game.softwareId);
    let facts = state.softwareFacts.get(game.softwareId);
    if (!releases || !facts) {
      [releases, facts] = await Promise.all([
        releases || requestJson(`/api/software/${game.softwareId}/releases`),
        facts || requestJson(`/api/software/${game.softwareId}/facts`),
      ]);
      state.releaseDetails.set(game.softwareId, releases);
      state.softwareFacts.set(game.softwareId, facts);
    }
    renderReleaseDetails(container, releases, facts, game.softwareId, game.media, game.title);
    detailRow.dataset.loaded = "true";
  } catch (error) {
    container.className = "release-details error-row";
    container.textContent = error.message;
  }
}

const correctionDialog = document.querySelector("#correction-dialog");
const correctionForm = document.querySelector("#correction-form");
const correctionTargetPanel = document.querySelector("#correction-target-panel");
const correctionTargetFilter = document.querySelector("#correction-target-filter");
const correctionTargets = document.querySelector("#correction-targets");
const correctionStatus = document.querySelector("#correction-status");

function openCorrectionDialog(release, softwareId) {
  state.correction = { release, softwareId, target: null };
  document.querySelector("#correction-subject").textContent = release.sourceTitle;
  document.querySelector("#correction-signature").textContent = release.releaseContentSignature;
  document.querySelector("#correction-note").value = "";
  correctionTargetFilter.value = "";
  correctionTargets.textContent = "Type a title to search.";
  correctionStatus.textContent = "";
  correctionForm.elements["correction-action"].value = "assign";
  correctionTargetPanel.hidden = false;
  document.querySelector("#correction-save").disabled = false;
  correctionDialog.showModal();
  correctionTargetFilter.focus();
}

function renderCorrectionTargets(targets) {
  correctionTargets.replaceChildren();
  if (!targets.length) {
    correctionTargets.textContent = "No matching software with a complete signature.";
    return;
  }
  for (const target of targets) {
    const label = document.createElement("label");
    label.className = "correction-target";
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "correction-target";
    radio.value = target.targetContentSignature;
    radio.addEventListener("change", () => { state.correction.target = target; });
    const text = document.createElement("span");
    const title = document.createElement("strong");
    title.textContent = target.displayName;
    const detail = document.createElement("small");
    detail.textContent = `${target.releaseCount} release${target.releaseCount === 1 ? "" : "s"} · ${target.identityBasis}`;
    text.append(title, detail);
    label.append(radio, text);
    correctionTargets.append(label);
  }
}

let correctionSearchTimer;
correctionTargetFilter.addEventListener("input", () => {
  clearTimeout(correctionSearchTimer);
  state.correction.target = null;
  const query = correctionTargetFilter.value.trim();
  if (!query) {
    correctionTargets.textContent = "Type a title to search.";
    return;
  }
  correctionTargets.textContent = "Searching…";
  const requestId = ++state.targetRequestId;
  correctionSearchTimer = setTimeout(async () => {
    try {
      const targets = await requestJson(
        `/api/systems/${state.selectedSystem.id}/correction-targets?exclude_software_id=${state.correction.softwareId}&q=${encodeURIComponent(query)}`
      );
      if (requestId === state.targetRequestId) renderCorrectionTargets(targets);
    } catch (error) {
      if (requestId === state.targetRequestId) correctionTargets.textContent = error.message;
    }
  }, 250);
});

for (const radio of correctionForm.elements["correction-action"]) {
  radio.addEventListener("change", () => {
    if (radio.checked) correctionTargetPanel.hidden = radio.value !== "assign";
  });
}

correctionForm.addEventListener("submit", async event => {
  event.preventDefault();
  const action = correctionForm.elements["correction-action"].value;
  if (action === "assign" && !state.correction.target) {
    correctionStatus.textContent = "Choose a target software.";
    return;
  }
  const save = document.querySelector("#correction-save");
  save.disabled = true;
  correctionStatus.textContent = "Saving correction and rebuilding software…";
  try {
    await requestJson("/api/software-corrections", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        systemId: state.selectedSystem.id,
        subjectContentSignature: state.correction.release.releaseContentSignature,
        action,
        targetContentSignature: action === "assign" ? state.correction.target.targetContentSignature : null,
        note: document.querySelector("#correction-note").value,
      }),
    });
    correctionDialog.close();
    state.releaseDetails.clear();
    state.softwareFacts.clear();
    await selectSystem(state.selectedSystem, state.page);
  } catch (error) {
    correctionStatus.textContent = error.message;
    save.disabled = false;
  }
});

document.querySelector("#correction-close").addEventListener("click", () => correctionDialog.close());
document.querySelector("#correction-cancel").addEventListener("click", () => correctionDialog.close());

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
    row.append(expandCell, artworkCell(game));
    const titleCell = cell(game.title, "title-cell");
    const identity = document.createElement("span");
    identity.className = "cell-note";
    const identityLabels = {
      recovered_legacy: "Recovered identity · exact SHA-1 anchor",
      parent_clone: "Recovered identity · Parent/Clone",
      manual: "Maintained manual identity",
      title_fallback: "Grouped by title",
    };
    identity.textContent = identityLabels[game.identityBasis] || game.identityBasis;
    titleCell.append(identity);
    row.append(titleCell);

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
    appendArcadeStatus(sourceCell, game.arcade);
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
    if (game.arcade) details.append("Completeness and emulation status rank before preference score.");
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
    detailCell.colSpan = 12;
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
    ? `${payload.total.toLocaleString()} matching software titles · preferred release per software`
    : `${state.selectedSystem.gameCount.toLocaleString()} software titles · preferred release per software`;
}

async function selectSystem(system, page = 1) {
  state.selectedSystem = system;
  state.page = page;
  const requestId = ++state.requestId;
  renderTree(filter.value);
  document.querySelector("#manufacturer-name").textContent = system.manufacturer;
  document.querySelector("#system-name").textContent = system.name;
  document.querySelector("#system-summary").textContent = `${system.gameCount.toLocaleString()} software titles · preferred release per software`;
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
    const [systems, capabilities] = await Promise.all([
      requestJson("/api/systems"),
      requestJson("/api/capabilities"),
    ]);
    state.systems = systems;
    state.correctionsEnabled = Boolean(capabilities.softwareCorrections);
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
