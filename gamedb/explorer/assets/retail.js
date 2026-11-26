"use strict";

const params = new URLSearchParams(location.search);
const platform = location.pathname.split("/").at(-1);
const cartridgeIcons = {
  astrocade: "monochrome-bally-astrocade-725396c9.png", arcadia: "monochrome-emerson-arcadia-2001-66429201.png",
  vc4000: "monochrome-interton-vc-4000-02a0d329.png", studio2: "monochrome-rca-studio-ii-d6131116.png",
  creativision: "monochrome-vtech-creativision-c7a96d5e.png", vectrex: "pixel-gce-vectrex-0fbb0983.png",
  advision: "monochrome-entex-adventure-vision-84743a1e.png", pv1000: "monochrome-casio-pv-1000-093af8d0.png",
  scv: "monochrome-epoch-super-cassette-vision-d8a161c3.png", myvision: "monochrome-nichibutsu-my-vision-755d7d47.png",
  superacan: "monochrome-funtech-super-acan-cbb59803.png", loopy: "monochrome-casio-loopy-4f8b3b59.png",
  virtualboy: "pixel-nintendo-virtual-boy-bf364885.png", pico: "monochrome-sega-pico-605066e8.png",
  copera: "monochrome-yamaha-copera-e1e43d6a.png", picno: "monochrome-konami-picno-7cb04bb6.png",
  vsmile: "monochrome-vtech-v-smile-a5e50e65.png",
  gx4000: "monochrome-amstrad-gx4000-675eae7c.png",
};
const catalogLabel = {
  snes: "SNES", megadrive: "Mega Drive", nes: "NES / Famicom", playstation: "PlayStation (US)", neogeo: "Neo Geo",
  mastersystem: "Master System", pcengine: "PC Engine / TurboGrafx-16", n64: "Nintendo 64", saturn: "Sega Saturn",
  jaguar: "Atari Jaguar", pcfx: "PC-FX", cd32: "Amiga CD32", cdtv: "Commodore CDTV", "3do": "3DO",
  playdia: "Bandai Playdia", pippin: "Apple Bandai Pippin", cdi: "Philips CD-i",
  dreamcast: "Sega Dreamcast", playstation2: "PlayStation 2 (US)", gamecube: "GameCube (US)",
  channelf: "Fairchild Channel F", atari2600: "Atari 2600", atari5200: "Atari 5200", atari7800: "Atari 7800", xegs: "Atari XEGS",
  odyssey2: "Magnavox Odyssey² / Philips Videopac", intellivision: "Intellivision", colecovision: "ColecoVision",
  astrocade: "Bally Astrocade", arcadia: "Emerson Arcadia 2001", vc4000: "Interton VC 4000",
  studio2: "RCA Studio II / Toshiba Visicom", creativision: "VTech CreatiVision", vectrex: "GCE Vectrex",
  advision: "Entex Adventure Vision", pv1000: "Casio PV-1000", scv: "Epoch Super Cassette Vision",
  myvision: "Nichibutsu My Vision", superacan: "Funtech Super A’Can", loopy: "Casio Loopy",
  virtualboy: "Nintendo Virtual Boy", pico: "Sega Pico", copera: "Yamaha Copera", picno: "Konami Picno",
  vsmile: "VTech V.Smile", nuon: "VM Labs NUON", gx4000: "Amstrad GX4000", marty: "Fujitsu FM Towns Marty",
}[platform];
const catalogApi = `/api/${platform}-retail`;
const romExtension = {
  snes: ".sfc", megadrive: ".md", nes: ".nes", mastersystem: ".sms", pcengine: ".pce", n64: ".z64", colecovision: ".col", virtualboy: ".vb",
}[platform];
const playStation = platform === "playstation";
const saturn = platform === "saturn";
const jaguar = platform === "jaguar";
const classicCartridge = Boolean(cartridgeIcons[platform])
  || ["channelf", "atari2600", "atari5200", "atari7800", "xegs", "odyssey2", "intellivision", "colecovision"].includes(platform);
const earlyDisc = ["pcfx", "cd32", "cdtv", "3do", "playdia", "pippin", "cdi", "nuon", "marty"].includes(platform);
const sixthGeneration = ["dreamcast", "playstation2", "gamecube"].includes(platform);
const optical = playStation || saturn || earlyDisc || sixthGeneration;
const neoGeo = platform === "neogeo";
const masterSystem = platform === "mastersystem";
const pcEngine = platform === "pcengine";
const nintendo64 = platform === "n64";
const useCoverFallback = neoGeo || masterSystem || pcEngine || jaguar || earlyDisc || classicCartridge || sixthGeneration;
const marketNames = {
  JP: "Japan", NA: playStation || ["gamecube", "playstation2", "pippin"].includes(platform) ? "United States" : "North America",
  PAL: "PAL region", BR: "Brazil", WORLD: "Worldwide", UNK: "Market unconfirmed",
  KR: "South Korea", AS: saturn || platform === "superacan" ? "Taiwan" : "Asia",
  MVS: "MVS arcade", AES: "AES home",
};
const channelNames = {"nintendo-power": "Nintendo Power", "sufami-turbo": "SuFami Turbo"};
const hardwareNames = {
  snes: "SNES / Super Famicom", n64: "Nintendo 64",
  satellaview: "Satellaview", "sufami-turbo": "SuFami Turbo", n64dd: "Nintendo 64DD",
  nes: "NES / Famicom", megadrive: "Mega Drive / Genesis", pcengine: "PC Engine / TurboGrafx-16",
  mastersystem: "Master System / Mark III", sg1000: "SG-1000",
  fds: "Famicom Disk System", "32x": "32X", supergrafx: "SuperGrafx",
  segacd: "Sega CD / Mega-CD", "32x-cd": "Sega CD + 32X", pcecd: "PC Engine CD", neogeocd: "Neo Geo CD",
  mvs: "MVS arcade", aes: "AES home",
  odyssey2: "Odyssey² / Videopac", "videopac-plus": "Videopac+ / Jopac",
  studio2: "RCA Studio II", visicom: "Toshiba Visicom",
};
const hardwareLabels = {fds: "FDS", segacd: "Sega CD", neogeocd: "CD", mvs: "MVS", aes: "AES", n64dd: "64DD", visicom: "Visicom"};
const cdAddons = new Set(["segacd", "32x-cd", "pcecd", "neogeocd"]);
const addonDownloads = {
  fds: "Download disk", "32x": "Download cartridge", supergrafx: "Download HuCard", sg1000: "Download cartridge",
  satellaview: "Download broadcast", "sufami-turbo": "Download cartridge", n64dd: "Download disk",
};
const matchNames = {ambiguous: "Needs review", unmatched: optical ? "No verified discs" : "No base ROM match"};
const artworkNames = {
  boxart: "Box art", cartridge: "Cartridge", flyer: "Arcade flyer", marquee: "Mini marquee",
  title: "Title screen", snap: "Gameplay", logo: "Clear logo",
};
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
const hardwareSelect = document.querySelector("#snes-hardware");
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
  const key = value.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase().trim();
  return playStation ? key.replace(/\b(s[cl]us)[-_\s]*(\d{3})\.?(\d{2})\b/g, "$1-$2$3") : key;
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
  if (!["JP", "NA", "PAL", "BR"].includes(market)) {
    const code = element("span", market, "snes-market-code");
    code.setAttribute("aria-hidden", "true");
    return code;
  }
  const icon = element("img");
  icon.alt = "";
  icon.src = `/snes-flags/${market.toLowerCase()}.png`;
  return icon;
}

function releaseHardware(release) {
  return release.hardware || (neoGeo ? release.market.toLowerCase() : platform);
}

function supportsHardware(release, hardware) {
  return !hardware || releaseHardware(release) === hardware
    || release.compatibleHardware?.includes(hardware) || release.requiredHardware?.includes(hardware);
}

function discRelease(release) {
  return optical || cdAddons.has(release.hardware);
}

function browseParameters({query, hardware, genre, translated}, pageNumber) {
  const result = new URLSearchParams();
  if (query?.trim()) result.set("q", query.trim());
  if (hardware) result.set("hardware", hardware);
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

function hasAesCover(release) {
  return release.market === "AES" && (release.boxart || release.artwork?.boxart);
}

function preferredCover(releases, title) {
  if (neoGeo) return releases.find(hasAesCover) || releases.find(release => release.market === "MVS" && release.cover)
    || releases.find(release => release.boxart || release.cover);
  return releases.find(release => release.boxart && release.titles.includes(title))
    || releases.find(release => release.boxart)
    || releases.find(release => release.hardware === "satellaview" && release.status === "matched" && release.cover)
    || releases.find(release => (useCoverFallback || release.hardware) && release.cover);
}

function renderBrowse() {
  const filters = {
    query: search.value, hardware: hardwareSelect.value, genre: genreSelect.value, translated: translationFilter.checked,
  };
  genreSelect.title = filters.genre;
  const term = searchKey(filters.query);
  const matches = [];
  for (const game of games) {
    if (!game.searchText.includes(term) || (filters.genre && !game.genres.includes(filters.genre))) continue;
    const releases = game.releases.filter(release => supportsHardware(release, filters.hardware)
      && (!filters.translated || release.hasTranslations));
    if (releases.length) matches.push({game, releases});
  }
  const pageCount = Math.max(1, Math.ceil(matches.length / pageSize));
  pageAnchor ??= (Math.min(page, pageCount) - 1) * pageSize;
  page = Math.min(Math.floor(pageAnchor / pageSize) + 1, pageCount);
  const start = (page - 1) * pageSize;
  const visible = matches.slice(start, start + pageSize);
  const query = browseParameters(filters, page);
  history.replaceState(null, "", location.pathname + (query.size ? `?${query}` : ""));
  const fragment = document.createDocumentFragment();
  for (const {game, releases} of visible) {
    const item = element("li");
    const link = element("a", "", "snes-game");
    const detailQuery = new URLSearchParams(query);
    detailQuery.set("game", game.key);
    const coverRelease = preferredCover(releases, game.title);
    const detailRelease = coverRelease || ((filters.translated || filters.hardware) ? releases[0] : null);
    if (detailRelease) {
      detailQuery.set("market", detailRelease.market);
      if (filters.hardware || filters.translated || game.releases.some(
        release => release !== detailRelease && release.market === detailRelease.market
      )) detailQuery.set("release", detailRelease.key);
    }
    const cover = coverRelease?.boxart || coverRelease?.cover
      || (filters.translated && !filters.hardware && preferredCover(game.releases, game.title)?.boxart);
    const stage = element("span", "", "snes-game-cover");
    const placeholderIcon = platform === "cdtv" ? "retail-logo-cdtv.png" : cartridgeIcons[platform];
    if (placeholderIcon) {
      stage.style.setProperty("--cover-placeholder", `url("/system-icons/${placeholderIcon}")`);
    }
    if (platform === "nuon") stage.dataset.hardware = "nuon";
    if (detailRelease?.hardware === "satellaview") stage.dataset.hardware = "satellaview";
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
    const markets = [...new Set(releases.map(release => release.market))];
    const addons = [...new Set(releases.flatMap(release =>
      [release.hardware, ...(release.compatibleHardware || [])].filter(Boolean)))];
    const flags = element("span", "", "snes-markets");
    flags.setAttribute("role", "img");
    flags.title = [...markets.map(market => marketNames[market]), ...addons.map(key => hardwareNames[key])].join(", ");
    flags.setAttribute("aria-label", flags.title);
    flags.append(...markets.map(marketFlag));
    for (const key of addons) flags.append(element("span", hardwareLabels[key] || hardwareNames[key], "snes-market-code"));
    label.append(flags);
    link.append(stage, label);
    item.append(link);
    fragment.append(item);
  }
  list.replaceChildren(fragment);
  const emptyText = filters.hardware || filters.genre || filters.translated
    ? "No games match these filters." : "No games match your search.";
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
  const hasCover = Boolean(release.artwork?.boxart || release.artwork?.cartridge
    || release.artwork?.flyer || release.artwork?.marquee);
  const kinds = hasCover ? Object.keys(artworkNames) : ["logo", "title", "snap"];
  const items = kinds.filter(kind => release.artwork?.[kind]).map(kind => {
    const asset = release.artwork[kind];
    const label = asset.label ?? artworkNames[kind];
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
    } else if (platform !== "snes") {
      entry.append(newTabLink(manual.name, manual.url));
    } else {
      entry.append(element("span", manual.name));
    }
    const info = platform !== "snes"
      ? [...manual.regions, manual.language, manual.format, manual.source].filter(Boolean).join(" · ")
      : manual.localUrl ? [manual.format, manual.language].filter(Boolean).join(" · ") : "Unavailable locally";
    if (info) entry.append(element("small", info));
    return entry;
  }));
}

function releaseTableManuals(game, release) {
  if (!neoGeo || release.market !== "MVS" || release.manuals?.length) return release.manuals || [];
  const aes = game.releases.find(other => other.market === "AES");
  return (aes?.manuals || []).map(manual => ({...manual, name: manual.name.replace(/ — Game manual$/, " — AES manual")}));
}

function openRomDownload(download) {
  romDownload = download;
  const discs = Boolean(download.discDownloadSize);
  const label = download.manifestUrl ? "Download arcade bundle"
    : download.archiveName ? download.archiveLabel
    : discs ? "Download disc set" : "Download ROM";
  document.querySelector("#snes-rom-title").textContent = (download.manifestUrl || download.archiveName) ? label
    : discs ? "Download translated disc set" : "Download translated ROM";
  romSubmit.textContent = label;
  romKey.value = rememberedRomKey;
  romStatus.hidden = true;
  romDialog.showModal();
  if (rememberedRomKey) romForm.requestSubmit();
}

function submitDownload(url, key) {
  const form = element("form");
  form.method = "post";
  form.action = url;
  form.hidden = true;
  const input = element("input");
  input.type = "hidden";
  input.name = "key";
  input.value = key;
  form.append(input);
  document.body.append(form);
  form.submit();
  form.remove();
}

romForm.addEventListener("submit", async event => {
  event.preventDefault();
  if (romRequest || !romDownload) return;
  const key = romKey.value.trim();
  const download = romDownload;
  const discs = Boolean(download.discDownloadSize);
  const arcade = Boolean(download.manifestUrl);
  const originalArchive = Boolean(download.archiveName);
  const request = new AbortController();
  romRequest = request;
  romSubmit.disabled = true;
  romStatus.textContent = arcade ? "Checking arcade ROMs…" : (discs || originalArchive)
    ? "Preparing archive download…" : "Building translated ROM…";
  romStatus.hidden = false;
  try {
    const response = await fetch(download.manifestUrl || download.installManifestUrl || download.romDownloadUrl, {
      method: discs ? "HEAD" : "GET",
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
      throw new Error(error?.error || "The download could not be prepared.");
    }
    if (arcade) {
      const manifest = await response.json();
      if (request.signal.aborted) return;
      if (!manifest.complete || !manifest.bundleUrl) throw new Error("Required arcade files are unavailable.");
      submitDownload(manifest.bundleUrl, key);
    } else if (originalArchive) {
      const manifest = await response.json();
      if (request.signal.aborted) return;
      const file = manifest.packages?.find(item => item.archiveName === download.archiveName);
      if (!file?.downloadUrl) throw new Error("This archive is unavailable.");
      submitDownload(file.downloadUrl, key);
    } else if (discs) {
      submitDownload(download.romDownloadUrl, key);
    } else {
      const file = await response.blob();
      if (request.signal.aborted) return;
      const encoded = response.headers.get("Content-Disposition")?.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
      const extension = download.extension ? `.${download.extension}` : romExtension;
      const name = encoded ? decodeURIComponent(encoded) : download.filename.replace(/\.[^.]+$/, extension);
      const url = URL.createObjectURL(file);
      const link = element("a");
      link.href = url;
      link.download = name;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
    }
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
    "ines-payload-only": "Targets the ROM data without the iNES header",
    "ines-file-only": "Targets an iNES image",
    "ines-unconfirmed": "Check the patch’s iNES header instructions",
    z64: "Big-endian .z64 input",
    v64: "Byte-swapped .v64 input",
    n64: "Little-endian .n64 input",
    ndd: "64DD disk image input",
    neosd: "Requires a NeoSD .neo image",
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
  const downloads = element("div", "", "snes-patch-downloads");
  if (translation.url) {
    const link = element("a", translation.filename);
    link.href = translation.url;
    link.download = translation.filename;
    downloads.append(link);
  }
  if (translation.installManifestUrl) {
    const names = translation.archiveNames;
    names.forEach((archiveName, index) => {
      const archiveLabel = names.length > 1 ? `Download disc ${index + 1}` : "Download patched disc";
      const download = element("button", archiveLabel, "snes-text-button");
      download.type = "button";
      download.setAttribute("aria-haspopup", "dialog");
      download.setAttribute("aria-label", `Download ${archiveName}`);
      download.addEventListener("click", () => openRomDownload({
        archiveName, archiveLabel, installManifestUrl: translation.installManifestUrl,
      }));
      downloads.append(download);
    });
  }
  if (translation.romDownloadUrl) {
    const label = translation.discDownloadSize ? "Download disc set" : translation.layout === "ndd" ? "Download disk" : "Download ROM";
    const download = element("button", label, "snes-text-button");
    download.type = "button";
    download.setAttribute("aria-haspopup", "dialog");
    download.setAttribute("aria-label", `${label} using ${translation.filename}`);
    download.addEventListener("click", () => openRomDownload(translation));
    downloads.append(download);
  }
  patch.append(downloads);
  const status = translation.status === "Fully Playable" ? "" : translation.status;
  const padding = translation.padToSize
    ? `Pad the base ROM to ${(translation.padToSize / 1024).toLocaleString()} KiB with zero bytes`
    : "";
  const info = [status, translation.baseEdition, inputLayouts[translation.layout], padding]
    .filter(Boolean).join(" · ");
  if (info) patch.append(element("small", info));
  if (translation.discDownloadSize) {
    const count = translation.baseDiscs.length;
    const size = translation.discDownloadSize / (1024 ** 2);
    patch.append(element("small", `${count} ${count === 1 ? "disc" : "discs"} · ${number.format(Math.round(size))} MiB ZIP`));
  }
  if (translation.sourceUrl && (translation.discDownloadSize || !translation.romDownloadUrl)) {
    const label = translation.discDownloadSize ? "Project notes" : "Patch instructions";
    patch.append(newTabLink(label, translation.sourceUrl));
  }
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
  if (release.includedIn) {
    const link = element("a", release.includedIn.title);
    const query = new URLSearchParams({game: release.includedIn.key, market: release.market});
    if (release.includedIn.release) query.set("release", release.includedIn.release);
    if (release.hardware) query.set("hardware", release.hardware);
    link.href = `${location.pathname}?${query}`;
    return releaseListCell([link]);
  }
  if (release.channel === "built-in") return element("td", "Included in the console BIOS");
  if (neoGeo && !discRelease(release)) {
    const sets = release.arcadeSets || [];
    if (!sets.length) {
      return element("td", release.setNames.length ? "No matching arcade set" : "See the MVS release for arcade sets");
    }
    return releaseListCell(sets.map(set => {
      const entry = element("div");
      const emulator = set.emulator === "FBNeo" ? "FinalBurn Neo" : set.emulator;
      const label = `${set.setName}.zip · ${emulator} ${set.version}`;
      const link = element("a", label);
      link.href = `/software/${set.softwareId}-${set.softwareKey}#releases`;
      entry.append(link);
      if (set.complete) {
        const button = element("button", "Download bundle", "snes-text-button");
        button.type = "button";
        button.setAttribute("aria-haspopup", "dialog");
        button.setAttribute("aria-label", `Download bundle for ${label}`);
        const manifestUrl = `/api/v1/releases/${set.installSignature}/install-manifest`;
        button.addEventListener("click", () => openRomDownload({manifestUrl}));
        const action = element("small");
        action.append(button);
        entry.append(action);
        if (set.singleCabinet) entry.append(element("small", "Single-cabinet play"));
      } else {
        const reason = set.issues?.includes("undumped") ? "Undumped chip listed in the DAT" : "Required files missing";
        entry.append(element("small", reason));
      }
      return entry;
    }));
  }
  const matched = release.status === "matched";
  const archives = matched ? release.archives : release.candidates;
  const entries = (archives || []).map(archive => {
    function archiveLink(name) {
      if (!matched) return element("span", name);
      const link = element("a", name);
      link.href = `/software/${archive.softwareId}-${archive.softwareKey}#releases`;
      const downloadLabel = addonDownloads[release.hardware]
        || (jaguar ? "Download cartridge" : classicCartridge ? "Download ROM"
          : (saturn || earlyDisc || sixthGeneration || cdAddons.has(release.hardware)) ? "Download disc" : "");
      if (downloadLabel && archive.installManifestUrl) {
        const download = element("button", downloadLabel, "snes-text-button");
        download.type = "button";
        download.setAttribute("aria-haspopup", "dialog");
        download.setAttribute("aria-label", `Download ${name}`);
        download.addEventListener("click", () => openRomDownload({
          installManifestUrl: archive.installManifestUrl, archiveName: name, archiveLabel: downloadLabel,
        }));
        const entry = element("div");
        const action = element("small");
        action.append(download);
        entry.append(link, action);
        return entry;
      }
      return link;
    }
    if (archive.discs?.length > 1) {
      const revisions = archive.revisions.map(value => `Rev ${value}`);
      const label = [archive.pressing, `${archive.discs.length} discs`, ...revisions, ...archive.versions]
        .filter(Boolean).join(" · ");
      return releaseDisclosure(label, releaseList(archive.discs.map(disc => archiveLink(disc.name))));
    }
    return archiveLink(archive.archiveNames.join(" · "));
  });
  const cell = releaseListCell(entries);
  if (!matched) {
    if (!entries.length) cell.replaceChildren();
    const message = release.status === "unmatched" && discRelease(release) ? "No verified discs" : matchNames[release.status];
    const status = element("p", release.dumpSource ? "Local ROM unavailable" : message, "snes-release-status");
    if (release.dumpSource) status.append(" · ", newTabLink(release.dumpSource.name, release.dumpSource.url));
    cell.prepend(status);
  }
  if (release.reviewNote?.text && (!matched || release.reviewNote.showWhenMatched)) {
    const note = element("small", release.reviewNote.text);
    if (release.reviewNote.source?.url) {
      note.append(" ", newTabLink(release.reviewNote.source.name, release.reviewNote.source.url));
    }
    cell.append(note);
    const related = release.reviewNote.related;
    if (related?.url) {
      const link = element("a", related.name);
      link.href = related.url;
      const row = element("p", "", "snes-release-status");
      row.append(link);
      cell.append(row);
    }
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
  setReleaseColumns(header, columns);
  table.createTBody().setAttribute("role", "rowgroup");
  return table;
}

function setReleaseColumns(header, columns) {
  header.replaceChildren(...columns.map(label => {
    const cell = element("th", label);
    cell.scope = "col";
    cell.setAttribute("role", "columnheader");
    return cell;
  }));
}

function labelReleaseCells(cells, columns) {
  for (const [index, cell] of cells.entries()) {
    cell.setAttribute("role", "cell");
    const label = element("span", columns[index + 1], "snes-mobile-label");
    label.setAttribute("aria-hidden", "true");
    cell.prepend(label);
  }
}

function releaseColumns(release) {
  return discRelease(release) ? ["Market", "Released", "Manuals", "Verified discs", "Serials"]
    : neoGeo ? ["Release", "Released", "Manuals and instructions", "Arcade sets", "Cartridge no."]
    : jaguar ? ["Market", "Released", "Manuals", "ROM archives"]
    : ["Market", "Released", "Manuals", "ROM archives", "Product code", ...(pcEngine || classicCartridge ? [] : ["PCB"])];
}

function renderReleaseTable(game, picker, hardwarePicker, targets, onSelection) {
  const table = releaseTable("Releases", releaseColumns(game.releases[0]));
  table.id = "snes-releases";
  const body = table.tBodies[0];
  const rows = game.releases.map(release => {
    const columns = releaseColumns(release);
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
    const date = element("td", release.date || "—");
    const medium = release.medium || channelNames[release.channel];
    if (medium) date.append(element("small", medium));
    const dateSource = (masterSystem || nintendo64 || classicCartridge) && (release.dateSource || release.source);
    if (dateSource?.url) {
      const citation = element("small");
      citation.append(newTabLink(dateSource.name, dateSource.url));
      date.append(citation);
    }
    const {serials, headerCodes, boards, chips} = cartridgeDetails(release);
    const productCodes = releaseListCell((release.productCodes || serials).map(code => element("code", code)));
    if (headerCodes.length) {
      productCodes.querySelector(".snes-release-empty")?.remove();
      productCodes.append(releaseDisclosure("ROM header", releaseList(headerCodes.map(code => element("code", code)))));
    }
    const pcb = releaseListCell(boards.map(code => element("code", code)));
    if (chips.length) {
      pcb.append(releaseDisclosure(chips.length === 1 ? "ROM chip" : "ROM chips",
        releaseList(chips.map(chip => element("code", chip)))));
    }
    const cells = [date, manualCell(releaseTableManuals(game, release)), romCell(release)];
    if (!jaguar) cells.push(productCodes);
    if (!discRelease(release) && !neoGeo && !pcEngine && !jaguar && !classicCartridge) cells.push(pcb);
    labelReleaseCells(cells, columns);
    row.append(market, ...cells);
    const flag = element("button", "", "snes-region-button");
    flag.type = "button";
    const name = title === game.title ? marketNames[release.market] : `${marketNames[release.market]} · ${title}`;
    flag.title = name;
    flag.setAttribute("aria-label", name);
    flag.setAttribute("aria-controls", `${targets} ${table.id}`);
    flag.append(marketFlag(release.market));
    if (game.releases.some(other => other !== release && other.market === release.market
      && releaseHardware(other) === releaseHardware(release))) {
      flag.append(element("span", title));
    }
    picker.append(flag);
    return {row, flag, release, columns};
  });
  const hardwareButtons = new Map();
  const hardware = new Set(game.releases.map(releaseHardware));
  hardwarePicker.hidden = hardware.size < 2;
  let current;
  function select(entry) {
    if (!entry || current === entry) return;
    if (!current || discRelease(current.release) !== discRelease(entry.release)) {
      setReleaseColumns(table.tHead.rows[0], entry.columns);
    }
    current = entry;
    body.replaceChildren(entry.row);
    const currentHardware = releaseHardware(entry.release);
    let visible = 0;
    for (const candidate of rows) {
      candidate.flag.hidden = releaseHardware(candidate.release) !== currentHardware;
      if (!candidate.flag.hidden) visible += 1;
      candidate.flag.setAttribute("aria-pressed", String(candidate === entry));
    }
    picker.hidden = visible < 2;
    for (const [key, button] of hardwareButtons) {
      button.setAttribute("aria-pressed", String(key === currentHardware));
    }
    onSelection(entry.release);
  }
  if (!hardwarePicker.hidden) {
    for (const key of hardware) {
      const name = hardwareNames[key];
      const button = element("button", hardwareLabels[key] || name, "snes-region-button");
      button.type = "button";
      button.title = name;
      button.setAttribute("aria-label", name);
      button.setAttribute("aria-controls", `${picker.id} ${targets} ${table.id}`);
      button.addEventListener("click", () => {
        if (current && releaseHardware(current.release) === key) return;
        const options = rows.filter(({release}) => releaseHardware(release) === key);
        select(options.find(({release}) => release.market === current?.release.market && release.status === "matched")
          || options.find(({release}) => release.status === "matched") || options[0]);
      });
      hardwareButtons.set(key, button);
      hardwarePicker.append(button);
    }
  }
  for (const entry of rows) {
    entry.flag.addEventListener("click", () => select(entry));
  }
  const defaultMarket = neoGeo && game.releases.some(hasAesCover) ? "AES" : null;
  const selectedMarket = params.get("market") || defaultMarket;
  const selectedStatus = params.get("match") || "matched";
  const selectedRelease = params.get("release");
  const requested = rows.filter(({release}) => supportsHardware(release, params.get("hardware")));
  const options = requested.length ? requested : rows;
  const selected = rows.find(({release}) => release.key === selectedRelease)
    || options.find(({release}) => release.status === selectedStatus &&
      (!selectedMarket || release.market === selectedMarket))
    || options.find(({release}) => release.market === selectedMarket)
    || options.find(({release}) => release.status === "matched")
    || options[0];
  if (selected) select(selected);
  return table;
}

function renderSoundtrackSources(container, sources) {
  const group = element("div");
  const status = element("p", "", "summary");
  status.setAttribute("role", "status");
  status.hidden = true;
  const entries = sources.map(source => {
    if (!source.loadUrl) return newTabLink(source.title, source.url);
    const label = sources.length === 1 ? "Load soundtrack" : `Load ${source.title.replace(/ — JoshW archive$/, "")}`;
    const button = element("button", label, "secondary-button");
    button.type = "button";
    button.addEventListener("click", async () => {
      const buttons = [...group.querySelectorAll("button")];
      buttons.forEach(item => { item.disabled = true; });
      status.hidden = false;
      status.textContent = "Preparing soundtrack…";
      try {
        let response = await fetch(source.loadUrl, {method: "POST"});
        while (response.status === 202) {
          await new Promise(resolve => setTimeout(resolve, 1400));
          if (!button.isConnected) return;
          response = await fetch(source.loadUrl);
        }
        if (!button.isConnected) return;
        const album = await response.json().catch(() => ({}));
        if (!response.ok || !album.assets?.length) {
          status.textContent = album.message || "The soundtrack could not be loaded.";
          return;
        }
        container.replaceChildren();
        renderSoundtracks(container, [album], {compact: true});
      } catch {
        status.textContent = "The soundtrack could not be loaded.";
      } finally {
        buttons.forEach(item => { item.disabled = false; });
      }
    });
    const entry = element("span");
    entry.append(button, " ", newTabLink("JoshW archive", source.url));
    return entry;
  });
  group.append(releaseList(entries), status);
  container.append(group);
}

function renderDetail(game, soundtracks) {
  if (!game) {
    status.textContent = "This retail catalog entry could not be found.";
    return;
  }
  const browseParams = browseParameters({
    query: params.get("q"), hardware: params.get("hardware"), genre: params.get("genre"),
    translated: params.get("translated") === "1",
  }, page);
  const back = document.querySelector("#snes-back");
  back.href = location.pathname + (browseParams.size ? `?${browseParams}` : "");
  back.hidden = false;

  const masthead = element("header", "", "snes-game-heading");
  const title = document.querySelector("#snes-title");
  const pageHeading = title.parentElement;
  const switches = element("div", "", "snes-release-picker");
  switches.hidden = game.releases.length < 2;
  const hardwarePicker = element("div", "", "snes-release-buttons");
  hardwarePicker.setAttribute("role", "group");
  hardwarePicker.setAttribute("aria-label", "Release hardware");
  const picker = element("div", "", "snes-release-buttons");
  picker.id = "snes-release-markets";
  picker.setAttribute("role", "group");
  picker.setAttribute("aria-label", neoGeo ? "Cartridge releases" : "Regional releases");
  switches.append(hardwarePicker, picker);
  masthead.append(switches);

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
      ["Genre", metadata.genres?.join(" · ") || release.genre], ["Players", release.players],
      ["Controls", discRelease(release) || classicCartridge ? release.accessories : renderInputs(metadata)],
      ["Required hardware", release.requiredAccessories?.join(" · ")],
      ["Memory card", release.memoryCard], ["ESRB", release.rating],
    ], {inline: true});
    const editionDescription = release.description ? renderDescription(release.description.text) : description;
    profile.replaceChildren(...[editionDescription, facts.childElementCount ? facts : null].filter(Boolean));
    const art = renderArt(release);
    const manual = release.manuals?.find(candidate => candidate.localUrl);
    if (manual) art.append(renderManualCover(manual));
    gallery.replaceChildren(art);
    gallery.hidden = !art.childElementCount;
    const albums = soundtracks.filter(album => album.releases.includes(release.key)).sort((first, second) =>
      Number(second.titleMatches.includes(release.key)) - Number(first.titleMatches.includes(release.key)));
    const sources = (game.soundtrackSources || []).filter(source => source.releases.includes(release.key));
    const current = [...albums.map(album => album.key), ...sources.map(source => source.url)];
    if (current.length === currentAlbums.length && current.every(key => currentAlbums.includes(key))) return;
    currentAlbums = current;
    pauseAudio(player);
    player.replaceChildren();
    soundtrack.hidden = !current.length;
    if (albums.length) renderSoundtracks(player, albums, {compact: true});
    if (sources.length && !albums.length) renderSoundtrackSources(player, sources);
  }

  const releases = renderReleaseTable(
    game, picker, hardwarePicker, `${gallery.id} ${soundtrack.id} ${translations.id}`, showRelease,
  );
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
  document.title = `${catalogLabel} retail catalog | GameDB`;
  const key = params.get("game");
  const heading = document.querySelector("#snes-title");
  heading.textContent = catalogLabel;
  if (!key) {
    const plate = element("span", "", "snes-platform-logo");
    plate.dataset.platform = platform;
    const logo = element("img");
    logo.alt = catalogLabel;
    logo.addEventListener("error", () => { heading.textContent = catalogLabel; }, {once: true});
    const filename = platform === "odyssey2" ? "odyssey2-wordmark" : platform;
    logo.src = `/system-icons/retail-logo-${filename}.png`;
    if (["copera", "myvision", "picno"].includes(platform)) {
      const crop = element("span", "", "system-logo-crop");
      crop.dataset.platform = platform;
      crop.append(logo);
      plate.append(crop);
    } else {
      plate.append(logo);
    }
    heading.replaceChildren(plate);
  }
  document.querySelector("#snes-back").textContent = `← ${catalogLabel} catalog`;
  try {
    const query = new URLSearchParams(key ? {game: key} : {view: "browse"});
    const response = await fetch(`${catalogApi}?${query}`);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `Could not load the ${catalogLabel} retail catalog.`);
    const source = document.querySelector("#snes-source-link");
    source.href = payload.source.url;
    source.textContent = payload.source.name;
    const license = document.querySelector("#snes-source-license");
    license.hidden = !payload.source.license;
    if (payload.source.license) license.href = payload.source.license;
    const addonCredits = document.querySelector("#snes-addon-sources");
    for (const [hardware, credit] of Object.entries(payload.addonSources || {})) {
      addonCredits.append(" · ", newTabLink(`${hardwareNames[hardware]} release list`, credit.url));
      if (credit.license) addonCredits.append(" ", newTabLink("CC BY-SA 4.0", credit.license));
    }
    document.querySelector("#snes-source").hidden = false;
    if (key) {
      renderDetail(payload.game, payload.soundtracks || []);
      return;
    }
    games = payload.games.map(game => ({
      ...game, genres: game.genres || [], searchText: searchKey([game.title, ...game.aliases.map(alias => alias.title),
        ...game.releases.flatMap(release => [...release.titles, ...release.archiveTitles,
          ...(release.productCodes || [])])].join(" ")),
    }));
    search.value = params.get("q") || "";
    if (optical) search.placeholder = "Search by title or serial";
    if (neoGeo) search.placeholder = "Search by title, cartridge number, or set";
    if (pcEngine || classicCartridge) search.placeholder = "Search by title or product code";
    const addons = Object.keys(payload.addonSources || {});
    if (addons.length) {
      const hardware = [...(neoGeo ? ["mvs", "aes"] : [platform]), ...addons];
      for (const key of hardware) hardwareSelect.add(new Option(hardwareNames[key], key));
      hardwareSelect.value = hardware.includes(params.get("hardware")) ? params.get("hardware") : "";
      hardwareSelect.hidden = false;
    }
    const genres = [...new Set(games.flatMap(game => game.genres))].sort((a, b) => a.localeCompare(b));
    for (const genre of genres) genreSelect.add(new Option(genre, genre));
    genreSelect.disabled = !genres.length;
    genreSelect.value = genres.includes(params.get("genre")) ? params.get("genre") : "";
    const hasTranslations = games.some(game => game.releases.some(release => release.hasTranslations));
    translationFilter.closest("label").hidden = !hasTranslations;
    translationFilter.checked = hasTranslations && params.get("translated") === "1";
    function updateFilters() {
      pageAnchor = 0;
      renderBrowse();
    }
    search.addEventListener("input", updateFilters);
    hardwareSelect.addEventListener("change", updateFilters);
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
    heading.hidden = false;
  }
}

start();
