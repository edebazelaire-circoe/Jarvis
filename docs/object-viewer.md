# Object viewer

The Control Center object viewer is a transient, full-viewport **in-app**
modal. Browser fullscreen remains owned by `JarvisFullscreen`; the viewer
never calls that API or writes scene geometry. The Board is inert behind the
viewer and returns with the same selection and geometry when it closes.
Scene selection/open bindings are owned by the integration Slice, not this
module. Source: `jarvis/runtime/control_center_object_viewer.js`.

## Scene bindings

`control_center_scene_viewer.js` composes this shell with existing Artifact
metadata, scene markdown/item helpers, sandboxed `JarvisPrefabHost` preview and
the public agent reader. The scene page loads these modules directly; there is
no production fixture adapter. Enter, double-click and **Ouvrir / Voir** use the
same dispatch. An agent/job anchor opens its detail alone. A document/artifact
anchor opens compatible selected documents, with an accessible count of skipped
members. Single mouse click selects; right-click or the keyboard context key
opens actions. Closing restores focus to the current anchor when it exists and
preserves scene selection.

Registry references are checked against returned Artifact identity. Images use
the canonical payload URL and native viewer zoom/pan. Registry text is the
existing extracted-text preview (16,000 characters maximum); truncation is stated.
Plain summaries/items use existing safe markdown blocks. PDF uses the shell's
explicit source-link fallback. Prefab preview binds focused-frame Escape to
viewer close; canonical host pause may reconstruct the iframe on return.

Metadata resolution has at most four readers; each document failure becomes a
readable fallback. Shell cancellation/deadline/retry applies to the initial
loader. Agent artifact navigation has a ten-second deadline, pushes a real shell
history entry, and returns through **Retour** to retained native agent DOM.
No viewer layout or navigation writes scene geometry. Async feedback belongs
inside the native top-layer dialog. Presentation fullscreen or another modal
must be closed first; the refusal is explicit.

## API

```js
const viewer = JarvisObjectViewer.create({
  document, window,
  log: (level, event, data) => { /* existing client journal */ },
  renderEntry: (entry, slot, context) => { /* optional canonical provider */ }
});
viewer.openObjects(entries, {
  title: 'Comparer les documents', layout: 'auto',
  returnFocus: anchorElement, notice: 'Un objet incompatible a été écarté.',
  onClose: () => {}, push: false
});
viewer.openCustom({id, title, mount: (slot, context) => controller}, {push: true});
viewer.setLayout('custom', {rows: 3, cols: 8});
viewer.back(); viewer.close(); viewer.isOpen(); viewer.snapshot(); viewer.destroy();
```

`openObjects`, `openCustom` and `setLayout` return `{ok:true}` or a bounded
`{ok:false,code,message}`. A failure is visible inside the dialog and logged;
even an invalid first opening provides a useful error and a Close action.
The first opening captures focus and `onClose`; closing restores focus only
if the anchor remains connected. The native dialog owns Tab containment,
background inertness and Escape from its own document. There is no browser
Fullscreen API state or durable viewer storage. A native `dialog.close()`
also performs cleanup through its close event. `destroy()` is final.

`entries` is a nonempty array of at most 512 unique IDs. Each entry has
`{id,title,kind,...}`; titles are bounded to160 characters. Supported kinds:

| Kind | Data and behavior |
| --- | --- |
| `image` | `artifactId`, optional `alt`; URL is derived only as `/api/artifacts/{encoded-id}/payload`. Arbitrary supplied URLs are ignored. Fit, zoom1–8×, wheel, pointer pan, keyboard +/−/0 and arrow pan; no source writes. |
| `text` | `text` rendered by `textContent`, bounded to500,000 characters, native scrolling; an empty document is explicit. No raw HTML or new markdown parser. |
| `provider` | `mount(slot,context)` or injected `renderEntry`; use existing document/markdown or `JarvisPrefabHost` infrastructure. The viewer does not build frames. |
| `pdf` | Same canonical Artifact URL; `mount`/`renderEntry` may supply an existing safe PDF provider. Without one, explicit `provider_missing` fallback and canonical Open PDF link in a new `noopener noreferrer` tab. No PDF renderer exists in this Slice. |
| `unsupported` | Explicit `unsupported_content` fallback, optional bounded `message`; canonical Artifact open link when an ID is available. |

PDF preview availability is conditional. This task does not introduce a
parallel document store, PDF engine, unsafe `object`/`embed`, or unsandboxed
HTML frame. S05 binds the available real content providers.

## Providers and history

`mount(slot,context)` receives `{signal,ready,fail,viewer,document,window,log}`.
It may return a controller (or a Promise of one), or a dispose function:

```js
return {pending: true, dispose() {}, pause() {}, resume() {}};
```

By default a returned controller/fulfilled Promise marks the content ready.
For asynchronous providers, `pending:true` requires `context.ready()` or
`context.fail(error)`. A visible loading state has motion, document name,
elapsed seconds, a20-second deadline, Retry and the shell's Close action.
Failures abort the provider signal, dispose its work and remain actionable.
Late completion cannot repopulate a closed/retried slot. Media failures and
timeouts are logged with IDs, bounded error and content kind, never contents.
Use the injected log adapter to connect the existing client journal.

`push:true` keeps the previous screen mounted (max8 screens); Back disposes
the current one and restores the exact previous DOM. Layout changes only
reconfigure the grid and hide/show tiles, preserving native document scroll,
image zoom/pan and mounted provider identity. Provider `pause`/`resume` runs
when content becomes effectively hidden/visible, for history **and** paging.
Slots mount lazily on viewport intersection; already mounted slots are reused.

Provider internals retain their canonical lifecycle: in particular existing
`JarvisPrefabHost.pause()` unloads its iframe and `resume()` recreates it under
the LRU policy. The shell does not promise to preserve iframe-internal state
across that teardown. Use native safe text/markdown for ordinary documents
where available; native slot DOM and scroll survive. No second suspension
engine is introduced.

For an agent detail, S05 calls `openCustom`; its renderer mounts public detail
inside the supplied slot. Artifact buttons can call
`viewer.openObjects(entries,{push:true})`, then the shell's Back returns to
the detail without reconstructing its native DOM. Stop/Ask transports and live
status remain outside the shell and use their canonical owners.

## Layouts and accessibility

`single`, `horizontal`, `vertical`, `quad`, `row`, `column`, `auto`, `custom`,
`largeLeft`, `largeTop`. Single/pairs/quadrants/asymmetric pairs paginate with
explicit document range and Previous/Next; no entry disappears silently.
Row/column/auto show the full set in a scrollable comparison area. Custom
supports1–64 rows/columns, at most512 cells, a6×6 graphical picker with arrow
navigation and numeric fallback for grids such as3×8. Initial custom grids
use `openObjects(entries,{layout:'custom',grid:{rows:3,cols:8}})`.

The shell inherits Jarvis theme tokens, dark content-led surfaces and native
controls. Layout controls wrap at small widths; image controls remain usable
in small cells. Reduced motion disables nonessential animation. Errors and
skipped-entry notices are inside the modal; callers should close other modal
Settings/Studio/menu flows first. Ordinary page toasts are behind the native
top layer, so they cannot be the only feedback for viewer actions.

Escape from a canonical prefab requires its host's optional
`onEscape: () => viewer.close()` callback. The canonical shim forwards only
trusted plain Escape, and Host admits only the focused current live ready
frame, with opaque-origin/source/staged/teardown/rate guards. Hosts without
this callback keep existing behavior. This is a bounded local UI bridge,
not an arbitrary keyboard/command channel; see [prefabs.md](prefabs.md).

## Evidence

`tests/unit/test_object_viewer_js.py` checks pure layouts and resource boundaries.
`tests/unit/test_object_viewer_browser.py` exercises native Chromium with real
clicks, keyboard, wheel and pointer pan:1/2/4/5/24 entries, both themes,
layouts/custom grid, document scrolling, safe text, focus/inert/restore,
history/lifecycle, canonical PrefabHost, reduced motion and640×400 viewport
(equivalent CSS space at200% of1280×800). `tests/unit/test_prefab_escape_bridge.py`
checks exact bridge shape, trusted/plain key filtering, source/focus/live/stale
and rate guards, teardown, no-callback behavior and visible/logged failure.
Scene/Core integration and real agent execution are S05/S06 responsibilities.
