import {
  bindingForPage,
  type WorkshopBinding,
  type PageRule,
  ruleForPage,
  sameRule,
} from './workshop';

export interface PageSource {
  tab_id: string;
  document_id: string;
  binding_id: string;
  revision: number;
}
export interface QuestionPage {
  binding_id: string;
  revision: number;
  document_id: string;
  recording_id: string | null;
  tab_id: string | null;
  asked_ms: number;
  timezone: string;
}
export interface LiveDocument {
  documentId: string;
  binding?: WorkshopBinding;
  state: 'unbound' | 'baseline' | 'ready' | 'paused';
}

export function matchesPage(url: string, rule: PageRule) {
  try {
    return sameRule(rule, ruleForPage(url, Object.keys(rule.query)));
  } catch {
    return false;
  }
}

// A scope change in a living document permanently fences this recorder, including back navigation.
export function observePage(
  previous: LiveDocument | undefined,
  documentId: string,
  url: string,
  rules: WorkshopBinding[],
): LiveDocument {
  const binding = bindingForPage(url, rules);
  if (!previous || previous.documentId !== documentId)
    return { documentId, binding, state: binding ? 'baseline' : 'unbound' };
  if (previous.state === 'paused') return previous;
  if (previous.binding?.id !== binding?.id || previous.binding?.revision !== binding?.revision)
    return { ...previous, state: 'paused' };
  return previous;
}

export function sourceOf(tabId: string, doc: LiveDocument | undefined): PageSource | undefined {
  if (!doc?.binding || (doc.state !== 'baseline' && doc.state !== 'ready')) return;
  return {
    tab_id: tabId,
    document_id: doc.documentId,
    binding_id: doc.binding.id,
    revision: doc.binding.revision,
  };
}

const elements = new Set(
  'html head body main section article nav header footer form fieldset legend div span p label input textarea select option button table thead tbody tfoot tr th td ul ol li a img svg path h1 h2 h3 h4 details summary dialog template br'.split(
    ' ',
  ),
);
export function safeElement(name: unknown) {
  return typeof name === 'string' && elements.has(name) ? name : 'div';
}

interface StructureNode {
  id: number;
  type: number;
  tagName?: string;
  textContent?: string;
  attributes?: Record<string, never>;
  childNodes?: StructureNode[];
  name?: string;
  publicId?: string;
  systemId?: string;
}
// Rebuild rrweb's node tree from a closed schema. Attributes, script, CSS and arbitrary text never cross the content boundary.
function structuralNode(raw: unknown, maxNodes = 100_000): StructureNode {
  let count = 0;
  function project(value: unknown, depth: number): StructureNode {
    const n = value as Partial<StructureNode> | null;
    if (
      ++count > maxNodes ||
      depth > 128 ||
      !n ||
      !Number.isSafeInteger(n.id) ||
      !Number.isInteger(n.type) ||
      n.type! < 0 ||
      n.type! > 5
    )
      throw new Error('invalid_baseline');
    const node: StructureNode = { id: n.id!, type: n.type! };
    if (node.type === 0 || node.type === 2) {
      if (!Array.isArray(n.childNodes)) throw new Error('invalid_baseline');
      if (node.type === 2) {
        node.tagName = safeElement(n.tagName);
        node.attributes = {};
      }
      node.childNodes = n.childNodes.map((child) => project(child, depth + 1));
    } else if (node.type === 1) {
      Object.assign(node, { name: 'html', publicId: '', systemId: '' });
    } else node.textContent = '';
    return node;
  }
  return project(raw, 0);
}
export function structuralBaseline(raw: unknown) {
  const tree = structuralNode(raw);
  if (tree.type !== 0) throw new Error('invalid_baseline');
  return tree;
}

export const actions = ['click', 'change', 'submit'] as const;
export type PageEvidence =
  | { kind: 'baseline'; node: StructureNode }
  | { kind: 'mutation'; adds: NodeAddition[]; removes: NodeRemoval[] }
  | { kind: 'action'; action: (typeof actions)[number]; element: string; node_id: number };

interface NodeRemoval {
  id: number;
  parentId: number;
}
interface NodeAddition {
  parentId: number;
  nextId: number | null;
  node: StructureNode;
}
function validId(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}
export function structuralMutation(data: unknown): Extract<PageEvidence, { kind: 'mutation' }> {
  const input = data as { adds: NodeAddition[]; removes: NodeRemoval[] };
  if (
    !input ||
    !Array.isArray(input.adds) ||
    !Array.isArray(input.removes) ||
    input.adds.length + input.removes.length > 50_000
  )
    throw new Error('invalid_mutation');
  return {
    kind: 'mutation',
    adds: input.adds.map((a) => {
      if (!validId(a.parentId) || (a.nextId !== null && !validId(a.nextId)))
        throw new Error('invalid_mutation');
      return { parentId: a.parentId, nextId: a.nextId, node: structuralNode(a.node) };
    }),
    removes: input.removes.map((r) => {
      if (!validId(r.id) || !validId(r.parentId)) throw new Error('invalid_mutation');
      return { id: r.id, parentId: r.parentId };
    }),
  };
}

export function projectPageEvent(input: unknown): PageEvidence {
  const item = input as Partial<{
    kind: string;
    node: unknown;
    action: (typeof actions)[number];
    element: string;
    node_id: number;
  }>;
  if (item?.kind === 'baseline') return { kind: 'baseline', node: structuralBaseline(item.node) };
  if (item?.kind === 'mutation') return structuralMutation(item);
  if (
    item?.kind === 'action' &&
    actions.includes(item.action!) &&
    Number.isSafeInteger(item.node_id)
  )
    return {
      kind: 'action',
      action: item.action!,
      element: safeElement(item.element),
      node_id: item.node_id!,
    };
  throw new Error('invalid_page_event');
}
