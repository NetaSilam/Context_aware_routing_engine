// jsdom (vitest's default test environment) has no EventSource implementation at all, so any
// component that opens one (NotificationIndicator, ForumPage's forum-activity stream,
// MessagesPage's live-conversation-update stream) throws "EventSource is not defined" the
// instant it renders in a test that doesn't stub it. A no-op default here means only the tests
// that actually care about SSE behavior need their own vi.stubGlobal("EventSource", ...); every
// other test just gets a connection that never fires, which is exactly what "not testing this"
// should look like.
class NoopEventSource {
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(
    public url: string,
    public options?: EventSourceInit,
  ) {}

  close(): void {
    // no-op
  }
}

if (typeof globalThis.EventSource === "undefined") {
  (globalThis as unknown as { EventSource: typeof NoopEventSource }).EventSource = NoopEventSource;
}
