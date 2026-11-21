const browserMusicFormats = new Set(["aac", "flac", "m4a", "mp3", "ogg", "opus", "wav"]);
const trackOrder = new Intl.Collator(undefined, {numeric: true, sensitivity: "base"});
let activeSoundtrack;
let soundtrackVolume = 1;

function pauseAudio(container) {
  if (activeSoundtrack && container.contains(activeSoundtrack.root)) activeSoundtrack.stop();
  for (const audio of container.querySelectorAll("audio")) audio.pause();
}

window.addEventListener("pagehide", () => pauseAudio(document));

function sourceMusicAlbum(title, attachments) {
  return {
    title, collection: "eXo",
    assets: attachments.map(({label: name, url}) => {
      const format = /\.([^.]+)$/.exec(name)?.[1].toLowerCase() || "";
      return {name, url, format, kind: format === "m3u" ? "support" : "track",
        playable: browserMusicFormats.has(format)};
    }),
  };
}

function startBrowserMusic(asset, {started, ended, volume}) {
  const audio = new Audio();
  let stopped = false;
  audio.volume = volume;
  audio.addEventListener("playing", () => { if (!stopped) started(); });
  audio.addEventListener("ended", () => { if (!stopped) ended(); });
  audio.addEventListener("error", () => { if (!stopped) ended("The audio file could not be loaded."); });
  audio.src = asset.url;

  function resume() {
    audio.play().catch(error => {
      if (!stopped && error.name !== "AbortError") ended("Browser audio could not start.");
    });
  }

  resume();
  return {
    resume,
    pause() { audio.pause(); },
    stop() {
      stopped = true;
      audio.pause();
      audio.removeAttribute("src");
      audio.load();
    },
    seek(position) { audio.currentTime = position; },
    position: () => audio.currentTime,
    duration: () => audio.duration,
    setVolume(value) { audio.volume = value; },
  };
}

function soundtrackTime(value) {
  const seconds = Math.floor(value);
  const minutes = Math.floor(seconds / 60);
  const tail = String(seconds % 60).padStart(2, "0");
  return minutes < 60 ? `${minutes}:${tail}` :
    `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")}:${tail}`;
}

function soundtrackTitle(asset) {
  if (asset.title) return asset.title;
  let name = asset.name;
  if (asset.format) {
    if (name.toLowerCase().endsWith(`.${asset.format}`)) name = name.slice(0, -asset.format.length - 1);
    else if (name.toLowerCase().startsWith(`${asset.format}.`)) name = name.slice(asset.format.length + 1);
  }
  return name.replace(/^\d{1,3}[a-z]?\s+-\s+/i, "").replace(/^S[CL][A-Z]{2}-\d{5}[_ ]+/i, "")
    .replaceAll("_", " ").trim() || asset.name;
}

function setSoundtrackIcon(button, icon, label) {
  button.dataset.icon = icon;
  button.title = label;
  button.setAttribute("aria-label", label);
}

function soundtrackDownload(asset, icon = false) {
  const link = cellText("a", icon ? "↓" : asset.name);
  link.href = asset.url;
  link.download = "";
  if (icon) {
    link.className = "soundtrack-download";
    link.title = `Download ${asset.name}`;
    link.setAttribute("aria-label", link.title);
  }
  return link;
}

function renderSoundtracks(container, soundtracks) {
  const albums = soundtracks.filter(album => album.assets?.length).map(album => ({
    ...album,
    tracks: album.assets.filter(asset => asset.kind === "track")
      .sort((first, second) => trackOrder.compare(first.name, second.name))
      .map(asset => ({asset, name: soundtrackTitle(asset),
        playable: asset.playable || canPlayVgm(asset), subsongs: asset.subsongs || 1})),
    files: album.assets.filter(asset => asset.kind !== "track"),
  }));
  if (!albums.length) return;

  const template = document.querySelector("#soundtrack-playlist-template");
  const root = template.content.firstElementChild.cloneNode(true);
  const player = root.querySelector(".soundtrack-player");
  const title = root.querySelector(".soundtrack-current-title");
  const credit = root.querySelector(".soundtrack-current-credit");
  const status = root.querySelector(".soundtrack-player-status");
  const [elapsed, position, total] = root.querySelector(".soundtrack-timeline").children;
  const [previous, play, next] = root.querySelector(".soundtrack-transport").children;
  const subtunes = root.querySelector(".soundtrack-subtunes");
  const song = subtunes.querySelector("select");
  const volume = root.querySelector(".soundtrack-volume input");
  volume.value = soundtrackVolume;
  const count = root.querySelector(".soundtrack-playlist-label span");
  const picker = root.querySelector(".soundtrack-playlist-tools select");
  picker.hidden = albums.length === 1;
  const labels = albums.map(({title, collection}) => `${title} · ${collection}`);
  for (const [index, label] of labels.entries()) {
    const archive = labels.indexOf(label) === labels.lastIndexOf(label) ? "" :
      albums[index].files.find(asset => asset.kind === "archive")?.name;
    picker.add(new Option(archive ? `${label} · ${archive}` : label, index));
  }
  const downloads = root.querySelector(".soundtrack-files");
  const files = downloads.querySelector("ul");
  const tracks = root.querySelector(".soundtrack-tracks");
  const downloadOnly = root.querySelector(".soundtrack-download-note");
  const credits = root.querySelector(".soundtrack-credits");
  container.append(root);

  let album, selected, highlighted, transport, clock;
  let playable = [];
  let libraries = [];
  let rows = new Map();
  let request = 0;
  let subtune = 0;
  let phase = "ready";
  let error = "";
  let ready = false;
  let scrubbing = false;

  function neighbor(step) {
    if (!selected) return;
    const index = (subtune || selected.defaultSubsong || 1) + step;
    if (selected.subsongs > 1 && index >= 1 && index <= selected.subsongs) return {track: selected, tune: index};
    const track = playable[playable.indexOf(selected) + step];
    if (track) return {track, tune: step < 0 && track.subsongs > 1 ? track.subsongs : 0};
  }

  function updateTimeline() {
    const duration = transport?.duration();
    const hasTime = ready && Number.isFinite(duration) && duration > 0;
    const now = Math.max(0, transport?.position() || 0);
    const displayTime = scrubbing && hasTime ? Number(position.value) : hasTime ? Math.min(now, duration) : now;
    position.disabled = !hasTime;
    position.max = hasTime ? String(duration) : "1";
    if (!scrubbing || !hasTime) position.value = hasTime ? displayTime : 0;
    position.style.setProperty("--played", `${hasTime ? displayTime / duration * 100 : 0}%`);
    elapsed.textContent = soundtrackTime(displayTime);
    total.textContent = hasTime ? soundtrackTime(duration) : "–:––";
    position.setAttribute("aria-valuetext", hasTime ? `${elapsed.textContent} of ${total.textContent}` : elapsed.textContent);
  }

  function updatePlayer() {
    player.hidden = !selected;
    downloadOnly.hidden = Boolean(selected);
    if (!selected) return;
    title.textContent = selected.name;
    const activeSong = subtune || selected.defaultSubsong;
    const songs = activeSong ? `Song ${activeSong} of ${selected.subsongs}` : `${selected.subsongs} subtunes`;
    credit.textContent = [selected.asset.artist, album.collection,
      selected.subsongs > 1 ? songs : ""].filter(Boolean).join(" · ");
    const message = error || {loading: "Loading…", playing: "Playing", paused: "Paused", ready: ""}[phase];
    if (status.textContent !== message) status.textContent = message;
    const playing = phase === "playing" || phase === "loading";
    setSoundtrackIcon(play, playing ? "pause" : "play", playing ? "Pause" : "Play");
    previous.disabled = !neighbor(-1);
    next.disabled = !neighbor(1);
    subtunes.hidden = selected.subsongs <= 1;
    if (!subtunes.hidden) {
      const defaultLabel = selected.defaultSubsong ? `Default song (${selected.defaultSubsong})` : "Default song";
      if (song.options.length !== selected.subsongs + 1 || song.options[0]?.label !== defaultLabel) {
        song.replaceChildren(new Option(defaultLabel, "0"));
        for (let index = 1; index <= selected.subsongs; index++) song.add(new Option(`Song ${index}`, index));
      }
      song.value = String(subtune);
    }
    for (const track of new Set([highlighted, selected])) {
      if (!track) continue;
      const {row, button, songs} = rows.get(track);
      const active = track === selected;
      row.classList.toggle("is-current", active);
      if (active) button.setAttribute("aria-current", "true");
      else button.removeAttribute("aria-current");
      button.setAttribute("aria-label", `${active && playing ? "Pause" : "Play"} ${track.name}`);
      songs.textContent = track.subsongs > 1 ? ` · ${track.subsongs} songs` : "";
    }
    highlighted = selected;
    updateTimeline();
  }

  function stop() {
    request++;
    clearInterval(clock);
    transport?.stop();
    transport = null;
    ready = false;
    scrubbing = false;
    phase = "ready";
    error = "";
    if (activeSoundtrack?.root === root) activeSoundtrack = null;
    updatePlayer();
  }

  function start() {
    pauseAudio(document);
    const revision = ++request;
    error = "";
    phase = "loading";
    volume.value = soundtrackVolume;
    const callbacks = {
      volume: soundtrackVolume,
      subsong: subtune,
      started(info) {
        if (request !== revision) return;
        ready = true;
        if (info?.subsongs > 0) selected.subsongs = info.subsongs;
        if (info?.defaultSubsong > 0) selected.defaultSubsong = info.defaultSubsong;
        if (phase !== "paused") phase = "playing";
        updatePlayer();
      },
      ended(message) {
        if (request !== revision) return;
        const following = message || phase === "paused" ? null : neighbor(1);
        stop();
        if (following) selectTrack(following.track, following.tune, true);
        else if (message) {
          error = `Could not play ${selected.name}. ${message}`;
          updatePlayer();
        }
      },
    };

    try {
      transport = selected.asset.playable ? startBrowserMusic(selected.asset, callbacks) :
        startVgmPlayback(selected.asset, libraries, callbacks);
      activeSoundtrack = {root, stop};
      clock = setInterval(updateTimeline, 200);
    } catch {
      callbacks.ended("The playback engine could not start.");
    }
    updatePlayer();
  }

  function toggle() {
    if (!selected) return;
    if (!transport) return start();
    if (phase === "paused") {
      phase = ready ? "playing" : "loading";
      transport.resume();
    } else {
      phase = "paused";
      transport.pause();
    }
    updatePlayer();
  }

  function selectTrack(track, tune, playImmediately) {
    stop();
    selected = track;
    subtune = tune;
    updatePlayer();
    if (playImmediately) start();
  }

  function move(step) {
    const adjacent = neighbor(step);
    if (adjacent) selectTrack(adjacent.track, adjacent.tune, Boolean(transport && phase !== "paused"));
  }

  function openAlbum(index) {
    stop();
    album = albums[index];
    picker.value = String(index);
    playable = album.tracks.filter(track => track.playable);
    libraries = album.assets.filter(asset => asset.kind !== "archive").map(({name, url}) => ({name, url}));
    selected = playable[0];
    highlighted = null;
    subtune = 0;
    count.textContent = `${album.tracks.length} ${album.tracks.length === 1 ? "track" : "tracks"}`;
    root.classList.toggle("soundtrack-archive-only", !album.tracks.length);
    count.hidden = !album.tracks.length;
    downloads.hidden = !album.files.length;
    downloads.open = !album.tracks.length;
    files.replaceChildren(...album.files.map(asset => {
      const item = document.createElement("li");
      item.append(soundtrackDownload(asset));
      return item;
    }));
    credits.hidden = !album.tracks.some(track => canPlayVgm(track.asset));
    rows = new Map();
    tracks.replaceChildren(...album.tracks.map((track, index) => {
      const row = document.createElement("li");
      row.className = "soundtrack-track";
      const number = cellText("span", index + 1);
      number.className = "soundtrack-track-number";
      number.setAttribute("aria-hidden", "true");
      const name = cellText(track.playable ? "button" : "div", track.name);
      name.className = "soundtrack-track-name";
      if (track.playable) {
        name.type = "button";
        name.setAttribute("aria-label", `Play ${track.name}`);
        name.addEventListener("click", () => track === selected ? toggle() : selectTrack(track, 0, true));
      }
      if (track.asset.artist) name.append(cellText("small", track.asset.artist));
      const meta = cellText("span", track.asset.format?.toUpperCase() || "");
      meta.className = "soundtrack-track-format";
      const songs = cellText("span", track.subsongs > 1 ? ` · ${track.subsongs} songs` : "");
      meta.append(songs);
      row.append(number, name, meta, soundtrackDownload(track.asset, true));
      rows.set(track, {row, button: name, songs});
      return row;
    }));
    updatePlayer();
  }

  play.addEventListener("click", toggle);
  previous.addEventListener("click", () => move(-1));
  next.addEventListener("click", () => move(1));
  picker.addEventListener("change", () => openAlbum(Number(picker.value)));
  song.addEventListener("change", () => selectTrack(selected, Number(song.value), Boolean(transport && phase !== "paused")));
  volume.addEventListener("input", () => {
    soundtrackVolume = Number(volume.value);
    transport?.setVolume(soundtrackVolume);
  });
  position.addEventListener("input", () => { scrubbing = true; updateTimeline(); });
  position.addEventListener("change", () => {
    scrubbing = false;
    transport?.seek(Number(position.value));
    updateTimeline();
  });
  position.addEventListener("blur", () => { scrubbing = false; updateTimeline(); });
  openAlbum(Math.max(0, albums.findIndex(album => album.tracks.some(track => track.playable))));
}
