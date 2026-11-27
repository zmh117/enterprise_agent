// Chrome rejects extension API calls with "No SW" if their originating worker has stopped.
// Use only for event callbacks or presentation work without a caller awaiting the result.
export async function observeWorkerTask(operation: string, task: Promise<unknown>): Promise<void> {
  try {
    await task;
  } catch (error) {
    if (error instanceof Error && error.message === 'No SW') return;
    console.error('浏览器采集助手：' + operation + '失败', error instanceof Error ? error.name : 'Error');
  }
}
