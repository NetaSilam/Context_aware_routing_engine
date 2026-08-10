import { useState } from "react";

import type { ConversationSummary } from "../../types/messages";

interface ConversationListProps {
  conversations: ConversationSummary[];
  onOpen: (otherUserId: number) => void;
  onStartConversation: (recipientId: number) => void;
}

export default function ConversationList(props: ConversationListProps): JSX.Element {
  const [recipientInput, setRecipientInput] = useState("");
  const [error, setError] = useState<string | null>(null);

  function handleStart(event: React.FormEvent) {
    event.preventDefault();
    const recipientId = Number(recipientInput);
    if (!Number.isInteger(recipientId) || recipientId <= 0) {
      setError("Enter a valid user ID.");
      return;
    }
    setError(null);
    props.onStartConversation(recipientId);
    setRecipientInput("");
  }

  return (
    <section className="filters-panel" aria-label="Conversations">
      <form className="forum-post-form" aria-label="Start a conversation" onSubmit={handleStart}>
        {error ? <p className="error-banner">{error}</p> : null}
        <label>
          Message a user by ID
          <input
            value={recipientInput}
            inputMode="numeric"
            onChange={(event) => setRecipientInput(event.target.value)}
          />
        </label>
        <button type="submit" className="ghost-button">
          Start conversation
        </button>
      </form>

      {props.conversations.length === 0 ? <p>No conversations yet.</p> : null}
      <ul className="forum-feed__list">
        {props.conversations.map((conversation) => (
          <li key={conversation.other_user_id} className="forum-feed__item">
            <button
              type="button"
              className="forum-feed__title"
              onClick={() => props.onOpen(conversation.other_user_id)}
            >
              {conversation.other_user_email}
            </button>
            <p className="forum-feed__meta">
              {conversation.last_message_body ?? "(attachment)"}
              {conversation.unread_count > 0 ? ` · ${conversation.unread_count} unread` : ""}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}
