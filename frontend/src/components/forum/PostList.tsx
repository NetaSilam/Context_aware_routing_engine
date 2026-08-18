import { HAZARD_TYPE_LABELS, HAZARD_TYPES, SEVERITY_LABELS } from "../../types/forum";
import type { HazardType, PostSummary } from "../../types/forum";
import VoteButtons from "./VoteButtons";

interface PostListProps {
  items: PostSummary[];
  hazardType: HazardType | "";
  hasMore: boolean;
  onFilterChange: (hazardType: HazardType | "") => void;
  onOpen: (postId: string) => void;
  onLoadMore: () => void;
  onVote: (postId: string, value: "up" | "down" | "none") => void;
}

export default function PostList(props: PostListProps): JSX.Element {
  return (
    <section className="filters-panel forum-feed" aria-label="Hazard reports">
      <label className="forum-feed__filter">
        Filter by hazard type
        <select
          value={props.hazardType}
          onChange={(event) => props.onFilterChange(event.target.value as HazardType | "")}
        >
          <option value="">All hazard types</option>
          {HAZARD_TYPES.map((type) => (
            <option key={type} value={type}>
              {HAZARD_TYPE_LABELS[type]}
            </option>
          ))}
        </select>
      </label>

      <div className="forum-feed__legend">
        <p>
          🤖 <strong>AI severity</strong> estimates how urgently drivers should treat a hazard
          (Low/Medium/High) from the report's own text.
        </p>
        <p>
          🤖 <strong>AI duplicate</strong> flags reports that likely describe the same hazard as
          another nearby report.
        </p>
        <p>Neither is verified by a person — treat them as a helpful hint, not a guarantee.</p>
      </div>

      {props.items.length === 0 ? <p>No hazard reports yet.</p> : null}

      <ul className="forum-feed__list">
        {props.items.map((post) => (
          <li key={post.id} className="forum-feed__item">
            <button type="button" className="forum-feed__title" onClick={() => props.onOpen(post.id)}>
              {post.title}
              {post.has_media ? (
                <span className="forum-feed__media-badge" title="This report includes a photo or video">
                  📷
                </span>
              ) : null}
            </button>
            <p className="forum-feed__meta">
              {HAZARD_TYPE_LABELS[post.hazard_type]} ·{" "}
              {post.is_anonymous
                ? post.is_own
                  ? "Anonymous (you)"
                  : "Anonymous"
                : post.author_email}{" "}
              · {post.comment_count} comment{post.comment_count === 1 ? "" : "s"} ·{" "}
              {new Date(post.created_at).toLocaleString()}
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
                🤖 AI: possible duplicate of report {post.duplicate_of_post_id}
              </p>
            ) : null}
            <VoteButtons
              upvoteCount={post.upvote_count}
              downvoteCount={post.downvote_count}
              myVote={post.my_vote}
              onVote={(value) => props.onVote(post.id, value)}
            />
          </li>
        ))}
      </ul>

      {props.hasMore ? (
        <button type="button" className="ghost-button" onClick={props.onLoadMore}>
          Load more
        </button>
      ) : null}
    </section>
  );
}
