import createZXTune from "./zxtune-f59403a-2/zxtune.mjs";

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

async function openZXTune({url, format, libraries, sampleRate, subsong}) {
  const [module, bytes] = await Promise.all([createZXTune(), readAudioFile(url)]);
  decoder = module;
  const info = readSubsongInfo(bytes, format);
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
      playback = await (data.format === "sndh" ? openSndh(data) : openZXTune(data));
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
