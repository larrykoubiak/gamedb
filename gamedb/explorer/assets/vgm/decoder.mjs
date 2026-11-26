import createZXTune from "./zxtune-f59403a-2/zxtune.mjs?v=3";

let decoder;
let playback;

async function readAudioFile(url) {
  const response = await fetch(url, {mode: "same-origin"});
  if (!response.ok) throw new Error("A soundtrack file could not be fetched.");
  return new Uint8Array(await response.arrayBuffer());
}

function withDecoderBytes(bytes, use) {
  const pointer = decoder._malloc(bytes.length);
  if (!pointer) throw new Error("The playback engine ran out of memory.");
  try {
    decoder.HEAPU8.set(bytes, pointer);
    return use(pointer, bytes.length);
  } finally {
    decoder._free(pointer);
  }
}

function findLibrary(path, libraries) {
  const name = path.split(/[\\/]/).at(-1).normalize("NFC");
  const exact = libraries.filter(file => file.name.normalize("NFC") === name);
  const matches = exact.length ? exact : libraries.filter(file =>
    file.name.normalize("NFC").toLowerCase() === name.toLowerCase());
  if (matches.length !== 1) throw new Error(`Could not resolve the soundtrack library ${name}.`);
  return matches[0];
}

async function loadLibraries(track, libraries) {
  const supplied = new Set();
  let missing = track.getAdditionalFiles();
  while (missing.length) {
    for (const path of missing) {
      if (supplied.has(path)) throw new Error(`Could not resolve the soundtrack library ${path}.`);
      const bytes = await readAudioFile(findLibrary(path, libraries).url);
      withDecoderBytes(bytes, (pointer, size) => track.resolveAdditionalFile(path, pointer, size));
      supplied.add(path);
    }
    missing = track.getAdditionalFiles();
  }
}

function ssfLibraries(bytes) {
  if (bytes.length < 16 || String.fromCharCode(...bytes.subarray(0, 4)) !== "PSF\x11") {
    throw new Error("Invalid Sega Saturn soundtrack file.");
  }
  const header = new DataView(bytes.buffer, bytes.byteOffset, 16);
  const offset = 16 + header.getUint32(4, true) + header.getUint32(8, true);
  if (offset > bytes.length) throw new Error("Incomplete Sega Saturn soundtrack file.");
  if (String.fromCharCode(...bytes.subarray(offset, offset + 5)) !== "[TAG]") return [];
  const raw = bytes.subarray(offset + 5);
  let tags;
  try {
    tags = new TextDecoder("utf-8", {fatal: true}).decode(raw);
  } catch {
    tags = new TextDecoder("windows-1252").decode(raw);
  }
  return [...tags.matchAll(/^_lib\d*[ \t]*=([^\r\n]+)$/gmi)].map(match => match[1].trim());
}

async function mountSsf(fs, path, bytes, libraries, mounted) {
  const folder = path.slice(0, path.lastIndexOf("/") + 1);
  fs.mkdirTree(folder);
  fs.writeFile(path, bytes);
  mounted.add(path);
  for (const library of ssfLibraries(bytes)) {
    const pieces = library.replaceAll("\\", "/").split("/");
    if (!pieces[0] || pieces.includes("..") || /[:\x00-\x1f]/.test(library)) {
      throw new Error("Invalid Sega Saturn soundtrack library path.");
    }
    const target = folder + pieces.filter(piece => piece && piece !== ".").join("/");
    if (mounted.has(target)) continue;
    if (mounted.size > libraries.length) throw new Error("Too many Sega Saturn soundtrack libraries.");
    await mountSsf(fs, target, await readAudioFile(findLibrary(library, libraries).url), libraries, mounted);
  }
}

async function openSsf({url, libraries, sampleRate}) {
  const [{default: createSsf}, bytes] = await Promise.all([
    import("./ssfplay-a28e0d7/ssfplay.mjs"), readAudioFile(url),
  ]);
  const player = await createSsf();
  const filename = "/soundtrack/track.ssf";
  await mountSsf(player.FS, filename, bytes, libraries, new Set());
  const open = player.cwrap("ssfplay_wasm_open", "number", ["string", "number", "number", "number", "number"]);
  const handle = open(filename, sampleRate, 3, -1n, -1n);
  if (!handle) throw new Error(player.UTF8ToString(player._ssfplay_wasm_last_error()));
  const duration = Number(player._ssfplay_length_ms(handle) + player._ssfplay_fade_ms(handle)) / 1000;
  const frames = Math.round(sampleRate / 4);
  const buffer = player._malloc(frames * 4);
  if (!buffer) throw new Error("The playback engine ran out of memory.");
  let position = 0;
  function renderFrames(count) {
    const countRendered = player._ssfplay_wasm_render(handle, buffer, count);
    position += countRendered;
    return countRendered;
  }
  return {
    duration,
    seek(seconds) {
      const target = Math.round(Math.min(seconds, duration) * sampleRate);
      if (target < position) {
        if (player._ssfplay_reset(handle)) throw new Error("Could not restart the Sega Saturn soundtrack.");
        position = 0;
      }
      while (position < target) {
        if (!renderFrames(Math.min(frames, target - position))) break;
      }
    },
    render() {
      const count = renderFrames(frames);
      const samples = player.HEAP16.slice(buffer / 2, buffer / 2 + count * 2);
      return {samples, done: count < frames, sampleRate};
    },
  };
}

function readSubsongInfo(bytes, format) {
  const magic = String.fromCharCode(...bytes.subarray(0, 5));
  let subsongs, firstSong;
  if (format === "sid" && bytes.length >= 118 && /^(PSID|RSID)/.test(magic)) {
    subsongs = (bytes[14] << 8) | bytes[15];
    firstSong = (bytes[16] << 8) | bytes[17];
  } else if (format === "nsf" && bytes.length >= 0x80 && magic === "NESM\x1a") {
    subsongs = bytes[6];
    firstSong = bytes[7];
  } else if (format === "gbs" && bytes.length >= 0x70 && magic.startsWith("GBS\x01")) {
    subsongs = bytes[4];
    firstSong = bytes[5];
  }
  return {subsongs, defaultSubsong: firstSong > 0 && firstSong <= subsongs ? firstSong : 1};
}

function loadTrack(bytes, format, subsong, firstSong) {
  return withDecoderBytes(bytes, (pointer, size) => {
    if (subsong) return decoder.load(pointer, size, `#${subsong}`);
    // HES stores the zero-based starting track at offset five.
    if (format === "hes" && size >= 6) return decoder.load(pointer, size, `#${bytes[5] + 1}`);
    try {
      return decoder.load(pointer, size, "");
    } catch (error) {
      // ZXTune gives files with multiple songs a separate path for each song.
      const {tracks} = decoder.detect(pointer, size);
      if (!tracks.length) throw error;
      const track = tracks.find(item => item.subpath === `#${firstSong}`) || tracks[0];
      return decoder.load(pointer, size, track.subpath);
    }
  });
}

async function openZXTune({url, format, libraries, sampleRate, subsong, defaultSubsong}) {
  const [module, bytes] = await Promise.all([
    createZXTune({locateFile: (name, prefix) => `${prefix}${name}?v=3`}),
    readAudioFile(url),
  ]);
  decoder = module;
  const info = readSubsongInfo(bytes, format);
  if (format === "nsfe" && defaultSubsong > 0) info.defaultSubsong = defaultSubsong;
  const track = loadTrack(bytes, format, subsong, info.defaultSubsong);
  let player, duration;
  try {
    await loadLibraries(track, libraries);
    player = track.createPlayer(sampleRate);
    duration = track.getDuration() / 1000;
  } finally {
    track.delete();
  }
  const frames = Math.round(sampleRate / 4);
  const buffer = decoder._malloc(frames * 4);
  if (!buffer) throw new Error("The playback engine ran out of memory.");
  return {
    duration,
    ...info,
    seek(position) { player.seek(Math.round(position * 1000)); },
    render() {
      const done = !player.render(buffer, frames);
      const offset = buffer / 2;
      const samples = decoder.HEAP16.slice(offset, offset + frames * 2);
      return {samples, done, sampleRate};
    },
  };
}

async function openSndh({url, subsong}) {
  const [module, bytes] = await Promise.all([
    import("./ym2149-0.8.1/ym2149_wasm.js"), readAudioFile(url),
  ]);
  await module.default();
  const player = new module.Ym2149Player(bytes);
  const firstSong = player.currentSubsong();
  if (subsong && !player.setSubsong(subsong)) throw new Error("This song is unavailable.");
  player.play();
  const metadata = player.metadata;
  const duration = metadata.duration_seconds;
  metadata.free();
  const sampleRate = 44100; // The WASM player outputs mono PCM at 44.1 kHz.
  return {
    duration,
    subsongs: player.subsongCount(),
    defaultSubsong: firstSong,
    seek(position) { player.seek_to_percentage(position / duration); },
    render() {
      const mono = player.generateSamples(sampleRate / 4);
      const samples = new Int16Array(mono.length * 2);
      for (let frame = 0; frame < mono.length; frame++) {
        const value = Math.max(-32768, Math.min(32767, Math.round(mono[frame] * 32768)));
        samples[2 * frame] = samples[2 * frame + 1] = value;
      }
      return {samples, done: !player.is_playing(), sampleRate};
    },
  };
}

self.addEventListener("message", async ({data}) => {
  try {
    if (data.type === "open") {
      if (data.format === "ssf" || data.format === "minissf") playback = await openSsf(data);
      else playback = await (data.format === "sndh" ? openSndh(data) : openZXTune(data));
    } else if (data.type === "seek") {
      playback.seek(data.position);
    }
    const chunk = playback.render();
    self.postMessage({
      ...chunk, generation: data.generation, duration: playback.duration,
      subsongs: playback.subsongs, defaultSubsong: playback.defaultSubsong,
    }, [chunk.samples.buffer]);
  } catch (error) {
    self.postMessage({generation: data.generation,
      error: error?.message || "The playback engine could not decode this track."});
  }
});
