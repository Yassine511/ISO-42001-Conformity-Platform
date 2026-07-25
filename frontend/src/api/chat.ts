// Grounded chat copilot (M4).
// Domain slice of the API client — assembled into `api` by ./index.ts.
import { json, post } from "./http";
import type {
  ChatMessage,
  Conversation,
} from "./types";

export const chatApi = {
  // chat
  listConversations: (orgId: string) =>
    fetch(`/api/organizations/${orgId}/chat/conversations`).then((r) =>
      json<Conversation[]>(r),
    ),
  listMessages: (orgId: string, conversationId: string) =>
    fetch(`/api/organizations/${orgId}/chat/conversations/${conversationId}/messages`).then(
      (r) => json<ChatMessage[]>(r),
    ),
  postMessage: (
    orgId: string,
    question: string,
    conversationId?: string,
    findingId?: string,
    kbOnly?: boolean,
  ) =>
    post(`/api/organizations/${orgId}/chat/messages`, {
      question,
      conversation_id: conversationId ?? null,
      finding_id: findingId ?? null,
      kb_only: kbOnly ?? false,
    }).then((r) => json<ChatMessage>(r)),
};
