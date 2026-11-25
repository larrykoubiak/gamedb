const catalogView = document.querySelector("#catalog-view");
const almanacView = document.querySelector("#almanac-view");
const catalogHome = document.querySelector("#catalog-home");
const backToCatalog = document.querySelector("#back-to-catalog");
const book = document.querySelector("#software-book");
const bookTitle = document.querySelector("#software-title");
const bookPlatform = document.querySelector("#software-platform");
const bookCover = document.querySelector("#software-cover");
const bookGlance = document.querySelector("#software-glance");
const bookPanel = document.querySelector("#software-section");
const bookStatus = document.querySelector("#almanac-status");
const bookTabs = [...document.querySelectorAll(".book-tabs [role=tab]")];
const detailPath = /^\/software\/(?:[1-9][0-9]{0,18}-[0-9a-f]{32}|exo\/[0-9a-f]{64})$/;
let entry;
let catalogStarted = false;
let catalogPosition;

function pageRequest(page, name, load) {
  if (!page.requests.has(name)) {
    page.requests.set(name, load().catch(error => {
      page.requests.delete(name);
      throw error;
    }));
  }
  return page.requests.get(name);
}

function sourceDetails(page) {
  if (page.source || !page.game.sourceDetailKey) return Promise.resolve(page.source);
  return pageRequest(page, "source", () => requestJson("/api/exo/" + page.game.sourceDetailKey));
}

function gameData(page, name) {
  if (page.game.sourceOnly) return Promise.resolve([]);
  const path = `/api/software/${page.game.softwareId}/${name}`;
  return pageRequest(page, name, () => requestJson(path + (page.hideRomHacks ? "?hide_rom_hacks=1" : "")));
}

function note(text) {
  const item = cellText("p", text);
  item.className = "book-note";
  return item;
}

function preferredFact(facts, name) {
  return facts.find(fact => fact.key === name)?.preferredValues || [];
}

function overviewNarrative(container, facts) {
  const description = preferredFact(facts, "description")[0];
  if (description) {
    const lead = cellText("p", description);
    lead.className = "book-description";
    container.append(lead);
    const providers = [...new Set(facts.find(fact => fact.key === "description").values
      .filter(claim => claim.value === description)
      .map(claim => ({launchbox: "LaunchBox", "libretro-database": "Libretro", exo: "eXo"})[claim.sourceProvider])
      .filter(Boolean))];
    if (providers.length) {
      const credit = cellText("p", providers.join(" · "));
      credit.className = "book-credit";
      container.append(credit);
    }
  } else {
    container.append(note("No description is available for this software."));
  }
  if (facts.length) {
    const evidence = document.createElement("details");
    evidence.className = "book-evidence";
    evidence.append(cellText("summary", "Metadata and sources"));
    renderSoftwareFacts(evidence, facts);
    container.append(evidence);
  }
}

function renderOverviewFacts(facts, game) {
  const preferred = name => preferredFact(facts, name);
  const fields = [
    ["Developer", preferred("developer")], ["Publisher", preferred("publisher")],
    ["Genre", preferred("genre")], ["Players", preferred("player_count")],
    ["Release dates", game.releaseDates], ["Regions", game.regions],
    ["Series", preferred("franchise")], ["Preferred source", [game.sourceCollection].filter(Boolean)],
  ].filter(([, values]) => values?.length);
  if (fields.length) {
    const grid = document.createElement("dl");
    grid.className = "book-facts";
    for (const [label, values] of fields) {
      const pair = document.createElement("div");
      pair.append(cellText("dt", label), cellText("dd", values.join(" · ")));
      grid.append(pair);
    }
    bookGlance.replaceChildren(grid);
  }
}

async function sectionContent(page, section) {
  const content = document.createDocumentFragment();
  const {game} = page;
  if (section === "overview") {
    const facts = game.sourceOnly
      ? sourceFacts(await sourceDetails(page), game.sourceEntryKey)
      : await gameData(page, "facts");
    page.overviewFacts = facts;
    overviewNarrative(content, facts);
    return content;
  }

  if (section === "releases") {
    const [ranked, editions] = await Promise.allSettled([gameData(page, "releases"), sourceDetails(page)]);
    if (ranked.value?.length) {
      renderRankedReleases(content, ranked.value, game.softwareId, game.systemId, Boolean(game.preferredEditionKey));
    }
    if (editions.value) {
      renderSourceEditions(content, editions.value, game);
      renderSourceRecords(content, editions.value, game.sourceEntryKey);
    }
    if (ranked.status === "rejected" || editions.status === "rejected") {
      content.append(note("Some release information could not be loaded."));
    }
    if (!content.childNodes.length) content.append(note("No releases are available for this software."));
    return content;
  }

  const [related, music] = await Promise.allSettled([
    sourceDetails(page),
    section === "soundtracks" && state.vgmEnabled ? gameData(page, "soundtracks") : [],
  ]);
  const attachments = related.value?.assets || [];
  if (section === "artwork") {
    renderArtworkGallery(content, game.media, game.title, attachments.filter(asset => asset.kind === "artwork"));
  } else if (section === "soundtracks") {
    const albums = [...(music.value || [])];
    const sourceMusic = attachments.filter(asset => asset.kind === "music");
    if (sourceMusic.length) albums.push(sourceMusicAlbum(game.title, sourceMusic));
    renderSoundtracks(content, albums);
  } else {
    renderSourceAssets(content, attachments.filter(asset => asset.kind !== "artwork" && asset.kind !== "music"));
  }
  if (related.status === "rejected" || music.status === "rejected") {
    content.append(note("Some media could not be loaded."));
  }
  if (!content.childNodes.length) {
    content.append(note({
      artwork: "No artwork is available for this software.",
      media: "No related media is linked to this software.",
      soundtracks: state.vgmEnabled || game.sourceOnly
        ? "No soundtracks are linked to this software."
        : "Soundtrack serving is disabled on this Explorer.",
    }[section]));
  }
  return content;
}

async function selectBookTab(tab) {
  const page = entry;
  if (!page?.game || page.tab === tab) return;
  page.tab = tab;
  const sequence = ++page.sequence;
  const section = tab.dataset.section;
  book.dataset.section = section;
  bookGlance.hidden = section !== "overview";
  for (const button of bookTabs) {
    const selected = button === tab;
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
  }
  pauseAudio(bookPanel);
  bookPanel.setAttribute("aria-labelledby", tab.id);
  bookPanel.setAttribute("aria-busy", "true");
  bookPanel.replaceChildren(cellText("h2", tab.textContent.trim()));
  const loading = note("Loading…");
  loading.setAttribute("role", "status");
  bookPanel.append(loading);
  try {
    const content = await sectionContent(page, section);
    if (entry !== page || sequence !== page.sequence) return;
    loading.replaceWith(content);
    if (section === "overview") renderOverviewFacts(page.overviewFacts, page.game);
  } catch (error) {
    if (entry !== page || sequence !== page.sequence) return;
    loading.textContent = error.message;
  }
  bookPanel.removeAttribute("aria-busy");
}

function activeBookTab() {
  return bookTabs.find(tab => `#${tab.dataset.section}` === location.hash) || bookTabs[0];
}

for (const tab of bookTabs) {
  tab.addEventListener("click", () => {
    const hash = tab === bookTabs[0] ? "" : "#" + tab.dataset.section;
    history.replaceState(history.state, "", location.pathname + location.search + hash);
    if (book.getBoundingClientRect().top < 0) book.scrollIntoView({block: "start"});
    selectBookTab(tab);
  });
  tab.addEventListener("keydown", event => {
    const index = bookTabs.indexOf(tab);
    const last = bookTabs.length - 1;
    const next = {
      Home: 0, End: last, ArrowUp: (index + last) % bookTabs.length,
      ArrowDown: (index + 1) % bookTabs.length, ArrowLeft: (index + last) % bookTabs.length,
      ArrowRight: (index + 1) % bookTabs.length,
    }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    bookTabs[next].focus();
  });
}

const narrowBook = matchMedia("(max-width: 960px)");
function orientTabs() {
  bookTabs[0].parentElement.setAttribute("aria-orientation", narrowBook.matches ? "horizontal" : "vertical");
}
orientTabs();
narrowBook.addEventListener("change", orientTabs);

async function openSoftwarePage(path, focus) {
  pauseAudio(document);
  const page = {path, requests: new Map(), sequence: 0};
  entry = page;
  catalogView.hidden = true;
  almanacView.hidden = false;
  catalogHome.removeAttribute("aria-current");
  backToCatalog.hidden = false;
  book.hidden = true;
  bookStatus.hidden = false;
  bookStatus.textContent = "Opening software entry…";
  document.title = "GameDB Almanac";
  window.scrollTo(0, 0);
  if (focus) bookStatus.focus({preventScroll: true});
  try {
    const [payload] = await Promise.all([requestJson(browseUrl("/api" + path)), loadInterfaceOptions()]);
    if (entry !== page) return;
    Object.assign(page, payload);
    const {game} = page;
    document.title = `${game.title} · GameDB Almanac`;
    bookTitle.textContent = game.title;
    bookPlatform.replaceChildren(platformIcon(game.manufacturer, game.systemName),
      cellText("span", [game.manufacturer, game.systemName].filter(Boolean).join(" · ")));
    bookCover.replaceChildren();
    bookGlance.replaceChildren();
    renderCover(bookCover, game, 320, {eager: true});
    bookStatus.hidden = true;
    book.hidden = false;
    selectBookTab(activeBookTab());
    if (focus) bookTitle.focus({preventScroll: true});
  } catch (error) {
    if (entry === page) bookStatus.textContent = error.message;
  }
}

function routePage(focus = false) {
  const path = location.pathname;
  if (detailPath.test(path)) {
    if (entry?.path === path) selectBookTab(activeBookTab());
    else openSoftwarePage(path, focus);
    return;
  }
  pauseAudio(almanacView);
  entry = null;
  catalogView.hidden = false;
  almanacView.hidden = true;
  catalogHome.setAttribute("aria-current", "page");
  backToCatalog.hidden = true;
  document.title = "V1 archive | GameDB";
  if (!catalogStarted) {
    catalogStarted = true;
    startCatalog();
  }
  if (catalogPosition) {
    window.scrollTo(0, catalogPosition.scroll);
    const focusTarget = catalogPosition.link.isConnected ? catalogPosition.link : gameFilter;
    focusTarget.focus({preventScroll: true});
  }
}

function ordinaryClick(event) {
  return event.button === 0 && !event.defaultPrevented && !event.metaKey
    && !event.ctrlKey && !event.shiftKey && !event.altKey;
}

catalogView.addEventListener("click", event => {
  const link = event.target.closest("a.software-link");
  if (!link || !ordinaryClick(event)) return;
  event.preventDefault();
  catalogPosition = {link, scroll: window.scrollY};
  history.pushState({fromCatalog: true}, "", link.href);
  routePage(true);
});

for (const link of [catalogHome, backToCatalog]) {
  link.addEventListener("click", event => {
    if (!entry || !ordinaryClick(event) || !history.state?.fromCatalog) return;
    event.preventDefault();
    history.back();
  });
}

document.addEventListener("catalog-rebuilt", () => {
  if (catalogStarted) selectSystem(state.selectedSystem, state.page);
  if (entry) openSoftwarePage(entry.path, true);
});

history.scrollRestoration = "manual";
window.addEventListener("popstate", () => routePage(true));
window.addEventListener("hashchange", () => routePage());
routePage();
