import assert from 'node:assert/strict';

// Hold the HTTP receipt after admission so the first stop click precedes the Job ID.
export async function checkStopReply(view, page, requests) {
  const pattern = '**/api/browser-extension/applications/*/messages';
  let release;
  const held = new Promise(resolve => { release = resolve; });
  const handler = async route => {
    const response = await route.fetch();
    await held;
    await route.fulfill({response});
  };
  const before = requests.length;
  const draft = view.locator('#agent-question');
  const send = view.getByRole('button', {name:'发送', exact:true});
  await page.route(pattern, handler);
  try {
    await draft.fill('合成停止测试');
    await send.click();
    await draft.fill('下一条草稿');
    await draft.press('Enter');
    await view.getByRole('button', {name:'停止回答', exact:true}).click();
    release();
    await view.getByText('已取消', {exact:true}).last().waitFor();
    assert.equal(await draft.inputValue(), '下一条草稿');
    await send.waitFor();
    assert.ok(await send.isEnabled());
    const posts = requests.slice(before).filter(([method]) => method === 'POST');
    assert.equal(posts.filter(([,url]) => url.endsWith('/messages')).length, 1);
    assert.equal(posts.filter(([,url,code]) => url.endsWith('/cancel') && code === 200).length, 1);
  } finally {
    release();
    await page.unroute(pattern, handler);
  }
}
