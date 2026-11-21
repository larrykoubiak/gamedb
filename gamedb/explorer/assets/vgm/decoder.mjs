import createZXTune from "./zxtune-f59403a/zxtune.mjs";

let decoder;
let player;
let buffer;
let frames;

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

async function loadLibraries(track, libraries) {
  const supplied = new Set();
  let missing = track.getAdditionalFiles();
  while (missing.length) {
    for (const path of missing) {
      const name = path.split(/[\\/]/).at(-1).normalize("NFC");
      const matches = libraries.filter(file => file.name.normalize("NFC") === name);
      const candidates = matches.length ? matches : libraries.filter(file =>
        file.name.normalize("NFC").toLowerCase() === name.toLowerCase());
      if (candidates.length !== 1 || supplied.has(path)) {
        throw new Error(`Could not resolve the soundtrack library ${name}.`);
      }
      const bytes = await readAudioFile(candidates[0].url);
      withDecoderBytes(bytes, (pointer, size) => track.resolveAdditionalFile(path, pointer, size));
      supplied.add(path);
    }
    missing = track.getAdditionalFiles();
  }
}

function loadTrack(bytes, format) {
  return withDecoderBytes(bytes, (pointer, size) => {
    try {
      return decoder.load(pointer, size, "");
    } catch (error) {
      // ZXTune gives files with multiple songs a separate path for each song.
      const {tracks} = decoder.detect(pointer, size);
      if (!tracks.length) throw error;
      let firstSong = 1;
      if (format === "sid" && bytes.length >= 18) firstSong = (bytes[16] << 8) | bytes[17];
      if (format === "nsf") firstSong = bytes[7];
      const track = tracks.find(item => item.subpath === `#${firstSong}`) || tracks[0];
      return decoder.load(pointer, size, track.subpath);
    }
  });
}

async function openTrack({url, format, libraries, sampleRate}) {
  const [module, bytes] = await Promise.all([createZXTune(), readAudioFile(url)]);
  decoder = module;
  const track = loadTrack(bytes, format);
  try {
    await loadLibraries(track, libraries);
    player = track.createPlayer(sampleRate);
  } finally {
    track.delete();
  }
  frames = Math.round(sampleRate / 4);
  buffer = decoder._malloc(frames * 4);
  if (!buffer) throw new Error("The playback engine ran out of memory.");
}

self.addEventListener("message", async ({data}) => {
  try {
    if (data.type === "open") await openTrack(data);
    const done = !player.render(buffer, frames);
    const offset = buffer / 2;
    const samples = decoder.HEAP16.slice(offset, offset + frames * 2);
    self.postMessage({samples, done}, [samples.buffer]);
  } catch (error) {
    self.postMessage({error: error.message || "The playback engine could not decode this track."});
  }
});
