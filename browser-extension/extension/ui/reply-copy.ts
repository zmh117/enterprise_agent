// Embedded assistants can run on HTTP sites where the async clipboard is unavailable.
function copyDuringClick(text: string): boolean {
  let written = false;
  function onCopy(event: ClipboardEvent) {
    if (!event.clipboardData) return;
    event.clipboardData.setData('text/plain', text);
    event.preventDefault();
    written = true;
  }
  document.addEventListener('copy', onCopy, true);
  try {
    return document.execCommand('copy') && written;
  } finally {
    document.removeEventListener('copy', onCopy, true);
  }
}

export async function copyReply(button: HTMLButtonElement, text: string) {
  if (button.dataset.feedback) return;
  let copied = false;
  try {
    if (window !== window.top || !navigator.clipboard) copied = copyDuringClick(text);
    if (!copied) {
      await navigator.clipboard.writeText(text);
      copied = true;
    }
  } catch {
    // The embedding page or browser may also block clipboard writes.
  }
  const message = copied ? '已复制' : '复制失败，请手动复制';
  button.dataset.feedback = copied ? 'success' : 'error';
  button.textContent = message;
  button.setAttribute('aria-label', message);
  button.title = message;
  window.setTimeout(() => {
    delete button.dataset.feedback;
    button.textContent = '';
    button.setAttribute('aria-label', '复制回复');
    button.title = '复制回复';
  }, 2200);
}
