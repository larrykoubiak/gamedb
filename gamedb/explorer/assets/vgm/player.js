const vgmFormats = new Set([
  "2sf", "adx", "ay", "gbs", "gsf", "gym", "hes", "hwas", "it", "kss", "med", "mini2sf", "minigsf",
  "minincsf", "minipsf", "miniusf", "mod", "ncsf", "nsf", "nsfe", "okt", "psf", "s3m", "sap", "sfx",
  "sid", "sndh", "spc", "strm", "swav", "usf", "vgm", "vgz", "xm",
]);
const vgmAudioContext = window.AudioContext || window.webkitAudioContext;

function canPlayVgm(asset) {
  return Boolean(vgmAudioContext && window.Worker && window.WebAssembly &&
    asset.kind === "track" && vgmFormats.has(asset.format));
}

function startVgmPlayback(asset, libraries, {started, ended, subsong}) {
  const audio = new vgmAudioContext();
  let worker;
  let timer;
  let queuedUntil = 0;
  let stopped = false;

  function stop() {
    if (stopped) return;
    stopped = true;
    clearTimeout(timer);
    worker?.terminate();
    audio.close().catch(() => {});
  }

  function finish(message) {
    if (stopped) return;
    stop();
    ended(message);
  }

  function queueAudio({samples, done, sampleRate}) {
    const buffer = audio.createBuffer(2, samples.length / 2, sampleRate);
    for (let channel = 0; channel < 2; channel++) {
      const output = buffer.getChannelData(channel);
      for (let frame = 0; frame < output.length; frame++) {
        output[frame] = samples[2 * frame + channel] / 32768;
      }
    }
    const source = audio.createBufferSource();
    source.buffer = buffer;
    source.connect(audio.destination);
    if (done) source.addEventListener("ended", () => finish(), {once: true});
    const startAt = Math.max(queuedUntil, audio.currentTime + 0.025);
    source.start(startAt);
    if (!queuedUntil) started();
    queuedUntil = startAt + buffer.duration;
    if (!done) {
      // Keep a short buffer ahead of the audio clock while the worker decodes.
      const delay = Math.max(0, queuedUntil - audio.currentTime - 0.6);
      timer = setTimeout(() => worker.postMessage({type: "next"}), delay * 1000);
    }
  }

  try {
    worker = new Worker("/vgm/decoder.mjs?v=3", {type: "module"});
    const resumed = audio.resume().catch(() => finish("Browser audio could not start."));
    worker.addEventListener("error", () => finish("The playback engine could not load."));
    worker.addEventListener("messageerror", () => finish("The playback engine returned unreadable audio."));
    worker.addEventListener("message", async ({data}) => {
      await resumed;
      if (stopped) return;
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
      type: "open", url: asset.url, format: asset.format, libraries, sampleRate: audio.sampleRate, subsong,
    });
  } catch (error) {
    stop();
    throw error;
  }
  return stop;
}
