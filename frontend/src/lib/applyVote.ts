import type { VoteValue } from "../types/forum";

export interface Votable {
  upvote_count: number;
  downvote_count: number;
  my_vote: VoteValue;
}

export function applyVote<T extends Votable>(item: T, next: VoteValue): T {
  const upDelta = (next === "up" ? 1 : 0) - (item.my_vote === "up" ? 1 : 0);
  const downDelta = (next === "down" ? 1 : 0) - (item.my_vote === "down" ? 1 : 0);
  return {
    ...item,
    upvote_count: item.upvote_count + upDelta,
    downvote_count: item.downvote_count + downDelta,
    my_vote: next,
  };
}
