const state = {
  systems: [],
  systemIcons: {},
  selectedSystem: null,
  page: 1,
  pageSize: 100,
  layout: "tiles",
  results: null,
  query: "",
  requestId: 0,
  releaseDetails: new Map(),
  softwareFacts: new Map(),
  correction: null,
  targetRequestId: 0,
  correctionsEnabled: false,
  vgmEnabled: false,
  metadataFilters: {},
  hideRomHacks: true,
};

const tree = document.querySelector("#system-tree");
const filter = document.querySelector("#system-filter");
const categoryFilter = document.querySelector("#system-category");
const systemBrowserToggle = document.querySelector("#system-browser-toggle");
const tableWrap = document.querySelector("#game-table-wrap");
const tableBody = document.querySelector("#game-table-body");
const gameGrid = document.querySelector("#game-grid");
const empty = document.querySelector("#game-empty");
const pagination = document.querySelector("#pagination");
const gameFilter = document.querySelector("#game-filter");
const metadataFields = {
  genre: "Genre", developer: "Developer", publisher: "Publisher",
  franchise: "Franchise", player_count: "Players",
  enhancement_hardware: "Enhancement hardware", rumble: "Rumble",
  analog: "Analog", origin: "Origin", tags: "Tags",
};
const metadataControls = new Map();

function browseUrl(path) {
  if (!state.hideRomHacks) return path;
  return path + (path.includes("?") ? "&" : "?") + "hide_rom_hacks=1";
}

function setMetadataValue(key, value, selected) {
  const values = new Set(state.metadataFilters[key] || []);
  if (selected) values.add(value);
  else values.delete(value);
  if (values.size) state.metadataFilters[key] = [...values];
  else delete state.metadataFilters[key];
  renderActiveMetadataFilters();
  selectSystem(state.selectedSystem);
}

function renderActiveMetadataFilters() {
  const active = document.querySelector("#active-metadata-filters");
  active.replaceChildren();
  for (const [key, control] of metadataControls) {
    const values = state.metadataFilters[key] || [];
    control.summary.textContent = `${metadataFields[key]}${values.length ? ` (${values.length})` : ""}`;
    control.details.classList.toggle("has-selection", Boolean(values.length));
    for (const checkbox of control.list.querySelectorAll('input[type="checkbox"]')) {
      checkbox.checked = values.includes(checkbox.value);
      checkbox.disabled = !checkbox.checked && values.length >= 25;
    }
    for (const value of values) {
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = `${metadataFields[key]}: ${value} ×`;
      remove.setAttribute("aria-label", `Remove ${metadataFields[key]} filter: ${value}`);
      remove.addEventListener("click", () => setMetadataValue(key, value, false));
      active.append(remove);
    }
  }
  document.querySelector("#clear-metadata-filters").hidden = !Object.keys(state.metadataFilters).length;
}

async function loadMetadataOptions(key) {
  const control = metadataControls.get(key);
  clearTimeout(control.timer);
  const requestId = ++control.requestId;
  control.context = metadataOptionContext(key);
  control.note.textContent = "Loading values…";
  control.list.replaceChildren();
  const params = new URLSearchParams({key, q: state.query,
    search: control.search.value.trim(), filters: JSON.stringify(state.metadataFilters)});
  if (state.selectedSystem) params.set("system_id", state.selectedSystem.id);
  try {
    const payload = await requestJson(browseUrl(`/api/metadata-options?${params}`));
    if (requestId !== control.requestId) return;
    const selected = new Set(state.metadataFilters[key] || []);
    for (const option of payload.items) {
      const label = document.createElement("label");
      label.className = "metadata-option";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.value = option.value;
      checkbox.checked = selected.has(option.value);
      checkbox.disabled = !checkbox.checked && selected.size >= 25;
      checkbox.addEventListener("change", () => setMetadataValue(key, option.value, checkbox.checked));
      const value = document.createElement("span");
      value.textContent = option.value;
      const count = document.createElement("small");
      count.textContent = option.count.toLocaleString();
      label.append(checkbox, value, count);
      control.list.append(label);
    }
    control.note.textContent = !payload.total ? "No matching values."
      : payload.total > payload.items.length ? `First ${payload.items.length} of ${payload.total.toLocaleString()} values. Search to narrow.`
      : "Any selected value matches. Different fields combine.";
  } catch (error) {
    if (requestId === control.requestId) control.note.textContent = error.message;
  }
}

function metadataOptionContext(key) {
  const filters = {...state.metadataFilters};
  delete filters[key];
  return JSON.stringify([state.selectedSystem?.id, state.query, filters, state.hideRomHacks]);
}

function refreshMetadataOptions() {
  for (const [key, control] of metadataControls) {
    if (control.context === metadataOptionContext(key)) continue;
    ++control.requestId;
    if (control.details.open) loadMetadataOptions(key);
  }
}

function initializeMetadataFilters() {
  const container = document.querySelector("#metadata-filters");
  const clearFilters = document.querySelector("#clear-metadata-filters");
  for (const [key, label] of Object.entries(metadataFields)) {
    const details = document.createElement("details");
    details.className = "metadata-filter";
    details.dataset.key = key;
    const summary = document.createElement("summary");
    summary.textContent = label;
    const panel = document.createElement("div");
    panel.className = "metadata-filter-panel";
    const search = document.createElement("input");
    search.type = "search";
    search.className = "metadata-option-search";
    search.placeholder = `Search ${label.toLowerCase()}…`;
    search.setAttribute("aria-label", `Search ${label.toLowerCase()} filter values`);
    const list = document.createElement("div");
    list.className = "metadata-option-list";
    const note = document.createElement("p");
    note.className = "metadata-option-note";
    note.setAttribute("role", "status");
    panel.append(search, list, note);
    details.append(summary, panel);
    const control = {details, summary, search, list, note, requestId: 0, timer: null};
    metadataControls.set(key, control);
    details.addEventListener("toggle", () => {
      if (!details.open) return;
      details.classList.toggle("align-end",
        summary.getBoundingClientRect().left + panel.offsetWidth > window.innerWidth - 16);
      for (const other of metadataControls.values()) {
        if (other !== control) other.details.open = false;
      }
      loadMetadataOptions(key);
    });
    search.addEventListener("input", () => {
      clearTimeout(control.timer);
      ++control.requestId;
      control.timer = setTimeout(() => loadMetadataOptions(key), 250);
    });
    details.addEventListener("keydown", event => {
      if (event.key === "Escape") {
        details.open = false;
        summary.focus();
      }
    });
    container.insertBefore(details, clearFilters);
  }
  document.addEventListener("click", event => {
    for (const control of metadataControls.values()) {
      if (!control.details.contains(event.target)) control.details.open = false;
    }
  });
  clearFilters.addEventListener("click", () => {
    state.metadataFilters = {};
    renderActiveMetadataFilters();
    selectSystem(state.selectedSystem);
  });
}

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

function platformIcon(manufacturer, name) {
  const frame = document.createElement("span");
  frame.className = "platform-icon";
  frame.setAttribute("aria-hidden", "true");
  const fallback = document.createElement("span");
  fallback.className = "platform-icon-fallback";
  fallback.textContent = "◇";
  const icon = state.systemIcons[`${manufacturer}\x1f${name}`];
  if (!icon) {
    frame.append(fallback);
    return frame;
  }
  const image = document.createElement("img");
  image.src = `/system-icons/${icon}`;
  if (icon.startsWith("pixel-")) image.classList.add("pixel-art");
  image.alt = "";
  image.loading = "lazy";
  image.decoding = "async";
  image.addEventListener("error", () => frame.replaceChildren(fallback), { once: true });
  frame.append(image);
  return frame;
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
    (!categoryFilter.value || system.category === categoryFilter.value) &&
    `${system.manufacturer} ${system.name}`.toLowerCase().includes(normalized)
  );
  const shown = visible.length.toLocaleString();
  const total = state.systems.length.toLocaleString();
  document.querySelector("#system-count").textContent = shown === total ? total : `${shown} / ${total}`;
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
      const label = document.createElement("span");
      label.className = "platform-identity";
      label.append(platformIcon(system.manufacturer, system.name), name);
      button.append(label, count);
      button.addEventListener("click", () => chooseSystem(system));
      details.append(button);
    }
    tree.append(details);
  }

  if (!groups.size) {
    const empty = document.createElement("div");
    empty.className = "loading-row";
    empty.textContent = "No matching platforms.";
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
  if (score == null) return "—";
  return score > 0 ? `+${score}` : String(score);
}

function artworkEntries(media, title) {
  return [["boxart", "Box art"], ["title", "Title screen"],
    ["snap", "Gameplay"], ["logo", "Logo"]]
    .filter(([kind]) => media?.[kind]?.path)
    .map(([kind, label]) => {
      const path = media[kind].path.split("/").map(encodeURIComponent).join("/");
      return {kind, label, path, source: `/media/${path}`, caption: `${title} — ${label}`};
    });
}

const coverObserver = window.IntersectionObserver && new IntersectionObserver(entries => {
  for (const {target, isIntersecting} of entries) {
    if (isIntersecting) {
      coverObserver.unobserve(target);
      target.src = target.dataset.preview;
    }
  }
}, {rootMargin: "240px 0px"});

function renderCover(element, game, size, {eager = false, enlarge = true} = {}) {
  const candidates = artworkEntries(game.media, game.title);
  const showFallback = () => element.replaceChildren(platformIcon(game.manufacturer, game.systemName));
  if (!candidates.length) return showFallback();
  const image = document.createElement("img");
  image.className = "game-art";
  image.alt = "";
  image.loading = eager ? "eager" : "lazy";
  image.decoding = "async";
  let index = 0;
  const preview = () => `/previews/${size}/${candidates[index].path}`;
  image.addEventListener("error", () => {
    if (!image.isConnected) return;
    index += 1;
    if (index < candidates.length) image.src = preview();
    else showFallback();
  });
  element.append(enlarge ? artworkButton(image, candidates, () => index, `${game.title} — Artwork`) : image);
  if (coverObserver && !eager) {
    image.dataset.preview = preview();
    coverObserver.observe(image);
  } else {
    image.src = preview();
  }
}

const artworkDialog = document.querySelector("#artwork-dialog");
const artworkImage = document.querySelector("#artwork-image");
const artworkError = document.querySelector("#artwork-error");
let artworkItems = [];
let artworkIndex = 0;

function renderArtworkImage() {
  const item = artworkItems[artworkIndex];
  document.querySelector("#artwork-caption").textContent = item.caption;
  artworkError.hidden = true;
  artworkImage.hidden = false;
  artworkImage.alt = item.caption;
  artworkImage.src = item.source;
  document.querySelector("#artwork-navigation").hidden = artworkItems.length < 2;
  document.querySelector("#artwork-position").textContent = `Image ${artworkIndex + 1} of ${artworkItems.length}`;
}

function moveArtwork(direction) {
  if (!artworkDialog.open || artworkItems.length < 2) return;
  artworkIndex = (artworkIndex + direction + artworkItems.length) % artworkItems.length;
  renderArtworkImage();
}

function artworkButton(image, items, startIndex, caption = items[startIndex()].caption) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "artwork-zoom";
  button.setAttribute("aria-label", `Enlarge ${caption}`);
  button.setAttribute("aria-haspopup", "dialog");
  button.append(image);
  button.addEventListener("click", () => {
    artworkItems = items;
    artworkIndex = startIndex();
    renderArtworkImage();
    artworkDialog.showModal();
  });
  return button;
}

document.querySelector("#artwork-close").addEventListener("click", () => artworkDialog.close());
document.querySelector("#artwork-previous").addEventListener("click", () => moveArtwork(-1));
document.querySelector("#artwork-next").addEventListener("click", () => moveArtwork(1));
artworkDialog.addEventListener("keydown", event => {
  if (artworkItems.length > 1 && ["ArrowLeft", "ArrowRight"].includes(event.key)) {
    event.preventDefault();
    moveArtwork(event.key === "ArrowLeft" ? -1 : 1);
  }
});
artworkDialog.addEventListener("click", event => {
  if (event.target !== artworkDialog) return;
  const rect = artworkDialog.getBoundingClientRect();
  if (event.clientX < rect.left || event.clientX > rect.right ||
      event.clientY < rect.top || event.clientY > rect.bottom) artworkDialog.close();
});
artworkDialog.addEventListener("close", () => {
  artworkImage.removeAttribute("src");
  artworkItems = [];
  artworkIndex = 0;
});
artworkImage.addEventListener("error", () => {
  if (!artworkDialog.open) return;
  artworkImage.hidden = true;
  artworkError.hidden = false;
});

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

function renderArtworkGallery(container, media, title, attachments = []) {
  const available = artworkEntries(media, title);
  const existing = new Set(available.map(item => item.path.split("/").at(-1)));
  for (const asset of attachments) {
    if (existing.has(asset.key)) continue;
    const label = asset.category || asset.label;
    available.push({label, path: asset.artworkPath, source: asset.url,
      caption: `${title} — ${label}`, credit: sourceCredit(asset), region: asset.region});
  }
  if (!available.length) return;

  const gallery = document.createElement("section");
  gallery.className = "art-gallery";
  gallery.setAttribute("aria-label", `Artwork for ${title}`);
  for (const [index, {kind, label, path, source, credit, region, caption: imageCaption}] of available.entries()) {
    const item = media?.[kind] || {};
    const figure = document.createElement("figure");
    const image = document.createElement("img");
    image.src = path ? `/previews/320/${path}` : source;
    image.alt = imageCaption;
    image.loading = "lazy";
    const zoom = artworkButton(image, available, () => index);
    const caption = document.createElement("figcaption");
    const credits = [label];
    if (credit || item.provider === "exo") credits.push(credit || "eXo");
    if (item.provider === "launchbox") credits.push("LaunchBox");
    if (region) credits.push(region);
    if (item.matchBasis) credits.push(item.matchBasis.replaceAll("_", " "));
    if (item.regionMatch) credits.push(`region ${item.regionMatch}`);
    caption.textContent = credits.join(" · ");
    figure.append(zoom, caption);
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
    const preferredValues = new Set(fact.preferredValues || fact.values.map(source => source.value));
    const grouped = new Map();
    for (const source of fact.values) {
      if (!preferredValues.has(source.value)) continue;
      if (!grouped.has(source.value)) grouped.set(source.value, { ...source, sources: [] });
      grouped.get(source.value).sources.push(source);
    }
    const candidates = [...grouped.values()];
    for (const candidate of candidates) {
      const item = document.createElement("div");
      item.className = "software-fact-value";
      const value = document.createElement("span");
      value.className = "software-fact-text";
      value.textContent = candidate.value;
      item.append(value);
      for (const source of candidate.sources) {
        const evidence = document.createElement("span");
        evidence.className = "software-fact-evidence";
        const contentLabel = source.matchedContentCount === 1 ? "content hash" : "content hashes";
        const recordLabel = source.sourceRecordCount === 1 ? "RDB row" : "RDB rows";
        const databases = source.sourceDatabases.length
          ? ` · ${source.sourceDatabases.join(", ")}`
          : "";
        evidence.textContent = source.sourceProvider === "exo" ? "eXo" + databases
          : source.sourceProvider === "launchbox"
          ? `LaunchBox · title/platform match${databases}`
          : `${source.matchedContentCount} ${contentLabel} · ${source.sourceRecordCount} ${recordLabel}${databases}`;
        if (source.sourceRevision) evidence.title = `${source.sourceProvider} revision ${source.sourceRevision}`;
        item.append(evidence);
      }
      definition.append(item);
    }
    grid.append(term, definition);
  }
  section.append(grid);
  container.append(section);
}

function renderReleaseDetails(container, releases, facts, softwareId, media, title, systemId, installChoice = false) {
  container.replaceChildren();
  renderArtworkGallery(container, media, title);
  renderSoftwareFacts(container, facts);
  renderRankedReleases(container, releases, softwareId, systemId, installChoice);
}

function renderRankedReleases(container, releases, softwareId, systemId, installChoice) {
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
    resultBadge.textContent = release.selected ? (installChoice ? "Install choice" : "Selected") : `Rank ${release.rank}`;
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
      button.addEventListener("click", () => openCorrectionDialog(release, softwareId, systemId));
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

function renderSourceDetails(container, detail, preferredEntry, showMetadata, game = {}) {
  if (showMetadata) renderSoftwareFacts(container, sourceFacts(detail, preferredEntry));
  renderSourceEditions(container, detail, game);
  renderSourceAssets(container, detail.assets);
  renderSourceRecords(container, detail, preferredEntry);
}

function sourceFacts(detail, preferredEntry) {
  const entry = detail?.entries.find(item => item.key === preferredEntry) || detail?.entries[0];
  return Object.entries(entry?.facts || {}).map(([key, values]) => ({
    key, preferredValues: values,
    values: values.map(value => ({value, sourceProvider: "exo", sourceDatabases: [entry.sourceList]})),
  }));
}

function renderSourceEditions(container, detail, game) {
  const heading = document.createElement("h3");
  heading.textContent = "eXo editions";
  container.append(heading);
  const list = document.createElement("ul");
  list.className = "source-editions";
  for (const edition of detail.editions) {
    const item = document.createElement("li");
    const source = detail.entries.find(entry => entry.key === edition.entryKey);
    const labels = [edition.label, edition.environment, source?.sourceList, edition.runner, edition.engineGame];
    if (edition.score != null) labels.push(scoreText(edition.score));
    if (game.preferredEditionKey === edition.key) labels.push("Preferred catalog edition");
    item.textContent = labels.filter(Boolean).join(" · ");
    if (edition.breakdown?.length) {
      const reasons = document.createElement("details");
      reasons.append(cellText("summary", "Score breakdown"));
      appendBreakdown(reasons, edition.breakdown);
      item.append(reasons);
    }
    list.append(item);
  }
  container.append(list);
  if (game.preferredEditionKey && game.installSourceCollection) {
    container.append(cellText("p", `Available to install: ${game.installReleaseTitle} · ${game.installSourceCollection} · ${scoreText(game.installScore)}`));
  }
}

function sourceCredit(asset) {
  return [...new Set((asset.sources || []).map(source => source.sourceList))].join(", ");
}

function renderSourceAssets(container, attachments) {
  const groups = new Map();
  const labels = {manual: "Manuals", extra: "Extras", video: "Videos", music: "Music",
    artwork: "Artwork", url: "Links", collection_document: "Collection guides", file: "Files"};
  for (const asset of attachments) {
    const label = labels[asset.kind] || asset.kind;
    if (!groups.has(label)) groups.set(label, []);
    groups.get(label).push(asset);
  }
  for (const [label, assets] of groups) {
    const section = document.createElement("details");
    section.className = "source-asset-group";
    section.open = label === "Manuals" || label === "Extras";
    const summary = document.createElement("summary");
    summary.textContent = label + " (" + assets.length + ")";
    const items = document.createElement("ul");
    for (const asset of assets) {
      const row = document.createElement("li");
      const link = document.createElement("a");
      link.href = asset.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = asset.label;
      row.append(link);
      const credit = [sourceCredit(asset), asset.region].filter(Boolean).join(" · ");
      if (credit) row.append(cellText("small", credit));
      items.append(row);
    }
    section.append(summary, items);
    container.append(section);
  }
}

function renderSourceRecords(container, detail, preferredEntry) {
  const entries = [...detail.entries].sort((a, b) => Number(b.key === preferredEntry) - Number(a.key === preferredEntry));
  for (const entry of entries) {
    const section = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = "Source record · " + entry.sourceList + " · " + entry.title;
    const fields = document.createElement("dl");
    fields.className = "software-fact-grid";
    for (const [key, value] of Object.entries(entry.fields)) {
      fields.append(cellText("dt", key), cellText("dd", value));
    }
    for (const alias of entry.alternateNames) {
      fields.append(cellText("dt", "Alternate title"), cellText("dd", [alias.Name, alias.Region].filter(Boolean).join(" · ")));
    }
    section.append(summary, fields);
    container.append(section);
  }
}

function cellText(tag, text) {
  const element = document.createElement(tag);
  element.textContent = text;
  return element;
}

function toggleReleaseDetails(game, row, detailRow, button) {
  const opening = detailRow.hidden;
  detailRow.hidden = !opening;
  button.textContent = opening ? "⌄" : "›";
  button.setAttribute("aria-expanded", String(opening));
  row.classList.toggle("expanded", opening);
  if (opening) loadReleaseDetails(game, detailRow.querySelector(".release-details"));
  else pauseAudio(detailRow);
}

async function loadReleaseDetails(game, container) {
  if (container.dataset.loaded) return;
  container.dataset.loaded = "loading";
  container.className = "release-details";
  container.textContent = "Loading software metadata, ranked releases and hashes…";
  try {
    const source = game.sourceDetailKey ? await requestJson("/api/exo/" + game.sourceDetailKey) : null;
    if (game.sourceOnly && source) {
      container.replaceChildren();
      renderArtworkGallery(container, game.media, game.title);
      renderSourceDetails(container, source, game.sourceEntryKey, true, game);
      container.dataset.loaded = "true";
      return;
    }
    const soundtrackRequest = state.vgmEnabled
      ? requestJson(`/api/software/${game.softwareId}/soundtracks`).catch(() => null)
      : Promise.resolve([]);
    const releaseKey = browseUrl(`/api/software/${game.softwareId}/releases`);
    const factsKey = browseUrl(`/api/software/${game.softwareId}/facts`);
    let releases = state.releaseDetails.get(releaseKey);
    let facts = state.softwareFacts.get(factsKey);
    if (!releases || !facts) {
      [releases, facts] = await Promise.all([
        releases || requestJson(releaseKey),
        facts || requestJson(factsKey),
      ]);
      state.releaseDetails.set(releaseKey, releases);
      state.softwareFacts.set(factsKey, facts);
    }
    renderReleaseDetails(container, releases, facts, game.softwareId, game.media, game.title, game.systemId, Boolean(game.preferredEditionKey));
    if (source) renderSourceDetails(container, source, game.sourceEntryKey, facts.length === 0, game);
    const soundtracks = await soundtrackRequest;
    if (!soundtracks || soundtracks.length) {
      const section = document.createElement("section");
      section.className = "software-facts";
      section.append(cellText("h3", "Soundtracks"));
      if (soundtracks) renderSoundtracks(section, soundtracks);
      else section.append(cellText("p", "Soundtracks are temporarily unavailable."));
      container.insertBefore(section, container.querySelector(":scope > .release-detail-heading"));
    }
    container.dataset.loaded = "true";
  } catch (error) {
    delete container.dataset.loaded;
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

function openCorrectionDialog(release, softwareId, systemId) {
  state.correction = { release, softwareId, systemId, target: null };
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
        `/api/systems/${state.correction.systemId}/correction-targets?exclude_software_id=${state.correction.softwareId}&q=${encodeURIComponent(query)}`
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
        systemId: state.correction.systemId,
        subjectContentSignature: state.correction.release.releaseContentSignature,
        action,
        targetContentSignature: action === "assign" ? state.correction.target.targetContentSignature : null,
        note: document.querySelector("#correction-note").value,
      }),
    });
    correctionDialog.close();
    state.releaseDetails.clear();
    state.softwareFacts.clear();
    document.dispatchEvent(new Event("catalog-rebuilt"));
  } catch (error) {
    correctionStatus.textContent = error.message;
    save.disabled = false;
  }
});

document.querySelector("#correction-close").addEventListener("click", () => correctionDialog.close());
document.querySelector("#correction-cancel").addEventListener("click", () => correctionDialog.close());

function showMessage(message, className = "empty-state") {
  state.results = null;
  coverObserver?.disconnect();
  pauseAudio(tableBody);
  tableWrap.hidden = true;
  tableBody.replaceChildren();
  gameGrid.hidden = true;
  gameGrid.replaceChildren();
  pagination.hidden = true;
  empty.className = className;
  empty.replaceChildren();
  const text = document.createElement("p");
  text.textContent = message;
  empty.append(text);
  empty.hidden = false;
}

function renderTableRows(items) {
  for (const game of items) {
    const row = document.createElement("tr");
    row.className = "game-row";
    const expandCell = document.createElement("td");
    expandCell.className = "expand-cell";
    const expand = document.createElement("button");
    expand.type = "button";
    expand.className = "expand-button";
    expand.textContent = "›";
    expand.setAttribute("aria-label", `Show details for ${game.title}`);
    expand.setAttribute("aria-expanded", "false");
    expandCell.append(expand);
    const art = document.createElement("td");
    art.className = "art-cell";
    renderCover(art, game, 128);
    row.append(expandCell, art);
    const titleCell = cell("", "title-cell");
    const title = softwareLink(game);
    title.textContent = game.title;
    titleCell.append(title);
    const identity = document.createElement("span");
    identity.className = "cell-note";
    const identityLabels = {
      recovered_legacy: "Recovered identity · exact SHA-1 anchor",
      parent_clone: "Recovered identity · Parent/Clone",
      manual: "Maintained manual identity",
      title_fallback: "Grouped by title",
      exo: "eXo source edition",
    };
    identity.textContent = identityLabels[game.identityBasis] || game.identityBasis;
    titleCell.append(identity);
    const platform = cell("", "platform-cell");
    const label = document.createElement("span");
    label.textContent = game.systemName || "Unknown platform";
    const manufacturer = document.createElement("span");
    manufacturer.className = "cell-note";
    manufacturer.textContent = game.manufacturer || "";
    label.append(manufacturer);
    const platformIdentity = document.createElement("div");
    platformIdentity.className = "platform-identity";
    platformIdentity.append(platformIcon(game.manufacturer, game.systemName), label);
    platform.append(platformIdentity);
    row.append(titleCell, platform);

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
    detailCell.colSpan = 13;
    const detailContainer = document.createElement("div");
    detailContainer.className = "release-details";
    detailCell.append(detailContainer);
    detailRow.append(detailCell);
    const toggle = () => toggleReleaseDetails(game, row, detailRow, expand);
    expand.addEventListener("click", toggle);
    row.addEventListener("click", event => {
      if (event.target.closest("a, button, details")) return;
      toggle();
    });
    tableBody.append(row, detailRow);
  }
}

function softwareLink(game) {
  const link = document.createElement("a");
  link.href = game.softwareKey
    ? `/software/${game.softwareId}-${game.softwareKey}`
    : `/software/exo/${game.sourceDetailKey}`;
  link.className = "software-link";
  link.setAttribute("aria-label", `Open ${game.title} on ${game.systemName}`);
  return link;
}

function gameCard(game) {
  const card = document.createElement("li");
  card.className = "game-card";
  const link = softwareLink(game);
  link.classList.add("card-link");
  const art = document.createElement("div");
  art.className = "card-art";
  renderCover(art, game, 320, {enlarge: false});
  const details = document.createElement("div");
  details.className = "card-details";
  const platform = document.createElement("span");
  platform.className = "card-platform";
  platform.textContent = state.selectedSystem ? (game.regions || []).join(" · ") : game.systemName;
  if (game.isRomHack) platform.textContent = [platform.textContent, "ROM hack"].filter(Boolean).join(" · ");
  const title = document.createElement("span");
  title.className = "card-title";
  title.textContent = game.title;
  if (platform.textContent) details.append(platform);
  details.append(title);
  link.append(art, details);
  card.append(link);
  return card;
}

function renderGames(payload) {
  state.results = payload;
  coverObserver?.disconnect();
  pauseAudio(tableBody);
  tableBody.replaceChildren();
  gameGrid.replaceChildren();
  const tiles = state.layout === "tiles";
  if (tiles) gameGrid.append(...payload.items.map(gameCard));
  else renderTableRows(payload.items);

  gameGrid.hidden = !tiles || !payload.items.length;
  tableWrap.hidden = tiles || !payload.items.length;
  empty.hidden = Boolean(payload.items.length);
  if (!payload.items.length) showMessage(state.query || Object.keys(state.metadataFilters).length ? "No games match your search and filters." : "No preferred releases found.");

  const pageCount = Math.max(1, Math.ceil(payload.total / payload.pageSize));
  pagination.hidden = payload.total <= payload.pageSize;
  document.querySelector("#page-label").textContent = `Page ${payload.page} of ${pageCount}`;
  document.querySelector("#previous-page").disabled = payload.page <= 1;
  document.querySelector("#next-page").disabled = payload.page >= pageCount;
  const match = state.query || Object.keys(state.metadataFilters).length ? " matching" : "";
  const titles = payload.total === 1 ? "title" : "titles";
  document.querySelector("#system-summary").textContent = `${payload.total.toLocaleString()}${match} ${titles}`;
}

function setLayout(layout) {
  state.layout = layout;
  for (const button of document.querySelectorAll(".layout-switch button")) {
    button.setAttribute("aria-pressed", String(button.dataset.layout === layout));
  }
  if (state.results) renderGames(state.results);
}

try {
  if (localStorage.getItem("gamedb-layout") === "table") setLayout("table");
} catch { /* Storage is optional. */ }
for (const button of document.querySelectorAll(".layout-switch button")) {
  button.addEventListener("click", () => {
    if (state.layout === button.dataset.layout) return;
    setLayout(button.dataset.layout);
    try { localStorage.setItem("gamedb-layout", state.layout); } catch { /* Storage is optional. */ }
  });
}

async function selectSystem(system, page = 1, platformsReady) {
  clearTimeout(gameFilterTimer);
  state.selectedSystem = system;
  state.page = page;
  refreshMetadataOptions();
  const requestId = ++state.requestId;
  if (state.systems.length) renderTree(filter.value);
  document.querySelector("#manufacturer-name").textContent = system?.manufacturer || "Catalog index";
  document.querySelector("#system-name").textContent = system?.name || "All platforms";
  document.querySelector("#system-summary").textContent = "";
  gameFilter.disabled = false;
  gameFilter.placeholder = system ? `Search games on ${system.name}…` : "Search games across all platforms…";
  document.querySelector("#all-platforms").classList.toggle("active", !system);
  showMessage("Loading preferred releases…");

  try {
    const query = encodeURIComponent(state.query);
    const path = system ? `/api/systems/${system.id}/titles` : "/api/titles";
    const metadata = Object.keys(state.metadataFilters).length
      ? `&filters=${encodeURIComponent(JSON.stringify(state.metadataFilters))}` : "";
    const [payload] = await Promise.all([
      requestJson(browseUrl(`${path}?page=${page}&page_size=${state.pageSize}&q=${query}${metadata}`)),
      platformsReady,
    ]);
    if (requestId !== state.requestId) return;
    renderGames(payload);
  } catch (error) {
    if (requestId !== state.requestId) return;
    showMessage(error.message, "error-row");
    pagination.hidden = true;
  }
}

function setSystemBrowserOpen(open) {
  systemBrowserToggle.setAttribute("aria-expanded", String(open));
  systemBrowserToggle.textContent = open ? "Hide platforms" : "Browse platforms";
}
systemBrowserToggle.addEventListener("click", () => {
  setSystemBrowserOpen(systemBrowserToggle.getAttribute("aria-expanded") !== "true");
});
function chooseSystem(system) {
  if (systemBrowserToggle.offsetWidth) {
    systemBrowserToggle.focus();
    setSystemBrowserOpen(false);
  }
  selectSystem(system);
}
document.querySelector("#all-platforms").addEventListener("click", () => chooseSystem(null));

filter.addEventListener("input", () => renderTree(filter.value));
categoryFilter.addEventListener("change", () => renderTree(filter.value));
document.querySelector("#previous-page").addEventListener("click", () => selectSystem(state.selectedSystem, state.page - 1));
document.querySelector("#next-page").addEventListener("click", () => selectSystem(state.selectedSystem, state.page + 1));

let gameFilterTimer;
gameFilter.addEventListener("input", () => {
  clearTimeout(gameFilterTimer);
  state.query = gameFilter.value.trim();
  state.requestId += 1;
  gameFilterTimer = setTimeout(() => {
    selectSystem(state.selectedSystem, 1);
  }, 250);
});

async function loadSystemCounts() {
  const mode = state.hideRomHacks;
  const systems = await requestJson(browseUrl("/api/systems"));
  if (state.hideRomHacks !== mode) return;
  state.systems = systems;
  if (state.selectedSystem) state.selectedSystem = systems.find(system => system.id === state.selectedSystem.id);
  renderTree(filter.value);
}

let optionsRequest;

function loadInterfaceOptions() {
  if (!optionsRequest) {
    optionsRequest = Promise.allSettled([
      requestJson("/api/capabilities"),
      requestJson("/system-icons.json"),
    ]).then(([capabilities, icons]) => {
      state.systemIcons = icons.value || {};
      state.correctionsEnabled = Boolean(capabilities.value?.softwareCorrections);
      state.vgmEnabled = Boolean(capabilities.value?.vgm);
    });
  }
  return optionsRequest;
}

async function loadPlatforms() {
  try {
    await Promise.all([loadSystemCounts(), loadInterfaceOptions()]);
    renderTree(filter.value);
  } catch (error) {
    tree.replaceChildren();
    const message = document.createElement("div");
    message.className = "error-row";
    message.textContent = error.message;
    tree.append(message);
  }
}

const hideRomHacks = document.querySelector("#hide-rom-hacks");
try {
  state.hideRomHacks = localStorage.getItem("gamedb-hide-rom-hacks") !== "0";
} catch { /* Storage is optional. */ }
hideRomHacks.checked = state.hideRomHacks;
hideRomHacks.addEventListener("change", () => {
  state.hideRomHacks = hideRomHacks.checked;
  try { localStorage.setItem("gamedb-hide-rom-hacks", state.hideRomHacks ? "1" : "0"); } catch { /* Storage is optional. */ }
  selectSystem(state.selectedSystem, 1, loadSystemCounts());
});

function startCatalog() {
  initializeMetadataFilters();
  selectSystem(null, 1, loadPlatforms());
}
