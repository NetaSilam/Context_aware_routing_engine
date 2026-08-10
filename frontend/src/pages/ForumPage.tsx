import { useEffect, useState } from "react";

import {
  createComment,
  createPost,
  deletePost as deletePostRequest,
  getMyForumDashboard,
  getPost,
  listComments,
  listPosts,
  uploadCommentMedia,
  uploadPostMedia,
  voteOnComment,
  voteOnPost,
} from "../api/forum";
import PostDetailPanel from "../components/forum/PostDetailPanel";
import PostForm from "../components/forum/PostForm";
import PostList from "../components/forum/PostList";
import { applyVote } from "../lib/applyVote";
import type { CommentItem, DashboardSummary, HazardType, PostDetail, PostSummary, VoteValue } from "../types/forum";

const PAGE_SIZE = 20;
const COMMENT_PAGE_SIZE = 30;

export default function ForumPage(): JSX.Element {
  const [posts, setPosts] = useState<PostSummary[]>([]);
  const [hazardType, setHazardType] = useState<HazardType | "">("");
  const [feedHasMore, setFeedHasMore] = useState(false);
  const [feedError, setFeedError] = useState<string | null>(null);

  const [selectedPost, setSelectedPost] = useState<PostDetail | null>(null);
  const [comments, setComments] = useState<CommentItem[]>([]);
  const [commentsHasMore, setCommentsHasMore] = useState(false);

  const [dashboard, setDashboard] = useState<DashboardSummary | null>(null);

  async function loadFeed(filter: HazardType | "") {
    setFeedError(null);
    try {
      const page = await listPosts(0, PAGE_SIZE, filter || undefined);
      setPosts(page.items);
      setFeedHasMore(page.has_more);
    } catch (err) {
      setFeedError(err instanceof Error ? err.message : "Could not load the hazard feed.");
    }
  }

  useEffect(() => {
    void loadFeed(hazardType);
    getMyForumDashboard()
      .then(setDashboard)
      .catch(() => setDashboard(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hazardType]);

  async function handleFilterChange(next: HazardType | "") {
    setHazardType(next);
  }

  async function handleLoadMoreFeed() {
    try {
      const page = await listPosts(posts.length, PAGE_SIZE, hazardType || undefined);
      setPosts((current) => [...current, ...page.items]);
      setFeedHasMore(page.has_more);
    } catch (err) {
      setFeedError(err instanceof Error ? err.message : "Could not load more reports.");
    }
  }

  async function handleCreatePost(payload: Parameters<typeof createPost>[0], files: File[]) {
    const created = await createPost(payload);
    for (const file of files) {
      await uploadPostMedia(created.id, file);
    }
    setPosts((current) => [
      {
        id: created.id,
        title: created.title,
        hazard_type: created.hazard_type,
        longitude: created.longitude,
        latitude: created.latitude,
        author_id: created.author_id,
        author_email: created.author_email,
        is_anonymous: created.is_anonymous,
        is_own: created.is_own,
        upvote_count: created.upvote_count,
        downvote_count: created.downvote_count,
        comment_count: created.comment_count,
        my_vote: created.my_vote,
        created_at: created.created_at,
        updated_at: created.updated_at,
        llm_hazard_type_suggested: created.llm_hazard_type_suggested,
        llm_severity: created.llm_severity,
        duplicate_of_post_id: created.duplicate_of_post_id,
      },
      ...current,
    ]);
    setDashboard((current) =>
      current ? { ...current, post_count: current.post_count + 1 } : current,
    );
  }

  async function openPost(postId: string) {
    setFeedError(null);
    try {
      const [post, commentPage] = await Promise.all([
        getPost(postId),
        listComments(postId, 0, COMMENT_PAGE_SIZE),
      ]);
      setSelectedPost(post);
      setComments(commentPage.items);
      setCommentsHasMore(commentPage.has_more);
    } catch (err) {
      setFeedError(err instanceof Error ? err.message : "Could not open this report.");
    }
  }

  function closeDetail() {
    setSelectedPost(null);
    setComments([]);
    void loadFeed(hazardType);
  }

  function handleVoteOnFeedPost(postId: string, value: VoteValue) {
    setPosts((current) =>
      current.map((post) => (post.id === postId ? applyVote(post, value) : post)),
    );
    void voteOnPost(postId, value).catch(() => void loadFeed(hazardType));
  }

  function handleVoteOnDetailPost(value: VoteValue) {
    if (!selectedPost) return;
    const postId = selectedPost.id;
    setSelectedPost((current) => (current ? applyVote(current, value) : current));
    void voteOnPost(postId, value).catch(() => void openPost(postId));
  }

  function handleVoteOnComment(commentId: string, value: VoteValue) {
    setComments((current) =>
      current.map((comment) => (comment.id === commentId ? applyVote(comment, value) : comment)),
    );
    void voteOnComment(commentId, value).catch(() => {
      if (selectedPost) void openPost(selectedPost.id);
    });
  }

  async function handleAddComment(body: string, isAnonymous: boolean, files: File[]) {
    if (!selectedPost) return;
    const created = await createComment(selectedPost.id, { body, is_anonymous: isAnonymous });
    let media = created.media;
    for (const file of files) {
      const uploaded = await uploadCommentMedia(created.id, file);
      media = [...media, uploaded];
    }
    setComments((current) => [...current, { ...created, media }]);
    setSelectedPost((current) =>
      current ? { ...current, comment_count: current.comment_count + 1 } : current,
    );
  }

  async function handleLoadMoreComments() {
    if (!selectedPost) return;
    const page = await listComments(selectedPost.id, comments.length, COMMENT_PAGE_SIZE);
    setComments((current) => [...current, ...page.items]);
    setCommentsHasMore(page.has_more);
  }

  async function handleDeletePost() {
    if (!selectedPost) return;
    await deletePostRequest(selectedPost.id);
    closeDetail();
  }

  return (
    <main className="page-shell">
      <section className="hero-panel">
        <p className="eyebrow">Community reports</p>
        <h1>Hazard reporting feed</h1>
        <p className="hero-panel__copy">
          Report potholes, flooding, broken signals, and other road hazards. Confirm or refute
          reports from other drivers with a vote.
        </p>
        {dashboard ? (
          <p className="forum-feed__meta">
            Your reports: {dashboard.post_count} · Your comments: {dashboard.comment_count} · Net
            votes received: {dashboard.net_votes_received}
          </p>
        ) : null}
      </section>

      {feedError ? <p className="error-banner">{feedError}</p> : null}

      {selectedPost ? (
        <PostDetailPanel
          post={selectedPost}
          comments={comments}
          hasMoreComments={commentsHasMore}
          onClose={closeDetail}
          onVotePost={handleVoteOnDetailPost}
          onVoteComment={handleVoteOnComment}
          onAddComment={handleAddComment}
          onDeletePost={handleDeletePost}
          onLoadMoreComments={() => void handleLoadMoreComments()}
        />
      ) : (
        <>
          <PostForm onSubmit={handleCreatePost} />
          <PostList
            items={posts}
            hazardType={hazardType}
            hasMore={feedHasMore}
            onFilterChange={(next) => void handleFilterChange(next)}
            onOpen={(postId) => void openPost(postId)}
            onLoadMore={() => void handleLoadMoreFeed()}
            onVote={handleVoteOnFeedPost}
          />
        </>
      )}
    </main>
  );
}
