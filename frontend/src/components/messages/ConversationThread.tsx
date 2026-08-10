import { useRef, useState } from "react";

import MediaGallery from "../forum/MediaGallery";
import type { MessageItem } from "../../types/messages";

interface ConversationThreadProps {
  otherUserEmail: string;
  myUserId: number;
  messages: MessageItem[];
  hasMore: boolean;
  onClose: () => void;
  onSend: (body: string | null, file: File | null) => Promise<void>;
  onLoadMore: () => void;
}

export default function ConversationThread(props: ConversationThreadProps): JSX.Element {
  const [body, setBody] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!body.trim() && !file) {
      setError("Write a message or attach a photo/video.");
      return;
    }
    setError(null);
    setSending(true);
    try {
      await props.onSend(body.trim() || null, file);
      setBody("");
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send the message.");
    } finally {
      setSending(false);
    }
  }

  return (
    <section className="detail-panel forum-post-detail" aria-label="Conversation">
      <button type="button" className="ghost-button" onClick={props.onClose}>
        Back to conversations
      </button>
      <h2>{props.otherUserEmail}</h2>

      {props.hasMore ? (
        <button type="button" className="ghost-button" onClick={props.onLoadMore}>
          Load older messages
        </button>
      ) : null}

      <ul className="forum-feed__list">
        {props.messages.map((message) => (
          <li key={message.id} className="forum-feed__item">
            <p className="forum-feed__meta">
              {message.sender_user_id === props.myUserId ? "You" : props.otherUserEmail}
              {message.sender_user_id === props.myUserId && message.read_at ? " · Read" : ""}
            </p>
            {message.body ? <p>{message.body}</p> : null}
            <MediaGallery items={message.media ? [message.media] : []} />
          </li>
        ))}
      </ul>

      {error ? <p className="error-banner">{error}</p> : null}
      <form className="forum-post-form" aria-label="Send a message" onSubmit={handleSubmit}>
        <label>
          Message
          <textarea
            value={body}
            maxLength={2000}
            rows={2}
            onChange={(event) => setBody(event.target.value)}
          />
        </label>
        <label>
          Photo or video (optional)
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*,video/*"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
        </label>
        <button type="submit" className="primary-button" disabled={sending}>
          {sending ? "Sending…" : "Send"}
        </button>
      </form>
    </section>
  );
}
