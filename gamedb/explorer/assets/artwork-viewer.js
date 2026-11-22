const artworkDialog = document.createElement("dialog");
artworkDialog.id = "artwork-dialog";
artworkDialog.className = "artwork-dialog";
artworkDialog.setAttribute("aria-labelledby", "artwork-caption");
artworkDialog.innerHTML = `
  <div class="artwork-heading">
    <h2 id="artwork-caption"></h2>
    <button id="artwork-close" class="icon-button" type="button" aria-label="Close artwork" autofocus>×</button>
  </div>
  <div class="artwork-stage">
    <img id="artwork-image" alt="">
    <p id="artwork-error" role="status" hidden>This image could not be loaded.</p>
  </div>
  <div id="artwork-navigation" class="artwork-navigation" hidden>
    <button id="artwork-previous" class="secondary-button" type="button" aria-label="Previous image">← Previous</button>
    <span id="artwork-position" role="status"></span>
    <button id="artwork-next" class="secondary-button" type="button" aria-label="Next image">Next →</button>
  </div>
`;
document.body.append(artworkDialog);

const artworkFullImage = artworkDialog.querySelector("#artwork-image");
const artworkError = artworkDialog.querySelector("#artwork-error");
const artworkCaption = artworkDialog.querySelector("#artwork-caption");
const artworkNavigation = artworkDialog.querySelector("#artwork-navigation");
const artworkPosition = artworkDialog.querySelector("#artwork-position");
let artworkItems = [];
let artworkIndex = 0;

function renderArtworkImage() {
  const item = artworkItems[artworkIndex];
  artworkCaption.textContent = item.caption;
  artworkError.hidden = true;
  artworkFullImage.hidden = false;
  artworkFullImage.alt = item.caption;
  artworkFullImage.classList.toggle("pixel-art", Boolean(item.pixelArt));
  artworkFullImage.src = item.source;
  artworkNavigation.hidden = artworkItems.length < 2;
  artworkPosition.textContent = `Image ${artworkIndex + 1} of ${artworkItems.length}`;
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

artworkDialog.querySelector("#artwork-close").addEventListener("click", () => artworkDialog.close());
artworkDialog.querySelector("#artwork-previous").addEventListener("click", () => moveArtwork(-1));
artworkDialog.querySelector("#artwork-next").addEventListener("click", () => moveArtwork(1));
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
  artworkFullImage.removeAttribute("src");
  artworkItems = [];
  artworkIndex = 0;
});
artworkFullImage.addEventListener("error", () => {
  if (!artworkDialog.open) return;
  artworkFullImage.hidden = true;
  artworkError.hidden = false;
});
