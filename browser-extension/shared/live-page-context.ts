import type { Policy } from './contracts';
import { protectedName, unsafeText } from './business-json';

export type PagePolicy = Pick<Policy, 'maskAllText' | 'sensitiveSelectors' | 'allowedInputNames'>;
export const contextFormat = 'visible_page_v1';
export const maxPageNodes = 12000;
export const maxPageText = 512;
export const masked = '[REDACTED]';

export function protectedField(name: string) {
  return (
    protectedName(name) ||
    /验证码|口令|密钥|密碼|原始消息|原始报文|聊天内容|one.time.code|\botp\b|verification.?code|raw[-_ ]?(?:body|message)|chat[-_ ]?(?:log|message|history|input)|message[-_ ]?(?:body|content)|^message$/i.test(
      name,
    )
  );
}

export function pageText(value: string, mask: boolean) {
  if (
    mask ||
    unsafeText(value) ||
    /^\s*(?:\{|\[\s*(?:[{"\[]|-?\d|true|false|null)|<!(?:doctype|--)|<\/?[a-z][\w:-]*[\s>])/i.test(
      value,
    ) ||
    /(?:password|passwd|token|secret|cookie|api.?key|authorization|密码|密钥|验证码)\s*["']?\s*[:=：]/i.test(
      value,
    )
  )
    return masked;
  return value.length <= maxPageText ? value : value.slice(0, maxPageText - 1) + '…';
}

export const contextFields = [
  'target_text',
  'field_label',
  'row_text',
  'row_position',
  'field_name',
  'value',
  'before_value',
  'selection',
] as const;
export type ActionContext = Partial<Record<(typeof contextFields)[number], string>>;
export interface VisibleNode {
  id: number;
  parent: number;
  order: number;
  element: string;
  role?: string;
  text?: string;
  field_name?: string;
  value?: string;
  selection?: string;
}
type View = { page_format: typeof contextFormat; page_title: string; page_coverage: string };
export type VisiblePageEvent =
  | (View & { kind: 'baseline' | 'mutation'; nodes: VisibleNode[]; removed: number[] })
  | (View &
      ActionContext & {
        kind: 'action';
        action: 'click' | 'change' | 'submit';
        element: string;
        node_id: number;
      });

const roles = new Set(
  'alert alertdialog application article banner button cell checkbox columnheader combobox complementary contentinfo dialog document feed form grid gridcell group heading img link list listbox listitem main menu menubar menuitem menuitemcheckbox menuitemradio navigation option presentation progressbar radio radiogroup region row rowgroup rowheader search searchbox separator slider spinbutton status switch tab table tablist tabpanel textbox toolbar tooltip tree treegrid treeitem'.split(
    ' ',
  ),
);
export const pageRole = (value: unknown) =>
  typeof value === 'string' && roles.has(value) ? value : undefined;
const coverageFlags = new Set(['rendered_dom', 'embedded_content_omitted', 'budget_limited']);
const safeWord = (v: unknown) => typeof v === 'string' && /^[a-z][a-z0-9-]{0,31}$/.test(v);
const id = (v: unknown): v is number => Number.isSafeInteger(v) && Number(v) >= 0;

// The document-side reader enforces DOM visibility and sensitive ancestors. The worker
// independently rebuilds the wire shape and reapplies the run's value policy before storage.
export function projectVisibleEvent(input: VisiblePageEvent, policy: PagePolicy): VisiblePageEvent {
  const text = (v: unknown) => {
    if (typeof v !== 'string') throw new Error('invalid_page_text');
    return pageText(v, policy.maskAllText);
  };
  const value = (v: unknown, name: unknown) => {
    if (typeof v !== 'string') throw new Error('invalid_page_value');
    if (
      typeof name !== 'string' ||
      protectedField(name) ||
      !(policy.allowedInputNames.includes('*') || policy.allowedInputNames.includes(name))
    )
      return masked;
    return text(v);
  };
  const view: View = {
    page_format: contextFormat,
    page_title: text(input.page_title),
    page_coverage: String(input.page_coverage)
      .split(',')
      .filter((k) => coverageFlags.has(k))
      .join(','),
  };
  if (input.kind === 'action') {
    if (
      !['click', 'change', 'submit'].includes(input.action) ||
      !id(input.node_id) ||
      !safeWord(input.element)
    )
      throw new Error('invalid_page_action');
    const result: VisiblePageEvent = {
      kind: 'action',
      ...view,
      action: input.action,
      element: input.element,
      node_id: input.node_id,
    };
    const sensitive = [input.field_name, input.field_label].some(
      (v) => typeof v === 'string' && protectedField(v),
    );
    for (const k of contextFields) {
      if (input[k] !== undefined)
        result[k] = sensitive
          ? masked
          : ['value', 'before_value', 'selection'].includes(k)
            ? value(input[k], input.field_name)
            : text(input[k]);
    }
    return result;
  }
  if (
    !['baseline', 'mutation'].includes(input.kind) ||
    !Array.isArray(input.nodes) ||
    !Array.isArray(input.removed) ||
    input.nodes.length > maxPageNodes ||
    input.removed.length > maxPageNodes ||
    !input.removed.every(id)
  )
    throw new Error('invalid_page_snapshot');
  const nodes = input.nodes.map((n) => {
    if (!n || !id(n.id) || !id(n.parent) || !id(n.order) || !safeWord(n.element))
      throw new Error('invalid_page_node');
    const node: VisibleNode = { id: n.id, parent: n.parent, order: n.order, element: n.element };
    const role = pageRole(n.role);
    if (role) node.role = role;
    if (n.text !== undefined) node.text = text(n.text);
    if (n.field_name !== undefined) node.field_name = text(n.field_name);
    if (n.value !== undefined) node.value = value(n.value, n.field_name);
    if (n.selection !== undefined) node.selection = value(n.selection, n.field_name);
    return node;
  });
  return { kind: input.kind, ...view, nodes, removed: [...input.removed] };
}
