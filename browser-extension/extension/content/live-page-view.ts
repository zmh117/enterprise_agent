import { safeElement } from '../../shared/live-page';
import {
  contextFormat,
  masked,
  maxPageNodes,
  pageText,
  pageRole,
  protectedField,
  type ActionContext,
  type PagePolicy,
  type VisibleNode,
  type VisiblePageEvent,
} from '../../shared/live-page-context';

const controls =
  'button,a[href],input,textarea,select,option,summary,label,[contenteditable]:not([contenteditable=false]),[role=button],[role=link],[role^=menuitem],[role=tab],[role=option],[role=combobox],[role=checkbox],[role=radio],[role=switch],[role=textbox],[role=treeitem]';
const options = '[role=option],[role=listbox]';
const editable =
  'input,textarea,select,[contenteditable]:not([contenteditable=false]),[role=combobox],[role=textbox],[role=checkbox],[role=switch],[role=radio]';
const excluded =
  'head,script,style,noscript,link,template,[hidden],[inert],[aria-hidden=true],[data-mes-agent-host],input[type=hidden]';
const protectedAreas =
  'input[type=password],input[type=file],[autocomplete~=one-time-code],[autocomplete~=current-password],[autocomplete~=new-password],[data-raw-message],[role=log]';

export function recordVisiblePage(
  policy: PagePolicy,
  allowed: () => boolean,
  emit: (event: VisiblePageEvent) => void,
  stopWithGap: () => void,
  signal: AbortSignal,
) {
  // Validate every configured selector before collecting even the first node.
  for (const selector of policy.sensitiveSelectors) document.querySelector(selector);
  const sensitiveSelector = [protectedAreas, ...policy.sensitiveSelectors].join(',');
  const ids = new WeakMap<Node, number>();
  const priorValues = new WeakMap<Element, string>();
  const editors = new WeakSet<Element>();
  const editedText = new WeakSet<Element>();
  let serial = 0;
  let previous = new Map<number, string>();
  let lastTitle = '',
    lastCoverage = '';
  let timer: ReturnType<typeof setTimeout> | undefined;

  function nodeId(node: Node) {
    let key = ids.get(node);
    if (key === undefined) ids.set(node, (key = ++serial));
    return key;
  }
  const clean = (s: string) => pageText(s, policy.maskAllText);
  function labels(el: Element): Element[] {
    const refs = (el.getAttribute('aria-labelledby') ?? '').split(/\s+/).filter(Boolean);
    const result = refs
      .slice(0, 12)
      .map((k) => document.getElementById(k))
      .filter((v): v is HTMLElement => !!v);
    if (
      el instanceof HTMLInputElement ||
      el instanceof HTMLTextAreaElement ||
      el instanceof HTMLSelectElement
    )
      result.push(...Array.from(el.labels ?? []).slice(0, 12));
    return result;
  }
  function fieldName(el: Element) {
    return el.getAttribute('name') || el.id || '';
  }
  function permitsValue(el: Element) {
    return (
      !policy.maskAllText &&
      (policy.allowedInputNames.includes('*') || policy.allowedInputNames.includes(fieldName(el)))
    );
  }
  function picker(el: Element): Element | null {
    const box = el.closest('[role=listbox]');
    if (!box) return el.closest('[role=combobox]');
    const parent = box.closest('[role=combobox]');
    if (parent || !box.id) return parent ?? box;
    const id = CSS.escape(box.id);
    return document.querySelector('[aria-controls~="' + id + '"],[aria-owns~="' + id + '"]') ?? box;
  }
  function protectedControl(el: Element) {
    return (
      [
        'id',
        'name',
        'type',
        'autocomplete',
        'aria-label',
        'placeholder',
        'data-field',
        'data-testid',
        'class',
      ].some((key) => protectedField(el.getAttribute(key) ?? '')) ||
      (el.matches(editable) &&
        labels(el).some(
          (label) => label.closest(sensitiveSelector) || protectedField(label.textContent ?? ''),
        ))
    );
  }
  function columnHeaders(cell: Element): Element[] {
    if (cell instanceof HTMLTableCellElement) {
      const explicit = cell.headers
        .split(/\s+/)
        .filter(Boolean)
        .map((id) => document.getElementById(id))
        .filter((el): el is HTMLElement => !!el);
      if (explicit.length) return explicit;
      return Array.from(cell.closest('table')?.tHead?.rows ?? [])
        .map((row) => row.cells[cell.cellIndex])
        .filter((el): el is HTMLTableCellElement => !!el);
    }
    const col = cell.getAttribute('aria-colindex');
    const grid = cell.closest('[role=grid],[role=table],[role=treegrid]');
    if (!grid) return [];
    const headers = [...grid.querySelectorAll('[role=columnheader]')];
    if (col) return headers.filter((el) => el.getAttribute('aria-colindex') === col);
    const cells = cell.closest('[role=row]')?.querySelectorAll('[role=gridcell],[role=cell]');
    const header = cells && headers[Array.from(cells).indexOf(cell)];
    return header ? [header] : [];
  }
  function restricted(el: Element): boolean {
    if (el.matches(sensitiveSelector)) return true;
    if (protectedControl(el)) return true;
    if (
      el.hasAttribute('contenteditable') &&
      el.getAttribute('contenteditable') !== 'false' &&
      !permitsValue(el)
    )
      return true;
    if (el.matches(options)) {
      const owner = picker(el) ?? el;
      if (
        owner &&
        (owner.closest(sensitiveSelector) || protectedControl(owner) || !permitsValue(owner))
      )
        return true;
    }
    if (
      el.tagName === 'DD' &&
      el.previousElementSibling?.tagName === 'DT' &&
      protectedField(el.previousElementSibling.textContent ?? '')
    )
      return true;
    if (el.matches('td,[role=gridcell],[role=cell]')) {
      const rowHeader = el.parentElement?.querySelector(':scope > th,:scope > [role=rowheader]');
      if (rowHeader && protectedField(rowHeader.textContent ?? '')) return true;
      if (columnHeaders(el).some((h) => protectedField(h.textContent ?? ''))) return true;
    }
    return false;
  }
  function shown(el: Element) {
    if (el.matches(excluded)) return false;
    const style = getComputedStyle(el);
    return (
      style.display !== 'none' &&
      style.visibility !== 'hidden' &&
      style.visibility !== 'collapse' &&
      style.opacity !== '0' &&
      style.contentVisibility !== 'hidden'
    );
  }
  function readable(el: Element): boolean {
    for (let n: Element | null = el; n; n = n.parentElement) {
      if (!shown(n) || restricted(n)) return false;
      if (
        n instanceof HTMLDetailsElement &&
        !n.open &&
        n !== el &&
        !n.querySelector(':scope > summary')?.contains(el)
      )
        return false;
    }
    return el.isConnected;
  }
  // Read individual visible text nodes; flattening a whole row first would expose protected descendants.
  function words(el: Element): string {
    if (!readable(el)) return '';
    const chunks: string[] = [];
    let chars = 0,
      visited = 0;
    function walk(n: Node) {
      if (++visited > 512 || chars >= 2048) return;
      if (n instanceof Element) {
        if (!shown(n) || restricted(n) || n.matches(editable + ',iframe,canvas')) return;
        if (n instanceof HTMLDetailsElement && !n.open) {
          const summary = n.querySelector(':scope > summary');
          if (summary) walk(summary);
          return;
        }
      }
      if (n.nodeType === Node.TEXT_NODE) {
        const s = clean((n.nodeValue ?? '').trim());
        if (s) {
          chunks.push(s);
          chars += s.length;
        }
      } else
        for (const child of n.childNodes) {
          walk(child);
          if (visited > 512 || chars >= 2048) break;
        }
    }
    walk(el);
    return clean(chunks.join(' ') + (visited > 512 || chars >= 2048 ? '…' : ''));
  }
  function title() {
    const titleNode = document.querySelector('head > title');
    return titleNode && !titleNode.closest(sensitiveSelector) && !restricted(titleNode)
      ? clean(document.title)
      : '';
  }
  function controlValue(el: Element): string | undefined {
    if (!el.matches(editable)) return undefined;
    if (!permitsValue(el)) return masked;
    if (el instanceof HTMLInputElement) {
      if (el.type === 'checkbox' || el.type === 'radio') return String(el.checked);
      return clean(el.value);
    }
    if (
      el instanceof HTMLSelectElement &&
      [...el.selectedOptions].some((o) => restricted(o) || o.closest(sensitiveSelector))
    )
      return masked;
    if (el instanceof HTMLTextAreaElement || el instanceof HTMLSelectElement)
      return clean(el.value);
    if (el instanceof HTMLElement && el.isContentEditable) {
      // Child nodes of rich editors may contain nested protected or hidden regions.
      const chunks = Array.from(el.childNodes).map((n) =>
        n.nodeType === Node.TEXT_NODE
          ? clean(n.nodeValue ?? '')
          : n instanceof Element
            ? words(n)
            : '',
      );
      return clean(chunks.join(''));
    }
    const aria = el.getAttribute('aria-valuetext') ?? el.getAttribute('aria-checked');
    return aria === null ? undefined : clean(aria);
  }
  function selection(el: Element) {
    if (!(el instanceof HTMLSelectElement)) return undefined;
    if (!permitsValue(el)) return masked;
    return clean(
      Array.from(el.selectedOptions, (o) =>
        restricted(o) || o.closest(sensitiveSelector) ? masked : clean(o.label),
      ).join(', '),
    );
  }
  function view() {
    let visited = 0,
      chars = 0,
      limited = false,
      embedded = false;
    const nodes: VisibleNode[] = [];
    function visit(el: Element, parent: number, order: number, depth: number) {
      if (++visited > maxPageNodes || chars > 500000 || depth > 128) {
        limited = true;
        return;
      }
      if (!shown(el) || restricted(el)) return;
      const id = nodeId(el);
      const node: VisibleNode = { id, parent, order, element: safeElement(el.localName) };
      const role = pageRole(el.getAttribute('role'));
      if (role) node.role = role;
      nodes.push(node);
      if (el.matches('iframe,canvas,object,embed') || el.shadowRoot) embedded = true;
      if (el.matches('iframe,canvas,object,embed')) return;
      const current = controlValue(el);
      if (current !== undefined) {
        node.field_name = clean(fieldName(el));
        node.value = current;
        node.selection = selection(el);
        if (current.endsWith('…') || node.selection?.endsWith('…')) limited = true;
        chars += current.length + (node.selection?.length ?? 0);
        if (!editors.has(el)) priorValues.set(el, current);
      }
      if (el.matches(editable) && !permitsValue(el)) return;
      if (el.matches('input,select,textarea,[contenteditable]:not([contenteditable=false])'))
        return;
      let pos = 0;
      for (const child of el.childNodes) {
        if (visited >= maxPageNodes || chars >= 500000) {
          limited = true;
          break;
        }
        if (child instanceof Element) {
          if (
            el instanceof HTMLDetailsElement &&
            !el.open &&
            child !== el.querySelector(':scope > summary')
          )
            continue;
          visit(child, id, pos++, depth + 1);
        } else if (child.nodeType === Node.TEXT_NODE && child.nodeValue?.trim()) {
          const text = clean(child.nodeValue.trim());
          nodes.push({ id: nodeId(child), parent: id, order: pos++, element: 'text', text });
          visited++;
          chars += text.length;
          if (text.endsWith('…')) limited = true;
        }
      }
    }
    if (document.body && readable(document.body)) visit(document.body, 0, 0, 0);
    const flags = ['rendered_dom'];
    if (embedded) flags.push('embedded_content_omitted');
    if (limited) flags.push('budget_limited');
    return { nodes, coverage: flags.join(',') };
  }
  function update(baseline = false) {
    if (!allowed() || signal.aborted) return;
    try {
      const current = view();
      const next = new Map<number, string>();
      const changed = current.nodes.filter((node) => {
        const json = JSON.stringify(node);
        next.set(node.id, json);
        return baseline || previous.get(node.id) !== json;
      });
      const removed = baseline ? [] : [...previous.keys()].filter((id) => !next.has(id));
      const pageTitle = title();
      if (
        baseline ||
        changed.length ||
        removed.length ||
        pageTitle !== lastTitle ||
        lastCoverage !== current.coverage
      ) {
        emit({
          kind: baseline ? 'baseline' : 'mutation',
          page_format: contextFormat,
          page_title: pageTitle,
          page_coverage: current.coverage,
          nodes: changed,
          removed,
        });
      }
      previous = next;
      lastTitle = pageTitle;
      lastCoverage = current.coverage;
    } catch {
      stopWithGap();
    }
  }
  function schedule() {
    if (timer !== undefined || signal.aborted) return;
    timer = setTimeout(() => {
      timer = undefined;
      update();
    }, 100);
  }
  function guarded(fn: (e: Event, el: Element) => void) {
    return (e: Event) => {
      if (!e.isTrusted || !allowed() || signal.aborted) return;
      const el = e.composedPath().find((n): n is Element => n instanceof Element);
      if (!el || el.getRootNode() !== document || el.closest('[data-mes-agent-host]')) return;
      try {
        fn(e, el);
      } catch {
        stopWithGap();
      }
    };
  }
  function action(e: Event, raw: Element) {
    const el =
      (e instanceof SubmitEvent && e.submitter) ||
      (e.type === 'click' ? raw.closest(controls) : null) ||
      raw;
    if (!readable(raw) || !readable(el)) return;
    // Flush a pending visibility or DOM change before referring to its target's node ID.
    if (timer !== undefined) {
      clearTimeout(timer);
      timer = undefined;
      update();
    }
    if (signal.aborted) return;
    const ctx: ActionContext = {};
    const cell = el.closest('td,th,[role=gridcell],[role=cell]');
    const row = el.closest('tr,[role=row]');
    const inputCaption =
      el instanceof HTMLInputElement && ['button', 'submit', 'reset'].includes(el.type)
        ? el.value
        : '';
    const field =
      labels(el).map(words).filter(Boolean).join(' ') || el.getAttribute('aria-label') || '';
    ctx.target_text = clean(
      field ||
        words(el) ||
        inputCaption ||
        el.getAttribute('title') ||
        el.getAttribute('placeholder') ||
        '',
    );
    if (row) {
      ctx.row_text = words(row);
      const position =
        row.getAttribute('aria-rowindex') ||
        (row instanceof HTMLTableRowElement ? String(row.sectionRowIndex + 1) : '');
      if (/^[1-9]\d*$/.test(position)) ctx.row_position = position;
    }
    const option = el.closest('[role=option]');
    const owner = option && picker(option);
    if (owner && readable(owner)) {
      ctx.field_name = clean(fieldName(owner));
      ctx.field_label = clean(
        labels(owner).map(words).filter(Boolean).join(' ') ||
          owner.getAttribute('aria-label') ||
          fieldName(owner),
      );
      ctx.selection = permitsValue(owner) ? words(option!) : masked;
    }
    if (el.matches(editable)) {
      const heading = cell ? columnHeaders(cell).map(words).filter(Boolean).join(' ') : '';
      ctx.field_label = clean(field || heading || el.getAttribute('placeholder') || fieldName(el));
      ctx.field_name = clean(fieldName(el));
      ctx.value = controlValue(el);
      ctx.selection = selection(el);
      if (e.type === 'change' && priorValues.has(el)) ctx.before_value = priorValues.get(el);
      if (e.type === 'change' && ctx.value !== undefined) priorValues.set(el, ctx.value);
    }
    emit({
      kind: 'action',
      page_format: contextFormat,
      page_title: title(),
      page_coverage: lastCoverage,
      action: e.type as 'click' | 'change' | 'submit',
      element: safeElement(el.localName),
      node_id: nodeId(el),
      ...ctx,
    });
    schedule();
  }
  for (const name of ['click', 'change', 'submit'])
    document.addEventListener(name, guarded(action), { capture: true, signal });
  document.addEventListener(
    'focusin',
    guarded((_e, el) => {
      if (!readable(el)) return;
      const value = controlValue(el);
      if (value !== undefined) {
        editors.add(el);
        priorValues.set(el, value);
      }
    }),
    { capture: true, signal },
  );
  document.addEventListener(
    'input',
    guarded((_e, el) => {
      if (el instanceof HTMLElement && el.isContentEditable) editedText.add(el);
    }),
    { capture: true, signal },
  );
  document.addEventListener(
    'focusout',
    guarded((_e, el) => {
      if (
        el instanceof HTMLElement &&
        el.isContentEditable &&
        editedText.has(el) &&
        readable(el) &&
        controlValue(el) !== priorValues.get(el)
      ) {
        action(new Event('change'), el);
      }
      editedText.delete(el);
      editors.delete(el);
      schedule();
    }),
    { capture: true, signal },
  );
  const observer = new MutationObserver((changes) => {
    if (
      changes.some(
        (c) =>
          !(c.target instanceof Element ? c.target : c.target.parentElement)?.closest(
            '[data-mes-agent-host]',
          ),
      )
    )
      schedule();
  });
  observer.observe(document, {
    subtree: true,
    childList: true,
    characterData: true,
    attributes: true,
  });
  window.addEventListener('resize', schedule, { signal });
  document.addEventListener('load', schedule, { signal, capture: true });
  const checkout = setInterval(() => update(true), 60_000);
  signal.addEventListener(
    'abort',
    () => {
      observer.disconnect();
      clearTimeout(timer);
      clearInterval(checkout);
    },
    { once: true },
  );
  update(true);
}
