const vgmFormats = new Set([
  "2sf", "adx", "ay", "gbs", "genh", "gsf", "gym", "hes", "hwas", "it", "kss", "med", "mini2sf", "minigsf",
  "minincsf", "minipsf", "miniusf", "mod", "ncsf", "nsf", "nsfe", "okt", "psf", "s3m", "sap", "sfx",
  "sid", "sndh", "spc", "strm", "swav", "usf", "vgm", "vgz", "xa", "xm",
]);
const vgmAudioContext = window.AudioContext || window.webkitAudioContext;

function canPlayVgm(asset) {
  return Boolean(vgmAudioContext && window.Worker && window.WebAssembly &&
    asset.kind === "track" && vgmFormats.has(asset.format));
}

function startVgmPlayback(asset, libraries, {started, ended, subsong, volume}) {
  const audio = new vgmAudioContext();
  const gain = audio.createGain();
  gain.gain.value = volume;
  gain.connect(audio.destination);
  const sources = new Set();
  let worker;
  let timer;
  let generation = 0;
  let duration = 0;
  let positionOffset = 0;
  let startedAt;
  let queuedUntil = 0;
  let pending = true;
  let paused = false;
  let finalChunk = false;
  let stopped = false;

  function clearQueue() {
    clearTimeout(timer);
    for (const source of sources) {
      source.onended = null;
      source.stop();
      source.disconnect();
    }
    sources.clear();
  }

  function stop() {
    if (stopped) return;
    stopped = true;
    clearQueue();
    worker?.terminate();
    audio.close().catch(() => {});
  }

  function finish(message) {
    if (stopped) return;
    stop();
    ended(message);
  }

  function scheduleMore() {
    clearTimeout(timer);
    if (stopped || paused || pending || finalChunk || audio.state !== "running") return;
    const delay = Math.max(0, queuedUntil - audio.currentTime - 0.6);
    timer = setTimeout(() => {
      pending = true;
      worker.postMessage({type: "next", generation});
    }, delay * 1000);
  }

  function resume() {
    paused = false;
    audio.resume().then(scheduleMore).catch(() => finish("Browser audio could not start."));
  }

  function queueAudio(data) {
    const {samples, done, sampleRate} = data;
    if (!samples.length) return finish();
    duration = data.duration;
    finalChunk = done;
    const buffer = audio.createBuffer(2, samples.length / 2, sampleRate);
    for (let channel = 0; channel < 2; channel++) {
      const output = buffer.getChannelData(channel);
      for (let frame = 0; frame < output.length; frame++) {
        output[frame] = samples[2 * frame + channel] / 32768;
      }
    }
    const source = audio.createBufferSource();
    source.buffer = buffer;
    source.connect(gain);
    source.onended = () => {
      sources.delete(source);
      source.disconnect();
      if (done) finish();
    };
    const startAt = Math.max(queuedUntil, audio.currentTime + 0.025);
    const first = startedAt === undefined;
    startedAt = first ? startAt : startedAt + startAt - queuedUntil;
    source.start(startAt);
    sources.add(source);
    queuedUntil = startAt + buffer.duration;
    if (first) started(data);
    scheduleMore();
  }

  try {
    worker = new Worker("/vgm/decoder.mjs?v=5", {type: "module"});
    worker.addEventListener("error", () => finish("The playback engine could not load."));
    worker.addEventListener("messageerror", () => finish("The playback engine returned unreadable audio."));
    worker.addEventListener("message", ({data}) => {
      if (stopped || data.generation !== generation) return;
      pending = false;
      if (data.error) {
        finish(data.error);
        return;
      }
      try {
        queueAudio(data);
      } catch {
        finish("The decoded audio could not be played.");
      }
    });
    worker.postMessage({
      type: "open", url: asset.url, format: asset.format, libraries, sampleRate: audio.sampleRate,
      subsong, defaultSubsong: asset.defaultSubsong, generation,
    });
    resume();
  } catch (error) {
    stop();
    throw error;
  }
  return {
    stop,
    resume,
    pause() {
      paused = true;
      clearTimeout(timer);
      audio.suspend().catch(() => finish("Browser audio could not pause."));
    },
    seek(position) {
      if (!(duration > 0)) return;
      clearQueue();
      positionOffset = position;
      startedAt = undefined;
      queuedUntil = 0;
      finalChunk = false;
      pending = true;
      worker.postMessage({type: "seek", position, generation: ++generation});
    },
    position: () => positionOffset + (startedAt === undefined ? 0 :
      Math.max(0, Math.min(audio.currentTime, queuedUntil) - startedAt)),
    duration: () => duration,
    setVolume(value) { gain.gain.value = value; },
  };
}
