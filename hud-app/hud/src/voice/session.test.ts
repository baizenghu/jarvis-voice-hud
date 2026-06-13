import { describe, expect, it } from "vitest";
import { orderActions, type Action } from "./session.ts";

describe("orderActions", () => {
  it("play_music 永远排在 end_session 之前", () => {
    const a: Action[] = [{ type: "end_session" }, { type: "play_music", query: "晴天" }];
    expect(orderActions(a).map((x) => x.type)).toEqual(["play_music", "end_session"]);
  });
  it("stop_music 保持在前,end_session 最后", () => {
    const a: Action[] = [{ type: "end_session" }, { type: "stop_music" }];
    expect(orderActions(a).map((x) => x.type)).toEqual(["stop_music", "end_session"]);
  });
});
