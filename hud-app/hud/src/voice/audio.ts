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

export class AudioEngine {
  private ctx: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private freqData: Uint8Array<ArrayBuffer> = new Uint8Array(new ArrayBuffer(0));

  // Recording state.
  private recorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  private recMime = "audio/webm";
  private micSource: MediaStreamAudioSourceNode | null = null;

  // Playback.
  private player: HTMLAudioElement | null = null;
  private mediaSource: MediaElementAudioSourceNode | null = null;

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
    if (!mime) {
      stream.getTracks().forEach((t) => t.stop());
      throw new Error("浏览器不支持 webm/ogg 录制");
    }
    this.recMime = mime;
    this.chunks = [];

    const ctx = this.ensureCtx();
    this.micSource = ctx.createMediaStreamSource(stream);
    this.micSource.connect(this.analyser!); // analyser is a sink; not routed to output

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
}
