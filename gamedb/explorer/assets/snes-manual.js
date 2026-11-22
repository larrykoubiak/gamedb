"use strict";

const manualDialog = document.querySelector("#snes-manual-dialog");
const manualBook = document.querySelector("#snes-manual-book");
const manualStatus = document.querySelector("#snes-manual-status");
const manualNavigation = document.querySelector("#snes-manual-navigation");
const manualPosition = document.querySelector("#snes-manual-position");
const manualPrevious = document.querySelector("#snes-manual-previous");
const manualNext = document.querySelector("#snes-manual-next");
const facingPages = matchMedia("(min-width: 44rem)");
const manualReducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
let manualSession;

function groupManualPages(pages) {
  const spreads = [];
  for (let page = 1; page <= pages.length; page++) {
    const spread = [page];
    if (facingPages.matches && page > 1 && page < pages.length &&
        pages[page - 1][0] <= pages[page - 1][1] && pages[page][0] <= pages[page][1]) {
      spread.push(++page);
    }
    spreads.push(spread);
  }
  return spreads;
}

function manualPage(session, page) {
  if (!session.images.has(page)) {
    const image = new Image();
    image.alt = `Page ${page}`;
    image.src = `${session.url}/${page}.webp`;
    const loading = image.decode().then(() => image);
    session.images.set(page, loading);
    loading.catch(() => {
      if (session.images.get(page) === loading) session.images.delete(page);
    });
  }
  return session.images.get(page);
}

function prefetchManualPages(session) {
  const {index, spreads, images} = session;
  const nearby = new Set(spreads.slice(Math.max(0, index - 1), index + 2).flat());
  for (const page of images.keys()) {
    if (!nearby.has(page)) images.delete(page);
  }
  for (const page of nearby) manualPage(session, page).catch(() => {});
}

function turnManualLeaf(session, images, direction) {
  if (!direction || manualReducedMotion.matches) return;
  const forward = direction > 0;
  const previous = session.visibleImages;
  if (previous.length === 2 && images.length === 2) {
    const leaf = document.createElement("span");
    leaf.className = "snes-manual-leaf";
    leaf.classList.toggle("is-forward", forward);
    leaf.setAttribute("aria-hidden", "true");
    leaf.append(previous[forward ? 1 : 0], images[forward ? 0 : 1]);
    manualBook.replaceChildren(forward ? previous[0] : images[0], forward ? images[1] : previous[1], leaf);
    session.animation = leaf.animate([
      {transform: "rotateY(0deg)"},
      {transform: `rotateY(${forward ? -90 : 90}deg) scaleY(.91)`},
      {transform: `rotateY(${forward ? -180 : 180}deg)`},
    ], {duration: 460, easing: "ease-in-out", fill: "forwards"});
  } else {
    manualBook.replaceChildren(...images);
    session.animation = manualBook.animate([
      {transform: `rotateY(${forward ? 18 : -18}deg)`, opacity: .65},
      {transform: "rotateY(0deg)", opacity: 1},
    ], {duration: 280, easing: "ease-out"});
  }
  return session.animation.finished.catch(() => {});
}

function manualMessage(text) {
  manualStatus.textContent = text;
  manualStatus.hidden = !text;
}

async function showManualSpread(session, index, direction = 0) {
  const request = ++session.request;
  const current = () => manualDialog.open && manualSession === session && session.request === request;
  session.animation?.cancel();
  session.pending = true;
  manualPrevious.disabled = true;
  manualNext.disabled = true;
  const spread = session.spreads[index];
  try {
    const images = await Promise.all(spread.map(page => manualPage(session, page)));
    if (!current()) return;
    const ratio = spread.reduce((sum, page) => {
      const [width, height] = session.pages[page - 1];
      return sum + width / height;
    }, 0);
    manualBook.style.setProperty("--manual-ratio", ratio);
    manualBook.classList.toggle("is-spread", spread.length === 2);
    manualBook.hidden = false;
    manualMessage("");
    await turnManualLeaf(session, images, direction);
    if (!current()) return;
    manualBook.replaceChildren(...images);
    session.visibleImages = images;
    session.index = index;
    if (direction) session.anchor = spread[0];
    const label = spread.length === 2 ? `Pages ${spread[0]}–${spread[1]}` : `Page ${spread[0]}`;
    manualPosition.textContent = `${label} of ${session.pages.length}`;
    manualNavigation.hidden = false;
    prefetchManualPages(session);
  } catch {
    if (current()) manualMessage("A page could not be displayed. You can open the PDF to read it.");
  } finally {
    if (current()) {
      session.pending = false;
      session.animation = null;
      manualPrevious.disabled = session.index === 0;
      manualNext.disabled = session.index >= session.spreads.length - 1;
    }
  }
}

async function openManual(manual) {
  if (manualDialog.open) return;
  const session = {
    url: `${manual.localUrl}/pages`, controller: new AbortController(), images: new Map(),
    visibleImages: [], anchor: 1, index: 0, request: 0,
  };
  manualSession = session;
  document.querySelector("#snes-manual-title").textContent = manual.name;
  document.querySelector("#snes-manual-file").href = manual.localUrl;
  manualBook.hidden = true;
  manualBook.replaceChildren();
  manualNavigation.hidden = true;
  manualMessage("Loading manual…");
  manualDialog.showModal();
  try {
    const response = await fetch(session.url, {signal: session.controller.signal});
    if (!response.ok) throw new Error("Manual unavailable");
    const {pages} = await response.json();
    if (manualSession !== session || !manualDialog.open) return;
    session.pages = pages;
    session.spreads = groupManualPages(pages);
    await showManualSpread(session, 0);
  } catch {
    if (manualSession === session && manualDialog.open) {
      manualMessage("The book view could not be loaded. You can open the PDF to read it.");
    }
  }
}

function moveManual(direction) {
  const session = manualSession;
  if (!session?.spreads || session.pending || manualNavigation.hidden) return;
  const target = session.index + direction;
  if (target >= 0 && target < session.spreads.length) showManualSpread(session, target, direction);
}

manualPrevious.addEventListener("click", () => moveManual(-1));
manualNext.addEventListener("click", () => moveManual(1));
manualDialog.addEventListener("keydown", event => {
  if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
  event.preventDefault();
  moveManual(event.key === "ArrowLeft" ? -1 : 1);
});
manualDialog.addEventListener("close", () => {
  if (manualDialog.open) return;
  manualSession?.controller.abort();
  manualSession?.animation?.cancel();
  manualSession = undefined;
  manualBook.replaceChildren();
});
manualDialog.addEventListener("click", event => {
  if (event.target !== manualDialog) return;
  const bounds = manualDialog.getBoundingClientRect();
  if (event.clientX < bounds.left || event.clientX > bounds.right ||
      event.clientY < bounds.top || event.clientY > bounds.bottom) manualDialog.close();
});
facingPages.addEventListener("change", () => {
  const session = manualSession;
  if (!session?.pages || !manualDialog.open) return;
  session.spreads = groupManualPages(session.pages);
  const index = session.spreads.findIndex(spread => spread.includes(session.anchor));
  showManualSpread(session, index);
});
