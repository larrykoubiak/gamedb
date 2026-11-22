"use strict";

const params = new URLSearchParams(location.search);
const marketNames = {JP: "Japan", NA: "North America", PAL: "PAL region"};
const channelNames = {"nintendo-power": "Nintendo Power", "sufami-turbo": "SuFami Turbo"};
const matchNames = {matched: "Base ROM matched", ambiguous: "Needs review", unmatched: "No base ROM match"};
const artworkNames = {boxart: "Box art", title: "Title screen", snap: "Gameplay", logo: "Clear logo"};
const inlineItems = 2;
const maxGamesPerPage = 10;
const number = new Intl.NumberFormat();
const view = document.querySelector("#snes-browse");
const browseControls = document.querySelector(".snes-browse-controls");
const search = document.querySelector("#snes-search");
const resultCount = document.querySelector("#snes-results");
const list = document.querySelector("#snes-games");
const pagers = document.querySelectorAll(".snes-pagination");
const pageLinks = document.querySelector(".snes-page-numbers");
const status = document.querySelector("#snes-status");
let games;
let pageSize;
let pageAnchor;
let page = Math.max(1, Number.parseInt(params.get("page"), 10) || 1);

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
  const icon = element("img");
  icon.alt = "";
  icon.src = `/snes-flags/${market.toLowerCase()}.png`;
  return icon;
}

function browseParameters(query, pageNumber) {
  const result = new URLSearchParams();
  if (query?.trim()) result.set("q", query.trim());
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

function renderPageLinks(total) {
  pageLinks.replaceChildren(...visiblePageNumbers(total).map(target => {
    if (target === null) {
      const gap = element("span", "…", "snes-page-gap");
      gap.setAttribute("aria-hidden", "true");
      return gap;
    }
    const label = number.format(target);
    const link = element("a", label);
    const query = browseParameters(search.value, target);
    link.href = query.size ? `?${query}` : location.pathname;
    link.dataset.page = target;
    link.setAttribute("aria-label", `Page ${label}`);
    if (target === page) link.setAttribute("aria-current", "page");
    return link;
  }));
}

function renderBrowse() {
  const term = searchKey(search.value);
  const matches = games.filter(game => game.searchText.includes(term));
  const pageCount = Math.max(1, Math.ceil(matches.length / pageSize));
  pageAnchor ??= (Math.min(page, pageCount) - 1) * pageSize;
  page = Math.min(Math.floor(pageAnchor / pageSize) + 1, pageCount);
  const start = (page - 1) * pageSize;
  const visible = matches.slice(start, start + pageSize);
  const query = browseParameters(search.value, page);
  history.replaceState(null, "", location.pathname + (query.size ? `?${query}` : ""));
  const fragment = document.createDocumentFragment();
  for (const game of visible) {
    const item = element("li");
    const link = element("a", "", "snes-game");
    const detailQuery = new URLSearchParams(query);
    detailQuery.set("game", game.key);
    const coverRelease = game.releases.find(release => release.boxart && release.titles.includes(game.title))
      || game.releases.find(release => release.boxart);
    const cover = coverRelease?.boxart;
    const stage = element("span", "", "snes-game-cover");
    if (coverRelease) {
      detailQuery.set("market", coverRelease.market);
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
  resultCount.textContent = matches.length
    ? `${number.format(start + 1)}–${number.format(start + visible.length)} of ${number.format(matches.length)} games`
    : "No games match your search.";
  resultCount.classList.toggle("sr-only", matches.length > 0);
  for (const pager of pagers) {
    const [previous, next] = pager.querySelectorAll("button");
    pager.hidden = pageCount === 1;
    previous.disabled = page <= 1;
    next.disabled = page >= pageCount;
  }
  renderPageLinks(pageCount);
}

function factList(pairs) {
  const list = element("dl", "", "snes-facts");
  for (const [label, value] of pairs) {
    if (value) list.append(element("dt", label), element("dd", value));
  }
  return list;
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
    } else {
      entry.append(element("span", manual.name));
    }
    const info = manual.localUrl ? [manual.format, manual.language].filter(Boolean).join(" · ") : "Unavailable locally";
    if (info) entry.append(element("small", info));
    return entry;
  }));
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

function renderReleaseTable(game, picker, targets, onSelection) {
  const columns = ["Market", "Released", "Manuals", "ROM archives", "Product code", "PCB"];
  const table = element("table", "", "snes-release-table");
  table.id = "snes-releases";
  // Keep the table structure available when CSS wraps each release on small screens.
  table.setAttribute("role", "table");
  table.append(element("caption", "Releases"));
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
  const body = table.createTBody();
  body.setAttribute("role", "rowgroup");
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
    const {serials, boards, chips} = cartridgeDetails(release);
    const productCodes = releaseListCell(serials.map(code => element("code", code)));
    const pcb = releaseListCell(boards.map(code => element("code", code)));
    if (chips.length) {
      pcb.append(releaseDisclosure(chips.length === 1 ? "ROM chip" : "ROM chips",
        releaseList(chips.map(chip => element("code", chip)))));
    }
    const cells = [date, manualCell(release.manuals || []), romCell(release), productCodes, pcb];
    for (const [index, cell] of cells.entries()) {
      cell.setAttribute("role", "cell");
      const label = element("span", columns[index + 1], "snes-mobile-label");
      label.setAttribute("aria-hidden", "true");
      cell.prepend(label);
    }
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
  const selected = rows.find(({release}) => release.status === selectedStatus &&
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
  const browseParams = browseParameters(params.get("q"), page);
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
  let currentAlbums = [];
  function showRelease(release) {
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

  const profile = element("section", "", "snes-profile");
  const credits = factList([["Developer", game.developer], ["Publisher", game.publisher]]);
  if (game.description) profile.append(renderDescription(game.description.text));
  if (credits.childElementCount) profile.append(credits);

  const releases = renderReleaseTable(game, picker, `${gallery.id} ${soundtrack.id}`, showRelease);
  const detail = document.querySelector("#snes-detail");
  detail.append(masthead, media, profile, releases);
  title.textContent = game.title;
  title.classList.add("snes-game-title");
  masthead.prepend(title);
  pageHeading.hidden = true;
  detail.hidden = false;
  document.title = `${game.title} | SNES retail catalog`;
}

async function start() {
  try {
    const key = params.get("game");
    const query = new URLSearchParams(key ? {game: key} : {view: "browse"});
    const response = await fetch(`/api/snes-retail?${query}`);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Could not load the SNES retail catalog.");
    document.querySelector("#snes-source-link").href = payload.source.url;
    document.querySelector("#snes-source-license").href = payload.source.license;
    document.querySelector("#snes-source").hidden = false;
    if (key) {
      renderDetail(payload.game, payload.soundtracks || []);
      return;
    }
    games = payload.games.map(game => ({
      ...game, searchText: searchKey([game.title, ...game.aliases.map(alias => alias.title),
        ...game.releases.flatMap(release => [...release.titles, ...release.archiveTitles])].join(" ")),
    }));
    search.value = params.get("q") || "";
    search.addEventListener("input", () => {
      pageAnchor = 0;
      renderBrowse();
    });
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
