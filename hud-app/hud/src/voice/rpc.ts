// Typed WS JSON-RPC client. Ported verbatim from voice-harness.html: same
// methods, same event handling (resolve pending replies on message.complete).

import type { AgentReply } from "./session.ts";
import { synthesizeHttp, transcribeHttp, useHttpVoice } from "./voice_http.ts";

export interface TranscribeResult {
  text: string;
}

export interface SynthesizeResult {
  audio: string; // base64
  mime: string;
}

interface RpcResponse<T = unknown> {
  id?: number;
  result?: T;
  error?: { message: string; code?: number };
  method?: string;
  params?: { type: string; payload?: { text?: string; end?: boolean } };
}

export type RpcStatus = "connecting" | "open" | "closed" | "error";

// Build the WS URL following the page scheme: an https page must use wss://
// (a ws:// from https is blocked as mixed content).
// `window.__JARVIS_WS_URL__` overrides — the Tauri shell injects it because under
// the tauri:// protocol location.host has no usable port.
export function wsUrl(): string {
  const override = (window as { __JARVIS_WS_URL__?: string }).__JARVIS_WS_URL__;
  if (override) {
    return override;
  }
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${location.host || "localhost:8765"}/api/ws`;
}

export class VoiceRpc {
  private ws: WebSocket | null = null;
  private ridSeq = 1;
  private pending = new Map<number, (msg: RpcResponse) => void>();
  private sessionId: string | null = null;

  // Reply tracking for the async agent turn (message.complete event).
  private replyText = "";
  private replyEnd = false; // payload.end — agent 判会话结束(decisions/0007)
  private awaitingReply = false;
  private replyDone: (() => void) | null = null;

  onStatus: (s: RpcStatus, detail?: string) => void = () => {};
  onLog: (m: string) => void = () => {};

  connect(): Promise<void> {
    const url = wsUrl();
    this.onLog(`connecting ${url} …`);
    this.onStatus("connecting");
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(url);
      this.ws = ws;
      ws.onopen = () => {
        this.onLog("WS connected");
        this.onStatus("open");
        resolve();
      };
      ws.onclose = (e) => {
        this.onLog(`WS closed (code ${e.code})`);
        this.onStatus("closed");
        // 旧会话随网关连接失效:清掉缓存的 session_id,重连后 ensureSession 会新建。
        // 否则网关重启后 HUD 仍用失效会话 submit,永远等不到 message.complete → 超时
        //(前端念"没听清,再说一次")。
        this.sessionId = null;
        // 若有正在等待的回复,断开即解掉(那一轮作废返回空),别卡到 30s 超时
        if (this.awaitingReply) {
          this.awaitingReply = false;
          this.replyText = "";
          this.replyEnd = false; // 断线作废轮:勿让残留 end 触发误退会话
          this.replyDone?.();
        }
        // 网关重启后自动重连,语音通道不用手动重启 HUD
        setTimeout(() => void this.connect().catch(() => {}), 2000);
      };
      ws.onerror = () => {
        this.onLog("WS ERROR — 若是 wss 证书问题,先单独打开页面接受证书");
        this.onStatus("error");
        reject(new Error("ws error"));
      };
      ws.onmessage = (ev) => this.handleMessage(ev);
    });
  }

  private handleMessage(ev: MessageEvent): void {
    const msg = JSON.parse(ev.data as string) as RpcResponse;
    if (msg.id && this.pending.has(msg.id)) {
      const resolve = this.pending.get(msg.id)!;
      this.pending.delete(msg.id);
      resolve(msg);
      return;
    }
    if (msg.method === "event" && msg.params) {
      const { type, payload } = msg.params;
      if (type === "message.complete" && this.awaitingReply) {
        this.replyText = payload?.text ?? "";
        this.replyEnd = payload?.end ?? false;
        this.awaitingReply = false;
        this.replyDone?.();
      }
    }
  }

  private rpc<T = unknown>(method: string, params: unknown): Promise<RpcResponse<T>> {
    return new Promise((resolve) => {
      const id = this.ridSeq++;
      this.pending.set(id, resolve as (m: RpcResponse) => void);
      this.ws?.send(JSON.stringify({ jsonrpc: "2.0", id, method, params }));
    });
  }

  async ensureSession(): Promise<string> {
    if (this.sessionId) {
      return this.sessionId;
    }
    const r = await this.rpc<{ session_id: string }>("session.create", { cols: 80 });
    this.sessionId = r.result!.session_id;
    this.onLog(`session: ${this.sessionId}`);
    return this.sessionId;
  }

  async transcribe(audio: string, mime: string): Promise<string> {
    // phase5: fetch the standalone voice service directly (flag default false →
    // legacy WS path below, unchanged). New logic lives in voice_http.ts.
    if (useHttpVoice()) {
      return transcribeHttp(audio, mime);
    }
    const tr = await this.rpc<TranscribeResult>("voice.transcribe", { audio, mime });
    if (tr.error) {
      this.onLog(`STT error: ${tr.error.message}`);
      return "";
    }
    return tr.result?.text ?? "";
  }

  // Submit a prompt and await the agent's reply (resolved via message.complete).
  async submitPrompt(text: string): Promise<AgentReply> {
    const sessionId = await this.ensureSession();
    this.replyText = "";
    this.replyEnd = false;
    this.awaitingReply = true;
    const waitReply = new Promise<void>((res) => (this.replyDone = res));
    await this.rpc("prompt.submit", { session_id: sessionId, text });
    await waitReply;
    return { text: this.replyText, end: this.replyEnd };
  }

  async synthesize(text: string): Promise<SynthesizeResult | null> {
    if (useHttpVoice()) {
      return synthesizeHttp(text);
    }
    const syn = await this.rpc<SynthesizeResult>("voice.synthesize", { text });
    if (syn.error) {
      this.onLog(`TTS error: ${syn.error.message}`);
      return null;
    }
    return syn.result ?? null;
  }
}
