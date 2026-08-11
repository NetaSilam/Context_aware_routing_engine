import { useEffect, useState } from "react";

import { getConversation, listConversations, sendMessage } from "../api/messages";
import ConversationList from "../components/messages/ConversationList";
import ConversationThread from "../components/messages/ConversationThread";
import type { ConversationSummary, MessageItem } from "../types/messages";
import type { UserProfile } from "../types/auth";

const CONVERSATION_PAGE_SIZE = 20;
const MESSAGE_PAGE_SIZE = 30;

interface InboxPageProps {
  user: UserProfile;
}

export default function InboxPage(props: InboxPageProps): JSX.Element {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [selectedUserId, setSelectedUserId] = useState<number | null>(null);
  const [selectedUserEmail, setSelectedUserEmail] = useState<string>("");
  const [messages, setMessages] = useState<MessageItem[]>([]);
  const [hasMoreMessages, setHasMoreMessages] = useState(false);

  async function loadConversations() {
    try {
      const page = await listConversations(0, CONVERSATION_PAGE_SIZE);
      setConversations(page.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load conversations.");
    }
  }

  useEffect(() => {
    void loadConversations();
  }, []);

  async function openConversation(otherUserId: number) {
    setError(null);
    try {
      const page = await getConversation(otherUserId, 0, MESSAGE_PAGE_SIZE);
      setMessages(page.items);
      setHasMoreMessages(page.has_more);
      setSelectedUserId(otherUserId);
      const known = conversations.find((c) => c.other_user_id === otherUserId);
      setSelectedUserEmail(known?.other_user_email ?? `User ${otherUserId}`);
      void loadConversations();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not open this conversation.");
    }
  }

  function closeConversation() {
    setSelectedUserId(null);
    setMessages([]);
    void loadConversations();
  }

  async function handleLoadMoreMessages() {
    if (selectedUserId === null) return;
    const page = await getConversation(selectedUserId, messages.length, MESSAGE_PAGE_SIZE);
    setMessages((current) => [...page.items, ...current]);
    setHasMoreMessages(page.has_more);
  }

  async function handleSend(body: string | null, file: File | null) {
    if (selectedUserId === null) return;
    const sent = await sendMessage(selectedUserId, body, file);
    setMessages((current) => [...current, sent]);
    void loadConversations();
  }

  return (
    <main className="page-shell">
      <section className="hero-panel hero-panel--illustrated">
        <div className="hero-panel__content">
          <p className="eyebrow">Direct messages</p>
          <h1>Coordinate with other drivers, one on one</h1>
          <p className="hero-panel__copy">
            Ask a reporter for more detail, arrange to share a route around a closure, or just
            say thanks for a heads-up — privately and directly.
          </p>
          <ul className="hero-panel__features">
            <li>🔒 Private &amp; secure</li>
            <li>📎 Photos &amp; videos</li>
            <li>🔔 Live delivery</li>
          </ul>
        </div>
        <div className="hero-panel__art" role="img" aria-label="A road leading toward a city skyline, marked with a safety pin" />
      </section>

      {error ? <p className="error-banner">{error}</p> : null}

      {selectedUserId !== null ? (
        <ConversationThread
          otherUserEmail={selectedUserEmail}
          myUserId={props.user.id}
          messages={messages}
          hasMore={hasMoreMessages}
          onClose={closeConversation}
          onSend={handleSend}
          onLoadMore={() => void handleLoadMoreMessages()}
        />
      ) : (
        <ConversationList
          conversations={conversations}
          onOpen={(otherUserId) => void openConversation(otherUserId)}
          onStartConversation={(recipientId) => void openConversation(recipientId)}
        />
      )}
    </main>
  );
}
