import { useRef, useState } from "react";

import { HAZARD_TYPE_LABELS, SEVERITY_LABELS } from "../../types/forum";
import type { CommentItem, PostDetail, VoteValue } from "../../types/forum";
import MediaGallery from "./MediaGallery";
import VoteButtons from "./VoteButtons";

interface PostDetailPanelProps {
  post: PostDetail;
  comments: CommentItem[];
  hasMoreComments: boolean;
  onClose: () => void;
  onVotePost: (value: VoteValue) => void;
  onVoteComment: (commentId: string, value: VoteValue) => void;
  onAddComment: (body: string, isAnonymous: boolean, files: File[]) => Promise<void>;
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
  const [commentFiles, setCommentFiles] = useState<File[]>([]);
  const [submittingComment, setSubmittingComment] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const commentFileInputRef = useRef<HTMLInputElement>(null);
  const { post } = props;

  async function submitComment(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmittingComment(true);
    try {
      await props.onAddComment(commentBody, commentAnonymous, commentFiles);
      setCommentBody("");
      setCommentAnonymous(false);
      setCommentFiles([]);
      if (commentFileInputRef.current) commentFileInputRef.current.value = "";
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
        {" "}· {new Date(post.created_at).toLocaleString()}
      </p>
      {post.llm_severity ? (
        <p
          className="forum-feed__severity"
          title="AI-estimated urgency, based on the report's own text — not verified by a person."
        >
          🤖 AI: {SEVERITY_LABELS[post.llm_severity]}
        </p>
      ) : null}
      {post.duplicate_of_post_id ? (
        <p
          className="forum-feed__duplicate"
          title="AI-detected: this report's text looks similar to a nearby report of the same hazard type."
        >
          🤖 AI: possible duplicate of "{post.duplicate_of_post_title ?? "another report"}"
        </p>
      ) : null}
      <p>{post.body}</p>
      <MediaGallery items={post.media} />
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
        <label>
          Photo or video (optional)
          <input
            ref={commentFileInputRef}
            type="file"
            accept="image/*,video/*"
            multiple
            onChange={(event) => setCommentFiles(Array.from(event.target.files ?? []))}
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
              {" "}· {new Date(comment.created_at).toLocaleString()}
            </p>
            <p>{comment.body}</p>
            <MediaGallery items={comment.media} />
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
