import { useEffect, useRef, useState } from "react";

import { NOTIFICATIONS_STREAM_URL } from "../api/notifications";
import { getConversation, listConversations, sendMessage } from "../api/messages";
import ConversationList from "../components/messages/ConversationList";
import ConversationThread from "../components/messages/ConversationThread";
import type { ConversationSummary, MessageItem } from "../types/messages";
import type { UserProfile } from "../types/auth";

const CONVERSATION_PAGE_SIZE = 20;
const MESSAGE_PAGE_SIZE = 30;

export interface MessageTarget {
  id: number;
  email: string;
}

interface MessagesPageProps {
  user: UserProfile;
  initialTarget?: MessageTarget | null;
  onInitialTargetConsumed?: () => void;
}

export default function MessagesPage(props: MessagesPageProps): JSX.Element {
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function openConversation(otherUserId: number, knownEmail?: string) {
    setError(null);
    try {
      const page = await getConversation(otherUserId, 0, MESSAGE_PAGE_SIZE);
      setMessages(page.items);
      setHasMoreMessages(page.has_more);
      setSelectedUserId(otherUserId);
      const known = conversations.find((c) => c.other_user_id === otherUserId);
      setSelectedUserEmail(known?.other_user_email ?? knownEmail ?? `User ${otherUserId}`);
      void loadConversations();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not open this conversation.");
    }
  }

  // A "Message" click elsewhere in the app (e.g. from a hazard report) hands off a target
  // user here instead of making the caller know about conversation state directly.
  useEffect(() => {
    if (!props.initialTarget) return;
    void openConversation(props.initialTarget.id, props.initialTarget.email);
    props.onInitialTargetConsumed?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.initialTarget]);

  const selectedUserIdRef = useRef<number | null>(null);
  useEffect(() => {
    selectedUserIdRef.current = selectedUserId;
  }, [selectedUserId]);

  // A message arriving while its conversation is open must appear without the user closing
  // and reopening the thread. The notification stream already reaches this recipient in real
  // time (it's how the header badge updates); this reuses that same connection rather than
  // opening a second one, and reacts only to the one kind relevant here.
  useEffect(() => {
    const source = new EventSource(NOTIFICATIONS_STREAM_URL, { withCredentials: true });
    source.onmessage = (event) => {
      let parsed: { kind?: string; payload?: { sender_user_id?: number } } = {};
      try {
        parsed = JSON.parse(event.data);
      } catch {
        return;
      }
      if (parsed.kind !== "new_dm") return;
      if (parsed.payload?.sender_user_id === selectedUserIdRef.current) {
        void openConversation(selectedUserIdRef.current);
      } else {
        void loadConversations();
      }
    };
    return () => source.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
        />
      )}
    </main>
  );
}
