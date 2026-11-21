/**
 * Estado global compartido de la aplicación web.
 */
export const state = {
  activeChatId: null,
  chats: [],
  messages: [],
  documentsCache: null,
  isSending: false,
  isLoadingChat: false,
};
