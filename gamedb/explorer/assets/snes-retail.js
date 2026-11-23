"use strict";

const params = new URLSearchParams(location.search);
const isMegaDrive = location.pathname === "/catalog/megadrive";
const catalogLabel = isMegaDrive ? "Mega Drive" : "SNES";
const catalogApi = isMegaDrive ? "/api/megadrive-retail" : "/api/snes-retail";
const marketNames = {
  JP: "Japan", NA: "North America", PAL: "PAL region", BR: "Brazil", KR: "South Korea", AS: "Asia",
};
const channelNames = {"nintendo-power": "Nintendo Power", "sufami-turbo": "SuFami Turbo"};
const matchNames = {matched: "Base ROM matched", ambiguous: "Needs review", unmatched: "No base ROM match"};
const artworkNames = {boxart: "Box art", title: "Title screen", snap: "Gameplay", logo: "Clear logo"};
const inputDevices = {
  mouse: {name: "SNES Mouse", icon: "mouse"},
  "super-scope": {name: "Super Scope", icon: "lightgun"},
  justifier: {name: "Konami Justifier", icon: "lightgun"},
  multitap: {name: "Multitap", icon: "multitap"},
  "j-cart": {name: "J-Cart controller ports", icon: "multitap"},
};
const inlineItems = 2;
const maxGamesPerPage = 10;
const number = new Intl.NumberFormat();
const translationDate = new Intl.DateTimeFormat("en-GB", {
  day: "numeric", month: "short", year: "numeric", timeZone: "UTC",
});
const view = document.querySelector("#snes-browse");
const browseControls = document.querySelector(".snes-browse-controls");
const search = document.querySelector("#snes-search");
const genreSelect = document.querySelector("#snes-genre");
const translationFilter = document.querySelector("#snes-translated");
const resultCount = document.querySelector("#snes-results");
const list = document.querySelector("#snes-games");
const pagers = document.querySelectorAll(".snes-pagination");
const pageLinks = document.querySelector(".snes-page-numbers");
const status = document.querySelector("#snes-status");
const romDialog = document.querySelector("#snes-rom-dialog");
const romForm = document.querySelector("#snes-rom-form");
const romKey = document.querySelector("#snes-rom-key");
const romStatus = document.querySelector("#snes-rom-status");
const romSubmit = document.querySelector("#snes-rom-submit");
let games;
let pageSize;
let pageAnchor;
let page = Math.max(1, Number.parseInt(params.get("page"), 10) || 1);
let romDownload;
let romRequest;
let rememberedRomKey = "";

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function searchKey(value) {
  return value.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase().trim();
}

function newTabLink(name, url) {
  const link = element("a", name);
  link.href = url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  return link;
}

function artworkImage(source, alt) {
  const image = element("img");
  image.alt = alt;
  image.loading = "lazy";
  image.decoding = "async";
  image.src = source;
  return image;
}

function marketFlag(market) {
  if (!["JP", "NA", "PAL"].includes(market)) {
    const code = element("span", market, "snes-market-code");
    code.setAttribute("aria-hidden", "true");
    return code;
  }
  const icon = element("img");
  icon.alt = "";
  icon.src = `/snes-flags/${market.toLowerCase()}.png`;
  return icon;
}

function browseParameters({query, genre, translated}, pageNumber) {
  const result = new URLSearchParams();
  if (query?.trim()) result.set("q", query.trim());
  if (genre) result.set("genre", genre);
  if (translated) result.set("translated", "1");
  if (pageNumber > 1) result.set("page", String(pageNumber));
  return result;
}

function sizeBrowsePage() {
  const columns = Number(getComputedStyle(list).getPropertyValue("--catalog-columns"));
  const size = Math.floor(maxGamesPerPage / columns) * columns;
  if (size === pageSize) return;
  pageSize = size;
  renderBrowse();
}

function visiblePageNumbers(total) {
  if (total <= 7) return Array.from({length: total}, (_, index) => index + 1);
  if (page < 5) return [1, 2, 3, 4, 5, null, total];
  if (page > total - 4) return [1, null, total - 4, total - 3, total - 2, total - 1, total];
  return [1, null, page - 1, page, page + 1, null, total];
}

function renderPageLinks(total, filters) {
  pageLinks.replaceChildren(...visiblePageNumbers(total).map(target => {
    if (target === null) {
      const gap = element("span", "…", "snes-page-gap");
      gap.setAttribute("aria-hidden", "true");
      return gap;
    }
    const label = number.format(target);
    const link = element("a", label);
    const query = browseParameters(filters, target);
    link.href = query.size ? `?${query}` : location.pathname;
    link.dataset.page = target;
    link.setAttribute("aria-label", `Page ${label}`);
    if (target === page) link.setAttribute("aria-current", "page");
    return link;
  }));
}

function preferredCover(releases, title) {
  return releases.find(release => release.boxart && release.titles.includes(title))
    || releases.find(release => release.boxart);
}

function renderBrowse() {
  const filters = {query: search.value, genre: genreSelect.value, translated: translationFilter.checked};
  genreSelect.title = filters.genre;
  const term = searchKey(filters.query);
  const matches = games.filter(game => game.searchText.includes(term)
    && (!filters.genre || game.genres.includes(filters.genre))
    && (!filters.translated || game.releases.some(release => release.hasTranslations)));
  const pageCount = Math.max(1, Math.ceil(matches.length / pageSize));
  pageAnchor ??= (Math.min(page, pageCount) - 1) * pageSize;
  page = Math.min(Math.floor(pageAnchor / pageSize) + 1, pageCount);
  const start = (page - 1) * pageSize;
  const visible = matches.slice(start, start + pageSize);
  const query = browseParameters(filters, page);
  history.replaceState(null, "", location.pathname + (query.size ? `?${query}` : ""));
  const fragment = document.createDocumentFragment();
  for (const game of visible) {
    const item = element("li");
    const link = element("a", "", "snes-game");
    const detailQuery = new URLSearchParams(query);
    detailQuery.set("game", game.key);
    const releases = filters.translated ? game.releases.filter(release => release.hasTranslations) : game.releases;
    const coverRelease = preferredCover(releases, game.title);
    const detailRelease = coverRelease || (filters.translated ? releases[0] : null);
    if (detailRelease) {
      detailQuery.set("market", detailRelease.market);
      if (filters.translated) detailQuery.set("release", detailRelease.key);
    }
    const cover = coverRelease?.boxart || (filters.translated && preferredCover(game.releases, game.title)?.boxart);
    const stage = element("span", "", "snes-game-cover");
    if (cover) {
      const image = artworkImage(cover.preview || cover.url, "");
      image.addEventListener("error", () => image.remove(), {once: true});
      stage.append(image);
    }
    link.href = `?${detailQuery}`;
    const label = element("span", "", "snes-game-label");
    label.append(element("strong", game.title));
    const alias = term && !searchKey(game.title).includes(term)
      && game.aliases.find(({title}) => searchKey(title).includes(term));
    if (alias) label.append(element("span", alias.title, "snes-aliases"));
    const markets = [...new Set(game.releases.map(release => release.market))];
    const flags = element("span", "", "snes-markets");
    flags.setAttribute("role", "img");
    flags.title = markets.map(market => marketNames[market]).join(", ");
    flags.setAttribute("aria-label", flags.title);
    flags.append(...markets.map(marketFlag));
    label.append(flags);
    link.append(stage, label);
    item.append(link);
    fragment.append(item);
  }
  list.replaceChildren(fragment);
  const emptyText = filters.genre || filters.translated ? "No games match these filters." : "No games match your search.";
  resultCount.textContent = matches.length
    ? `${number.format(start + 1)}–${number.format(start + visible.length)} of ${number.format(matches.length)} games`
    : emptyText;
  resultCount.classList.toggle("sr-only", matches.length > 0);
  for (const pager of pagers) {
    const [previous, next] = pager.querySelectorAll("button");
    pager.hidden = pageCount === 1;
    previous.disabled = page <= 1;
    next.disabled = page >= pageCount;
  }
  renderPageLinks(pageCount, filters);
}

function factList(pairs, {inline = false} = {}) {
  const list = element("dl", "", inline ? "snes-profile-facts" : "snes-facts");
  for (const [label, value] of pairs) {
    if (!value) continue;
    const term = element("dt", label);
    const definition = element("dd");
    definition.append(value);
    if (inline) {
      const pair = element("div");
      pair.append(term, definition);
      list.append(pair);
    } else {
      list.append(term, definition);
    }
  }
  return list;
}

function inputIcon(icon, title) {
  const image = element("img");
  image.src = `/snes-inputs/${icon}.png`;
  image.alt = "";
  if (title) image.title = title;
  return image;
}

function renderInputs({players = 0, peripherals = []}) {
  const devices = peripherals.map(device => inputDevices[device]).filter(Boolean);
  if (!players && !devices.length) return null;
  const inputs = element("span", "", "snes-input-icons");
  const count = players === 1 ? "1 player" : players ? `Up to ${players} players` : "";
  const supported = devices.length ? `Supports ${devices.map(device => device.name).join(", ")}` : "";
  inputs.title = [count, supported].filter(Boolean).join(" · ");
  inputs.setAttribute("role", "img");
  inputs.setAttribute("aria-label", inputs.title);
  if (players === 1 && devices.length === 1 && devices[0].icon !== "multitap") {
    inputs.append(inputIcon(devices[0].icon, devices[0].name));
    return inputs;
  }
  const icons = players > 8 ? 1 : players;
  for (let index = 0; index < icons; index++) inputs.append(inputIcon("pad"));
  if (players > 8) inputs.append(element("span", `×${players}`));
  if (devices.length) {
    const accessories = element("span", "", "snes-peripheral-icons");
    accessories.append(...devices.map(device => inputIcon(device.icon, device.name)));
    inputs.append(accessories);
  }
  return inputs;
}

function uniqueValues(records, field) {
  return [...new Set(records.flatMap(record => record[field] || []))].sort();
}

function cartridgeDetails(release) {
  const records = [
    ...(release.archives || []).flatMap(archive => archive.cartridge || []),
    ...(release.cartridgeScans || []),
  ];
  return {
    serials: uniqueValues(records, "serials"),
    headerCodes: uniqueValues(records, "headerCodes"),
    boards: uniqueValues(records, "boards"),
    chips: uniqueValues(records, "romChip"),
  };
}

function renderDescription(text) {
  const container = element("div", "", "snes-description");
  const summary = element("p", text);
  summary.id = "snes-description-text";
  const toggle = element("button", "Read more", "snes-text-button");
  toggle.type = "button";
  toggle.hidden = true;
  toggle.setAttribute("aria-controls", summary.id);
  toggle.setAttribute("aria-expanded", "false");
  toggle.addEventListener("click", () => {
    const expanded = container.classList.toggle("is-expanded");
    toggle.setAttribute("aria-expanded", String(expanded));
    toggle.textContent = expanded ? "Show less" : "Read more";
  });
  container.append(summary, toggle);
  new ResizeObserver(() => {
    const style = getComputedStyle(summary);
    const lines = Number(style.getPropertyValue("--description-lines"));
    const collapsedHeight = Math.ceil(lines * parseFloat(style.lineHeight));
    toggle.hidden = summary.scrollHeight <= collapsedHeight;
  }).observe(summary);
  return container;
}

function renderArt(release) {
  const art = element("div", "", "snes-art");
  const title = release.titles.join(" / ");
  const hasCover = Boolean(release.artwork?.boxart);
  const kinds = hasCover ? Object.keys(artworkNames) : ["logo", "title", "snap"];
  const items = kinds.filter(kind => release.artwork?.[kind]).map(kind => {
    const label = artworkNames[kind];
    const asset = release.artwork[kind];
    return {kind, label, asset, source: asset.url, caption: `${title} — ${label}`,
      pixelArt: kind === "title" || kind === "snap"};
  });
  for (const [index, {kind, label, asset, caption}] of items.entries()) {
    if (kind === "logo" && hasCover) continue;
    const image = artworkImage(asset.preview || asset.url, caption);
    image.loading = "eager";
    const zoom = artworkButton(image, items, () => index);
    image.addEventListener("error", () => {
      zoom.textContent = `View ${label.toLowerCase()}`;
    }, {once: true});
    const figure = element("figure");
    figure.dataset.kind = kind;
    figure.append(zoom, element("figcaption", label));
    art.append(figure);
  }
  return art;
}

function renderManualCover(manual) {
  const figure = element("figure", "", "snes-manual-cover");
  const button = element("button", "", "artwork-zoom");
  button.type = "button";
  button.setAttribute("aria-label", `Read manual for ${manual.name}`);
  button.setAttribute("aria-haspopup", "dialog");
  button.addEventListener("click", () => openManual(manual));
  if (manual.preview) {
    const image = artworkImage(manual.preview, "");
    image.loading = "eager";
    image.addEventListener("error", () => {
      button.textContent = "Read manual";
    }, {once: true});
    button.append(image);
  } else {
    button.textContent = "Read manual";
  }
  figure.append(button, element("figcaption", "Manual"));
  return figure;
}

function releaseList(entries) {
  const list = element("ul", "", "snes-release-list");
  list.setAttribute("role", "list");
  for (const entry of entries) {
    const item = element("li");
    item.append(entry);
    list.append(item);
  }
  return list;
}

function releaseDisclosure(label, content) {
  const details = element("details", "", "snes-release-disclosure");
  details.append(element("summary", label), content);
  return details;
}

function releaseListCell(entries) {
  const cell = element("td");
  if (!entries.length) {
    cell.append(element("span", "—", "snes-release-empty"));
  } else {
    cell.append(releaseList(entries.slice(0, inlineItems)));
    const rest = entries.slice(inlineItems);
    if (rest.length) cell.append(releaseDisclosure(`+${rest.length} more`, releaseList(rest)));
  }
  return cell;
}

function manualCell(manuals) {
  return releaseListCell(manuals.map(manual => {
    const entry = element("span");
    if (manual.localUrl) {
      const link = newTabLink(manual.name, manual.localUrl);
      link.setAttribute("aria-haspopup", "dialog");
      link.addEventListener("click", event => {
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        openManual(manual);
      });
      entry.append(link);
    } else if (isMegaDrive) {
      entry.append(newTabLink(manual.name, manual.url));
    } else {
      entry.append(element("span", manual.name));
    }
    const info = isMegaDrive
      ? [...manual.regions, manual.format, manual.source].filter(Boolean).join(" · ")
      : manual.localUrl ? [manual.format, manual.language].filter(Boolean).join(" · ") : "Unavailable locally";
    if (info) entry.append(element("small", info));
    return entry;
  }));
}

function openRomDownload(translation) {
  romDownload = translation;
  romKey.value = rememberedRomKey;
  romStatus.hidden = true;
  romDialog.showModal();
  if (rememberedRomKey) romForm.requestSubmit();
}

romForm.addEventListener("submit", async event => {
  event.preventDefault();
  if (romRequest || !romDownload) return;
  const key = romKey.value.trim();
  const translation = romDownload;
  const request = new AbortController();
  romRequest = request;
  romSubmit.disabled = true;
  romStatus.textContent = "Building translated ROM…";
  romStatus.hidden = false;
  try {
    const response = await fetch(translation.romDownloadUrl, {
      headers: {Authorization: `Bearer ${key}`},
      mode: "same-origin", redirect: "error", signal: request.signal,
    });
    if (response.status === 401) {
      rememberedRomKey = "";
      romKey.value = "";
      romKey.focus();
      throw new Error("Check your GameDB API key.");
    }
    if (!response.ok) {
      const error = await response.json().catch(() => null);
      throw new Error(error?.error || "Could not build the translated ROM.");
    }
    const file = await response.blob();
    if (request.signal.aborted) return;
    const encoded = response.headers.get("Content-Disposition")?.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
    const name = encoded ? decodeURIComponent(encoded) : translation.filename.replace(/\.[^.]+$/, isMegaDrive ? ".md" : ".sfc");
    const url = URL.createObjectURL(file);
    const link = element("a");
    link.href = url;
    link.download = name;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    rememberedRomKey = key;
    romDialog.close();
  } catch (error) {
    if (!request.signal.aborted) romStatus.textContent = error.message;
  } finally {
    if (romRequest === request) {
      romRequest = null;
      romSubmit.disabled = false;
    }
  }
});

document.querySelector("#snes-rom-cancel").addEventListener("click", () => romDialog.close());
romDialog.addEventListener("close", () => {
  romRequest?.abort();
  romRequest = null;
  romSubmit.disabled = false;
  romKey.value = "";
});

function translationRow(translation, columns) {
  const inputLayouts = {
    headered: "Requires a copier header",
    interleaved: "Requires an interleaved ROM",
    "interleaved-headered": "Requires an interleaved ROM with a copier header",
  };
  const row = element("tr");
  row.setAttribute("role", "row");
  const language = element("th", translation.language);
  language.scope = "row";
  language.setAttribute("role", "rowheader");
  const authors = element("td", translation.authors?.join(", ") || "—");
  const version = element("td", translation.version || "—");
  const released = element("td");
  const date = new Date(translation.releasedAt * 1000);
  if (translation.releasedAt && Number.isFinite(date.getTime())) {
    const time = element("time", translationDate.format(date));
    time.dateTime = date.toISOString().slice(0, 10);
    released.append(time);
  } else {
    released.textContent = "—";
  }
  const patch = element("td");
  const link = element("a", translation.filename);
  link.href = translation.url;
  link.download = translation.filename;
  const downloads = element("div", "", "snes-patch-downloads");
  downloads.append(link);
  if (translation.romDownloadUrl) {
    const download = element("button", "Download ROM", "snes-text-button");
    download.type = "button";
    download.setAttribute("aria-haspopup", "dialog");
    download.setAttribute("aria-label", `Download ROM using ${translation.filename}`);
    download.addEventListener("click", () => openRomDownload(translation));
    downloads.append(download);
  }
  patch.append(downloads);
  const status = translation.status === "Fully Playable" ? "" : translation.status;
  const padding = translation.padToSize
    ? `Pad the base ROM to ${(translation.padToSize / 1024).toLocaleString()} KiB with zero bytes`
    : "";
  const info = [status, inputLayouts[translation.layout], padding].filter(Boolean).join(" · ");
  if (info) patch.append(element("small", info));
  if (translation.baseArchive) patch.append(element("small", translation.baseArchive));
  const cells = [authors, version, released, patch];
  labelReleaseCells(cells, columns);
  row.append(language, ...cells);
  return row;
}

function showTranslations(section, translations) {
  section.hidden = !translations.length;
  section.replaceChildren();
  if (section.hidden) return;

  const columns = ["Language", "Authors", "Version", "Released", "Patch"];
  const table = releaseTable("Translations", columns);
  table.classList.add("snes-translation-table");
  const rows = translations.map(translation => translationRow(translation, columns));
  table.tBodies[0].append(...rows.slice(0, inlineItems));
  section.append(table);
  const remaining = rows.slice(inlineItems);
  if (!remaining.length) return;

  const additional = table.createTBody();
  additional.id = "snes-more-translations";
  additional.setAttribute("role", "rowgroup");
  additional.append(...remaining);
  additional.hidden = true;
  const moreLabel = `Show ${remaining.length} more`;
  const button = element("button", moreLabel, "snes-text-button");
  button.type = "button";
  button.setAttribute("aria-controls", additional.id);
  button.setAttribute("aria-expanded", "false");
  button.addEventListener("click", () => {
    additional.hidden = !additional.hidden;
    button.textContent = additional.hidden ? moreLabel : "Show fewer";
    button.setAttribute("aria-expanded", String(!additional.hidden));
  });
  section.append(button);
}

function romCell(release) {
  const matched = release.status === "matched";
  const archives = matched ? release.archives : release.candidates;
  const entries = (archives || []).map(archive => {
    const name = archive.archiveNames.join(" · ");
    if (!matched) return element("span", name);
    const link = element("a", name);
    link.href = `/software/${archive.softwareId}-${archive.softwareKey}#releases`;
    return link;
  });
  const cell = releaseListCell(entries);
  if (!matched) {
    if (!entries.length) cell.replaceChildren();
    cell.prepend(element("p", matchNames[release.status], "snes-release-status"));
    if (release.reviewNote?.text) cell.append(element("small", release.reviewNote.text));
  }
  return cell;
}

function releaseTable(caption, columns) {
  const table = element("table", "", "snes-release-table");
  // Keep the table structure available when CSS wraps each release on small screens.
  table.setAttribute("role", "table");
  table.append(element("caption", caption));
  const head = table.createTHead();
  head.setAttribute("role", "rowgroup");
  const header = head.insertRow();
  header.setAttribute("role", "row");
  for (const label of columns) {
    const cell = element("th", label);
    cell.scope = "col";
    cell.setAttribute("role", "columnheader");
    header.append(cell);
  }
  table.createTBody().setAttribute("role", "rowgroup");
  return table;
}

function labelReleaseCells(cells, columns) {
  for (const [index, cell] of cells.entries()) {
    cell.setAttribute("role", "cell");
    const label = element("span", columns[index + 1], "snes-mobile-label");
    label.setAttribute("aria-hidden", "true");
    cell.prepend(label);
  }
}

function renderReleaseTable(game, picker, targets, onSelection) {
  const columns = ["Market", "Released", "Manuals", "ROM archives", "Product code", "PCB"];
  const table = releaseTable("Releases", columns);
  table.id = "snes-releases";
  const body = table.tBodies[0];
  const rows = game.releases.map(release => {
    const row = element("tr");
    row.setAttribute("role", "row");
    const market = element("th", marketNames[release.market]);
    market.scope = "row";
    market.setAttribute("role", "rowheader");
    const title = release.titles.join(" / ");
    if (title !== game.title) market.append(element("small", title));
    const credits = factList([
      ["Publisher", release.publisher !== game.publisher ? release.publisher : ""],
      ["Developer", release.developer !== game.developer ? release.developer : ""],
    ]);
    if (credits.childElementCount) market.append(releaseDisclosure("Credits", credits));
    const date = element("td", release.date);
    if (channelNames[release.channel]) date.append(element("small", channelNames[release.channel]));
    const {serials, headerCodes, boards, chips} = cartridgeDetails(release);
    const productCodes = releaseListCell(serials.map(code => element("code", code)));
    if (headerCodes.length) {
      productCodes.querySelector(".snes-release-empty")?.remove();
      productCodes.append(releaseDisclosure("ROM header", releaseList(headerCodes.map(code => element("code", code)))));
    }
    const pcb = releaseListCell(boards.map(code => element("code", code)));
    if (chips.length) {
      pcb.append(releaseDisclosure(chips.length === 1 ? "ROM chip" : "ROM chips",
        releaseList(chips.map(chip => element("code", chip)))));
    }
    const cells = [date, manualCell(release.manuals || []), romCell(release), productCodes, pcb];
    labelReleaseCells(cells, columns);
    row.append(market, ...cells);
    const flag = element("button", "", "snes-region-button");
    flag.type = "button";
    const name = title === game.title ? marketNames[release.market] : `${marketNames[release.market]} · ${title}`;
    flag.title = name;
    flag.setAttribute("aria-label", name);
    flag.setAttribute("aria-controls", `${targets} ${table.id}`);
    flag.append(marketFlag(release.market));
    if (game.releases.some(other => other !== release && other.market === release.market)) {
      flag.append(element("span", title));
    }
    picker.append(flag);
    return {row, flag, release};
  });
  let current;
  function select(entry) {
    if (!entry || current === entry) return;
    current = entry;
    body.replaceChildren(entry.row);
    for (const candidate of rows) {
      candidate.flag.setAttribute("aria-pressed", String(candidate === entry));
    }
    onSelection(entry.release);
  }
  for (const entry of rows) {
    entry.flag.addEventListener("click", () => select(entry));
  }
  const selectedMarket = params.get("market");
  const selectedStatus = params.get("match") || "matched";
  const selectedRelease = params.get("release");
  const selected = rows.find(({release}) => release.key === selectedRelease)
    || rows.find(({release}) => release.status === selectedStatus &&
      (!selectedMarket || release.market === selectedMarket))
    || rows.find(({release}) => release.market === selectedMarket)
    || rows.find(({release}) => release.status === "matched")
    || rows[0];
  if (selected) select(selected);
  return table;
}

function renderDetail(game, soundtracks) {
  if (!game) {
    status.textContent = "This retail catalog entry could not be found.";
    return;
  }
  const browseParams = browseParameters({
    query: params.get("q"), genre: params.get("genre"), translated: params.get("translated") === "1",
  }, page);
  const back = document.querySelector("#snes-back");
  back.href = location.pathname + (browseParams.size ? `?${browseParams}` : "");
  back.hidden = false;

  const masthead = element("header", "", "snes-game-heading");
  const title = document.querySelector("#snes-title");
  const pageHeading = title.parentElement;
  const picker = element("div", "", "snes-release-picker");
  picker.setAttribute("role", "group");
  picker.setAttribute("aria-label", "Regional releases");
  picker.hidden = game.releases.length < 2;
  masthead.append(picker);

  const media = element("div", "", "snes-media");
  const gallery = element("div", "", "snes-gallery");
  gallery.id = "snes-gallery";
  const soundtrack = element("section", "", "snes-soundtrack");
  soundtrack.id = "snes-soundtrack";
  soundtrack.hidden = true;
  const soundtrackTitle = element("h2", "Soundtrack");
  soundtrackTitle.id = "snes-soundtrack-title";
  soundtrack.setAttribute("aria-labelledby", soundtrackTitle.id);
  const player = element("div", "", "snes-soundtrack-content");
  soundtrack.append(soundtrackTitle, player);
  media.append(gallery, soundtrack);
  const profile = element("section", "", "snes-profile");
  const translations = element("section", "", "snes-translations");
  translations.id = "snes-translations";
  const description = game.description ? renderDescription(game.description.text) : null;
  let currentAlbums = [];
  function showRelease(release) {
    showTranslations(translations, release.translations || []);
    const metadata = release.metadata || {};
    const facts = factList([
      ["Developer", release.developer || game.developer], ["Publisher", release.publisher || game.publisher],
      ["Genre", metadata.genres?.join(" · ")], ["Controls", renderInputs(metadata)],
    ], {inline: true});
    profile.replaceChildren(...[description, facts.childElementCount ? facts : null].filter(Boolean));
    const art = renderArt(release);
    const manual = release.manuals?.find(candidate => candidate.localUrl);
    if (manual) art.append(renderManualCover(manual));
    gallery.replaceChildren(art);
    gallery.hidden = !art.childElementCount;
    const albums = soundtracks.filter(album => album.releases.includes(release.key)).sort((first, second) =>
      Number(second.titleMatches.includes(release.key)) - Number(first.titleMatches.includes(release.key)));
    if (albums.length === currentAlbums.length && albums.every(album => currentAlbums.includes(album.key))) return;
    currentAlbums = albums.map(album => album.key);
    pauseAudio(player);
    player.replaceChildren();
    soundtrack.hidden = !albums.length;
    if (albums.length) renderSoundtracks(player, albums, {compact: true});
  }

  const releases = renderReleaseTable(game, picker, `${gallery.id} ${soundtrack.id} ${translations.id}`, showRelease);
  const detail = document.querySelector("#snes-detail");
  detail.append(masthead, media, profile, releases, translations);
  title.textContent = game.title;
  title.classList.add("snes-game-title");
  masthead.prepend(title);
  pageHeading.hidden = true;
  detail.hidden = false;
  document.title = `${game.title} | ${catalogLabel} retail catalog`;
}

async function start() {
  if (isMegaDrive) {
    document.title = "Mega Drive retail catalog | GameDB";
    document.querySelector("#snes-title").textContent = "Mega Drive retail catalog";
    document.querySelector("#snes-back").textContent = "← Mega Drive catalog";
  }
  try {
    const key = params.get("game");
    const query = new URLSearchParams(key ? {game: key} : {view: "browse"});
    const response = await fetch(`${catalogApi}?${query}`);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `Could not load the ${catalogLabel} retail catalog.`);
    document.querySelector("#snes-source-link").href = payload.source.url;
    document.querySelector("#snes-source-license").href = payload.source.license;
    document.querySelector("#snes-source").hidden = false;
    if (key) {
      renderDetail(payload.game, payload.soundtracks || []);
      return;
    }
    games = payload.games.map(game => ({
      ...game, genres: game.genres || [], searchText: searchKey([game.title, ...game.aliases.map(alias => alias.title),
        ...game.releases.flatMap(release => [...release.titles, ...release.archiveTitles])].join(" ")),
    }));
    search.value = params.get("q") || "";
    const genres = [...new Set(games.flatMap(game => game.genres))].sort((a, b) => a.localeCompare(b));
    for (const genre of genres) genreSelect.add(new Option(genre, genre));
    genreSelect.disabled = !genres.length;
    genreSelect.value = genres.includes(params.get("genre")) ? params.get("genre") : "";
    const hasTranslations = !isMegaDrive || games.some(game => game.releases.some(release => release.hasTranslations));
    translationFilter.closest("label").hidden = !hasTranslations;
    translationFilter.checked = hasTranslations && params.get("translated") === "1";
    function updateFilters() {
      pageAnchor = 0;
      renderBrowse();
    }
    search.addEventListener("input", updateFilters);
    genreSelect.addEventListener("change", updateFilters);
    translationFilter.addEventListener("change", updateFilters);
    for (const pager of pagers) {
      pager.addEventListener("click", event => {
        const control = event.target.closest("[data-page-step], [data-page]");
        if (!control || control.disabled || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        const target = control.dataset.page ? Number(control.dataset.page) : page + Number(control.dataset.pageStep);
        event.preventDefault();
        if (target === page) return;
        pageAnchor = (target - 1) * pageSize;
        renderBrowse();
        if (!browseControls.contains(pager)) resultCount.focus({preventScroll: true});
        window.scrollTo(0, 0);
      });
    }
    browseControls.hidden = false;
    view.hidden = false;
    sizeBrowsePage();
    new ResizeObserver(sizeBrowsePage).observe(list);
    status.hidden = true;
  } catch (error) {
    status.textContent = error.message;
  } finally {
    document.querySelector("#snes-title").hidden = false;
  }
}

start();
