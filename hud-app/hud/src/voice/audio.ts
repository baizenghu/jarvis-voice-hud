// Mic capture (MediaRecorder) + Web Audio analysers for HUD reactivity.
// Pure helpers (mime selection, base64) are exported for unit tests.

// Prefer webm, fall back to ogg. Returns "" if neither is supported.
// `isSupported` is injected so this is testable without a real MediaRecorder.
export function pickMime(
  isSupported: (m: string) => boolean = (m) =>
    typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(m),
): string {
  if (isSupported("audio/webm")) {
    return "audio/webm";
  }
  if (isSupported("audio/ogg")) {
    return "audio/ogg";
  }
  return "";
}

// Decode a base64 string to bytes (for the synthesized audio blob).
export function base64ToBytes(b64: string): Uint8Array<ArrayBuffer> {
  const bin = atob(b64);
  const bytes = new Uint8Array(new ArrayBuffer(bin.length));
  for (let i = 0; i < bin.length; i++) {
    bytes[i] = bin.charCodeAt(i);
  }
  return bytes;
}

export function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve) => {
    const r = new FileReader();
    r.onloadend = () => resolve((r.result as string).split(",")[1]); // strip data: prefix
    r.readAsDataURL(blob);
  });
}

export interface CaptureResult {
  blob: Blob;
  mime: string;
}

// 16-bit PCM mono WAV encoder — fallback recording path for engines whose
// MediaRecorder has no usable audio codec (e.g. WebKitGTK on Linux).
export function encodeWav(samples: Float32Array, sampleRate: number): ArrayBuffer {
  const buf = new ArrayBuffer(44 + samples.length * 2);
  const v = new DataView(buf);
  const str = (off: number, s: string): void => {
    for (let i = 0; i < s.length; i++) {
      v.setUint8(off + i, s.charCodeAt(i));
    }
  };
  str(0, "RIFF");
  v.setUint32(4, 36 + samples.length * 2, true);
  str(8, "WAVE");
  str(12, "fmt ");
  v.setUint32(16, 16, true);
  v.setUint16(20, 1, true); // PCM
  v.setUint16(22, 1, true); // mono
  v.setUint32(24, sampleRate, true);
  v.setUint32(28, sampleRate * 2, true);
  v.setUint16(32, 2, true);
  v.setUint16(34, 16, true);
  str(36, "data");
  v.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return buf;
}

// Split an FFT magnitude spectrum (0..255 bins) into normalized bass/mid/treble
// levels (0..1) for the music-reactive core. Pure for testing.
export function bandLevels(freq: Uint8Array): { bass: number; mid: number; treble: number } {
  const n = freq.length;
  if (!n) {
    return { bass: 0, mid: 0, treble: 0 };
  }
  const avg = (lo: number, hi: number): number => {
    const a = Math.max(0, Math.floor(lo));
    const b = Math.min(n, Math.floor(hi));
    let s = 0;
    for (let i = a; i < b; i++) {
      s += freq[i];
    }
    return b > a ? s / (b - a) / 255 : 0;
  };
  return { bass: avg(0, n * 0.08), mid: avg(n * 0.08, n * 0.35), treble: avg(n * 0.35, n) };
}

export class AudioEngine {
  private ctx: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private freqData: Uint8Array<ArrayBuffer> = new Uint8Array(new ArrayBuffer(0));

  // Recording state.
  private recorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  private recMime = "audio/webm";
  private micSource: MediaStreamAudioSourceNode | null = null;

  // PCM fallback recording state (no MediaRecorder codec available).
  private pcmNode: ScriptProcessorNode | null = null;
  private pcmChunks: Float32Array[] = [];
  private pcmStream: MediaStream | null = null;

  // Playback.
  private player: HTMLAudioElement | null = null;
  private mediaSource: MediaElementAudioSourceNode | null = null;

  // Music playback (Phase 4): online stream plays IN the webview via a
  // same-origin <audio> (gateway /api/music proxy) so it flows through the
  // shared analyser and the core dances. crossOrigin is intentionally unset:
  // the /api/music URL is same-origin → never taints the analyser (a
  // cross-origin stream would zero out the FFT and the core wouldn't move).
  private music: HTMLAudioElement | null = null;
  private musicSource: MediaElementAudioSourceNode | null = null;

  onLog: (m: string) => void = () => {};

  private ensureCtx(): AudioContext {
    if (!this.ctx) {
      this.ctx = new AudioContext();
      this.analyser = this.ctx.createAnalyser();
      this.analyser.fftSize = 256;
      this.freqData = new Uint8Array(new ArrayBuffer(this.analyser.frequencyBinCount));
    }
    // Resuming on a user gesture (mousedown) keeps autoplay policies happy.
    if (this.ctx.state === "suspended") {
      void this.ctx.resume();
    }
    return this.ctx;
  }

  // Start mic capture; routes the live stream through the analyser so the HUD
  // reacts to the mic level while LISTENING. Returns once recording has started.
  async startRecording(): Promise<void> {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("非安全上下文,浏览器不提供麦克风。确认地址是 https:// 或 localhost");
    }
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mime = pickMime();
    const ctx = this.ensureCtx();
    this.micSource = ctx.createMediaStreamSource(stream);
    this.micSource.connect(this.analyser!); // analyser is a sink; not routed to output

    if (!mime) {
      // WebKitGTK has MediaRecorder but no webm/ogg encoder — capture raw PCM
      // through Web Audio and encode WAV ourselves on stop.
      this.recMime = "audio/wav";
      this.pcmChunks = [];
      this.pcmStream = stream;
      this.pcmNode = ctx.createScriptProcessor(4096, 1, 1);
      this.pcmNode.onaudioprocess = (e) => {
        this.pcmChunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
      };
      this.micSource.connect(this.pcmNode);
      // ScriptProcessor only fires when connected toward the destination; route
      // through a zero-gain node so the mic is NOT audible on the speakers.
      const mute = ctx.createGain();
      mute.gain.value = 0;
      this.pcmNode.connect(mute);
      mute.connect(ctx.destination);
      this.onLog("recording… (pcm/wav fallback)");
      return;
    }
    this.recMime = mime;
    this.chunks = [];

    this.recorder = new MediaRecorder(stream, { mimeType: mime });
    this.recorder.ondataavailable = (e) => {
      if (e.data.size) {
        this.chunks.push(e.data);
      }
    };
    this.recorder.start();
    this.onLog(`recording… (${mime})`);
  }

  // Stop capture and return the recorded blob (empty blob if nothing captured).
  async stopRecording(): Promise<CaptureResult> {
    if (this.pcmNode) {
      this.pcmNode.disconnect();
      this.pcmNode = null;
      this.pcmStream?.getTracks().forEach((t) => t.stop());
      this.pcmStream = null;
      if (this.micSource) {
        this.micSource.disconnect();
        this.micSource = null;
      }
      const total = this.pcmChunks.reduce((n, c) => n + c.length, 0);
      const samples = new Float32Array(total);
      let off = 0;
      for (const c of this.pcmChunks) {
        samples.set(c, off);
        off += c.length;
      }
      this.pcmChunks = [];
      const blob = new Blob([encodeWav(samples, this.ctx!.sampleRate)], { type: "audio/wav" });
      this.onLog(`captured ${blob.size} bytes (wav)`);
      return { blob: total ? blob : new Blob([], { type: "audio/wav" }), mime: "audio/wav" };
    }
    const rec = this.recorder;
    if (!rec || rec.state === "inactive") {
      return { blob: new Blob([], { type: this.recMime }), mime: this.recMime };
    }
    const done = new Promise<void>((res) => (rec.onstop = () => res()));
    rec.stop();
    rec.stream.getTracks().forEach((t) => t.stop());
    await done;

    if (this.micSource) {
      this.micSource.disconnect();
      this.micSource = null;
    }
    const blob = new Blob(this.chunks, { type: this.recMime });
    this.onLog(`captured ${blob.size} bytes`);
    return { blob, mime: this.recMime };
  }

  // Visible, clickable player — always present so the user can hit ▶ even if
  // autoplay is blocked. Routes playback through the analyser for SPEAKING.
  private ensurePlayer(): HTMLAudioElement {
    if (!this.player) {
      const el = document.createElement("audio");
      el.id = "tts-player";
      el.controls = true;
      el.className = "tts-player";
      document.body.appendChild(el);
      this.player = el;

      const ctx = this.ensureCtx();
      this.mediaSource = ctx.createMediaElementSource(el);
      // Tap TTS for the analyser (visuals) AND route TTS to the speakers.
      // CRITICAL: the analyser must NEVER connect to ctx.destination — the mic
      // also feeds the analyser, so analyser→destination would monitor the mic
      // out the speakers, causing acoustic feedback that corrupts every
      // recording after the first TTS playback.
      this.mediaSource.connect(this.analyser!);
      this.mediaSource.connect(ctx.destination);
    }
    return this.player;
  }

  // Play synthesized audio; returns when playback starts (or when autoplay is
  // blocked — caller can leave the visible player for a manual click).
  async play(bytes: Uint8Array<ArrayBuffer>, mime: string): Promise<void> {
    const player = this.ensurePlayer();
    const url = URL.createObjectURL(new Blob([bytes], { type: mime }));
    player.onerror = () => this.onLog("音频解码失败 (audio element error)");
    player.src = url;
    try {
      await player.play();
      this.onLog("playing ▶");
    } catch (e) {
      const err = e as Error;
      this.onLog(`自动播放被拦 (${err.name}) — 点页面上的 ▶ 手动播放`);
    }
  }

  // Wait until playback ends (or resolves immediately if no player/already ended).
  awaitPlaybackEnd(): Promise<void> {
    const player = this.player;
    if (!player || player.ended || player.paused) {
      return Promise.resolve();
    }
    return new Promise((res) => {
      player.onended = () => res();
    });
  }

  private ensureMusic(): HTMLAudioElement {
    if (!this.music) {
      const el = document.createElement("audio");
      el.id = "music-player";
      document.body.appendChild(el);
      this.music = el;
      const ctx = this.ensureCtx();
      this.musicSource = ctx.createMediaElementSource(el);
      // Same rule as TTS: analyser is a sink, NEVER → destination (the mic also
      // feeds it). Music → analyser (visuals) AND → destination (sound).
      this.musicSource.connect(this.analyser!);
      this.musicSource.connect(ctx.destination);
    }
    return this.music;
  }

  // Play an online stream by search query, proxied same-origin by the gateway.
  async playMusic(query: string): Promise<void> {
    const el = this.ensureMusic();
    el.src = `/api/music?q=${encodeURIComponent(query)}`;
    el.onerror = () => this.onLog("音乐加载/解码失败");
    try {
      await el.play();
      this.onLog(`♪ ${query}`);
    } catch (e) {
      this.onLog(`音乐自动播放被拦 (${(e as Error).name})`);
    }
  }

  stopMusic(): void {
    if (!this.music) {
      return;
    }
    this.music.pause();
    this.music.removeAttribute("src");
    this.music.load();
    this.onLog("音乐已停");
  }

  isMusicPlaying(): boolean {
    return !!this.music && !this.music.paused && !this.music.ended;
  }

  // Pause music for a clean STT window (decisions/0006 Layer 1: music must not
  // bleed into speech recognition). Returns a resume fn; no-op if not playing
  // (and a no-op resume if the music was stopped meanwhile, since play() on a
  // src-less element rejects and is swallowed).
  duckForSpeech(): () => void {
    const el = this.music;
    if (!el || el.paused) {
      return () => {};
    }
    el.pause();
    return () => void el.play().catch(() => {});
  }

  // 0..1 RMS-ish level from the FFT magnitude — drives the reactive core.
  getLevel(): number {
    if (!this.analyser) {
      return 0;
    }
    this.analyser.getByteFrequencyData(this.freqData);
    let sum = 0;
    for (let i = 0; i < this.freqData.length; i++) {
      sum += this.freqData[i] * this.freqData[i];
    }
    const rms = Math.sqrt(sum / this.freqData.length);
    return Math.min(1, rms / 180);
  }

  // Raw frequency bins (0..255) for spectrum-style rendering.
  getFrequencyBins(): Uint8Array<ArrayBuffer> {
    if (!this.analyser) {
      return new Uint8Array(new ArrayBuffer(0));
    }
    this.analyser.getByteFrequencyData(this.freqData);
    return this.freqData;
  }

  // Normalized bass/mid/treble for the music-reactive core (M3).
  getBands(): { bass: number; mid: number; treble: number } {
    if (!this.analyser) {
      return { bass: 0, mid: 0, treble: 0 };
    }
    this.analyser.getByteFrequencyData(this.freqData);
    return bandLevels(this.freqData);
  }
}
