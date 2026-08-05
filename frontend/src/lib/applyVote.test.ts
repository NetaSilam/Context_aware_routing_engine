import { describe, expect, it } from "vitest";

import { applyVote } from "./applyVote";

describe("applyVote", () => {
  it("adds an upvote from no vote", () => {
    const result = applyVote({ upvote_count: 0, downvote_count: 0, my_vote: "none" as const }, "up");
    expect(result).toEqual({ upvote_count: 1, downvote_count: 0, my_vote: "up" });
  });

  it("switches an upvote to a downvote in one step", () => {
    const result = applyVote({ upvote_count: 1, downvote_count: 0, my_vote: "up" as const }, "down");
    expect(result).toEqual({ upvote_count: 0, downvote_count: 1, my_vote: "down" });
  });

  it("clears an existing vote back to none", () => {
    const result = applyVote({ upvote_count: 1, downvote_count: 0, my_vote: "up" as const }, "none");
    expect(result).toEqual({ upvote_count: 0, downvote_count: 0, my_vote: "none" });
  });

  it("re-clicking the same vote value is a no-op on counts", () => {
    const result = applyVote({ upvote_count: 3, downvote_count: 1, my_vote: "up" as const }, "up");
    expect(result).toEqual({ upvote_count: 3, downvote_count: 1, my_vote: "up" });
  });
});
