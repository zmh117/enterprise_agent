import type {QuestionPage} from '../../shared/live-page';
export type MessageRef = {
  key: string;
  conversation: string;
  scope: string;
  recording?: string | null;
  page?:QuestionPage;
};

export type Chat = {
  conversation: string;
  jobs: string[];
  awaiting: MessageRef[];
  recordingScope?: string;
  recording?: string | null;
};

export type Receipt = {
  job_id: string;
  conversation_id: string;
  recording_id: string | null;
};

export async function loadChat(key: string): Promise<Chat> {
  const saved = (await chrome.storage.local.get(key))[key] as
    Partial<Chat> | undefined;
  return {
    recordingScope:
      typeof saved?.recordingScope === 'string'
        ? saved.recordingScope
        : undefined,
    recording: typeof saved?.recording === 'string' ? saved.recording : null,
    conversation:
      typeof saved?.conversation === 'string' ? saved.conversation : '',
    jobs: Array.isArray(saved?.jobs)
      ? saved.jobs.filter((id) => typeof id === 'string').slice(-20)
      : [],
    awaiting: Array.isArray(saved?.awaiting)
      ? saved.awaiting.filter(
          (ref) =>
            ref &&
            typeof ref.key === 'string' &&
            typeof ref.conversation === 'string' &&
            typeof ref.scope === 'string',
        )
      : [],
  };
}

// Each console can submit independently. Update references under a short lock
// so a late receipt from another window cannot overwrite pending submissions.
async function update(
  key: string,
  change: (chat: Chat) => void,
): Promise<Chat> {
  return navigator.locks.request(key, async () => {
    const chat = await loadChat(key);
    change(chat);
    await chrome.storage.local.set({ [key]: chat });
    return chat;
  });
}

export function chooseConversation(key: string, conversation: string) {
  return update(key, chat => {
    if (chat.awaiting.length) throw new Error('有一条消息正在确认回执，请先恢复发送。');
    if (chat.conversation !== conversation) {
      chat.conversation = conversation;
      chat.jobs = [];
      chat.recording = null;
      chat.recordingScope = undefined;
    }
  });
}

export function rememberMessage(key: string, ref: MessageRef) {
  return update(key, (chat) => {
    if (!chat.awaiting.some((item) => item.key === ref.key))
      chat.awaiting.push(ref);
  });
}

export async function finishMessage(key: string, ref: MessageRef, receipt?: Receipt) {
  const saved = await update(key, (chat) => {
    if (!chat.awaiting.some((item) => item.key === ref.key)) return;
    if (receipt && (chat.conversation === ref.conversation || chat.conversation === receipt.conversation_id)) {
      if (chat.conversation !== receipt.conversation_id) chat.jobs = [];
      chat.conversation = receipt.conversation_id;
      chat.recording = receipt.recording_id;
      chat.recordingScope = ref.scope;
      if (!chat.jobs.includes(receipt.job_id)) chat.jobs.push(receipt.job_id);
      chat.jobs = chat.jobs.slice(-20);
    }
    chat.awaiting = chat.awaiting.filter((item) => item.key !== ref.key);
  });
  if (receipt && saved.conversation !== receipt.conversation_id) {
    // Another window selected its own conversation. Show this receipt only to the sender.
    return {...saved, conversation:receipt.conversation_id, jobs:[receipt.job_id],
      recording:receipt.recording_id, recordingScope:ref.scope, awaiting:[]};
  }
  return saved;
}
