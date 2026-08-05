import type { VoteValue } from "../../types/forum";

interface VoteButtonsProps {
  upvoteCount: number;
  downvoteCount: number;
  myVote: VoteValue;
  disabled?: boolean;
  onVote: (value: VoteValue) => void;
}

export default function VoteButtons(props: VoteButtonsProps): JSX.Element {
  function toggle(value: "up" | "down") {
    props.onVote(props.myVote === value ? "none" : value);
  }

  return (
    <div className="forum-vote-buttons" role="group" aria-label="Vote">
      <button
        type="button"
        className={
          props.myVote === "up" ? "forum-vote-button forum-vote-button--active-up" : "forum-vote-button"
        }
        disabled={props.disabled}
        aria-pressed={props.myVote === "up"}
        onClick={() => toggle("up")}
      >
        &#9650; {props.upvoteCount}
      </button>
      <button
        type="button"
        className={
          props.myVote === "down"
            ? "forum-vote-button forum-vote-button--active-down"
            : "forum-vote-button"
        }
        disabled={props.disabled}
        aria-pressed={props.myVote === "down"}
        onClick={() => toggle("down")}
      >
        &#9660; {props.downvoteCount}
      </button>
    </div>
  );
}
