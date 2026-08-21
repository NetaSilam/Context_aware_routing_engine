import type { ConversationSummary } from "../../types/messages";

interface ConversationListProps {
  conversations: ConversationSummary[];
  onOpen: (otherUserId: number) => void;
}

export default function ConversationList(props: ConversationListProps): JSX.Element {
  return (
    <section className="filters-panel" aria-label="Conversations">
      {props.conversations.length === 0 ? (
        <p>
          No conversations yet. Open a hazard report from someone else and click "Message" to
          start one.
        </p>
      ) : null}
      <ul className="forum-feed__list">
        {props.conversations.map((conversation) => (
          <li key={conversation.other_user_id} className="forum-feed__item">
            <div className="forum-feed__item-body">
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
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
