import { useState } from "react";

import { HAZARD_TYPE_LABELS } from "../../types/forum";
import type { CommentItem, PostDetail, VoteValue } from "../../types/forum";
import VoteButtons from "./VoteButtons";

interface PostDetailPanelProps {
  post: PostDetail;
  comments: CommentItem[];
  hasMoreComments: boolean;
  onClose: () => void;
  onVotePost: (value: VoteValue) => void;
  onVoteComment: (commentId: string, value: VoteValue) => void;
  onAddComment: (body: string, isAnonymous: boolean) => Promise<void>;
  onDeletePost: () => Promise<void>;
  onLoadMoreComments: () => void;
}

function authorLabel(isAnonymous: boolean, isOwn: boolean, email: string | null): string {
  if (!isAnonymous) return email ?? "Unknown";
  return isOwn ? "Anonymous (you)" : "Anonymous";
}

export default function PostDetailPanel(props: PostDetailPanelProps): JSX.Element {
  const [commentBody, setCommentBody] = useState("");
  const [commentAnonymous, setCommentAnonymous] = useState(false);
  const [submittingComment, setSubmittingComment] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { post } = props;

  async function submitComment(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmittingComment(true);
    try {
      await props.onAddComment(commentBody, commentAnonymous);
      setCommentBody("");
      setCommentAnonymous(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not post the comment.");
    } finally {
      setSubmittingComment(false);
    }
  }

  return (
    <section className="detail-panel forum-post-detail" aria-label="Hazard report detail">
      <button type="button" className="ghost-button" onClick={props.onClose}>
        Back to feed
      </button>
      <h2>{post.title}</h2>
      <p className="forum-feed__meta">
        {HAZARD_TYPE_LABELS[post.hazard_type]} · {authorLabel(post.is_anonymous, post.is_own, post.author_email)}
      </p>
      <p>{post.body}</p>
      <VoteButtons
        upvoteCount={post.upvote_count}
        downvoteCount={post.downvote_count}
        myVote={post.my_vote}
        onVote={props.onVotePost}
      />
      {post.is_own ? (
        <button type="button" className="ghost-button" onClick={() => void props.onDeletePost()}>
          Delete report
        </button>
      ) : null}

      <h3>Comments</h3>
      {error ? <p className="error-banner">{error}</p> : null}
      <form className="forum-post-form" aria-label="Comment form" onSubmit={submitComment}>
        <label>
          Add a comment
          <textarea
            value={commentBody}
            maxLength={2000}
            required
            rows={2}
            onChange={(event) => setCommentBody(event.target.value)}
          />
        </label>
        <label className="forum-post-form__checkbox">
          <input
            type="checkbox"
            checked={commentAnonymous}
            onChange={(event) => setCommentAnonymous(event.target.checked)}
          />
          Comment anonymously
        </label>
        <button type="submit" className="primary-button" disabled={submittingComment}>
          {submittingComment ? "Posting…" : "Post comment"}
        </button>
      </form>

      <ul className="forum-feed__list">
        {props.comments.map((comment) => (
          <li key={comment.id} className="forum-feed__item">
            <p className="forum-feed__meta">
              {authorLabel(comment.is_anonymous, comment.is_own, comment.author_email)}
            </p>
            <p>{comment.body}</p>
            <VoteButtons
              upvoteCount={comment.upvote_count}
              downvoteCount={comment.downvote_count}
              myVote={comment.my_vote}
              onVote={(value) => props.onVoteComment(comment.id, value)}
            />
          </li>
        ))}
      </ul>
      {props.hasMoreComments ? (
        <button type="button" className="ghost-button" onClick={props.onLoadMoreComments}>
          Load more comments
        </button>
      ) : null}
    </section>
  );
}
