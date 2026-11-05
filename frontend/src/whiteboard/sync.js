/**
 * Realtime sync for whiteboard state: the op vocabulary shared with the server,
 * a client-side diff that turns one state into another, and a copy-on-write
 * applier. State is `{ layers, background }`. Layers and elements are never
 * mutated, so `===` means "unchanged".
 *
 * An op is `{ op, ...fields }`, where `op` is the op name from the protocol table.
 */

/** Layer fields that `layer.set` may change. */
const LAYER_FLAGS = ['name', 'visible', 'locked']

/** Index of the item with `id` in `list`, or -1. */
function indexOf(list, id) {
  return list.findIndex(item => item.id === id)
}

/** Layer index and element index of the element `id`, or null. */
function locate(layers, id) {
  for (let li = 0; li < layers.length; li++) {
    const ei = indexOf(layers[li].elements, id)
    if (ei !== -1) return { li, ei }
  }
  return null
}

/** Copy of `list` with `item` inserted at `index`, clamped to [0, length]. */
function insertAt(list, index, item) {
  const out = list.slice()
  out.splice(Math.min(Math.max(index, 0), out.length), 0, item)
  return out
}

/** Copy of `layers` with the layer at `li` replaced by `layer`. */
function replaceLayer(layers, li, layer) {
  return layers.map((l, i) => (i === li ? layer : l))
}

/** `layers` with the element `id` removed from whichever layer holds it. */
function detach(layers, id) {
  return layers.map(layer => {
    if (indexOf(layer.elements, id) === -1) return layer
    return { ...layer, elements: layer.elements.filter(el => el.id !== id) }
  })
}

/** Items listed in `ids` first, in that order, then the rest in their current order. */
function reorder(items, ids) {
  const pending = new Map(items.map(item => [item.id, item]))
  const out = []
  for (const id of ids) {
    if (pending.has(id)) {
      out.push(pending.get(id))
      pending.delete(id)
    }
  }
  for (const item of items) {
    if (pending.has(item.id)) out.push(item)
  }
  return out
}

/** True when the items present in both lists appear in the same relative order. */
function sameRelativeOrder(a, b) {
  const aIds = new Set(a.map(item => item.id))
  const bIds = new Set(b.map(item => item.id))
  const x = a.map(item => item.id).filter(id => bIds.has(id))
  const y = b.map(item => item.id).filter(id => aIds.has(id))
  return x.length === y.length && x.every((id, i) => id === y[i])
}

function addElement(layers, { layer, index, el }) {
  const li = indexOf(layers, layer)
  if (li === -1) return layers
  const moved = detach(layers, el.id)
  return replaceLayer(moved, li, { ...moved[li], elements: insertAt(moved[li].elements, index, el) })
}

function setElement(layers, { id, set = {}, unset = [] }) {
  const pos = locate(layers, id)
  if (!pos) return layers
  const el = { ...layers[pos.li].elements[pos.ei], ...set }
  for (const key of unset) delete el[key]
  const elements = layers[pos.li].elements.slice()
  elements[pos.ei] = el
  return replaceLayer(layers, pos.li, { ...layers[pos.li], elements })
}

function orderElements(layers, { layer, ids }) {
  const li = indexOf(layers, layer)
  if (li === -1) return layers
  return replaceLayer(layers, li, { ...layers[li], elements: reorder(layers[li].elements, ids) })
}

function addLayer(layers, { index, layer }) {
  let rest = layers.filter(l => l.id !== layer.id)
  for (const el of layer.elements) rest = detach(rest, el.id)
  return insertAt(rest, index, layer)
}

function setLayer(layers, { id, set }) {
  const li = indexOf(layers, id)
  if (li === -1) return layers
  const layer = { ...layers[li] }
  for (const key of LAYER_FLAGS) {
    if (Object.hasOwn(set, key)) layer[key] = set[key]
  }
  return replaceLayer(layers, li, layer)
}

function deleteLayer(layers, id) {
  const li = indexOf(layers, id)
  if (li === -1 || layers.length === 1) return layers
  return layers.filter((_, i) => i !== li)
}

/**
 * Apply ops to `state` and return a new `{ layers, background }`. The input is
 * never mutated, and layers or elements the ops do not touch keep their identity.
 * Ops that reference a missing target are skipped; unknown ops and `title` are ignored.
 */
export function applyOps(state, ops) {
  let { layers, background } = state
  for (const op of ops) {
    switch (op.op) {
      case 'el.add':
        layers = addElement(layers, op)
        break
      case 'el.set':
        layers = setElement(layers, op)
        break
      case 'el.del':
        layers = detach(layers, op.id)
        break
      case 'el.order':
        layers = orderElements(layers, op)
        break
      case 'layer.add':
        layers = addLayer(layers, op)
        break
      case 'layer.set':
        layers = setLayer(layers, op)
        break
      case 'layer.del':
        layers = deleteLayer(layers, op.id)
        break
      case 'layer.order':
        layers = reorder(layers, op.ids)
        break
      case 'doc.set':
        if (Object.hasOwn(op.set, 'background')) background = op.set.background
        break
    }
  }
  return { layers, background }
}

/**
 * Ops for one layer present in both states and not `===`. Appends to `ops`.
 * `nextElIds` holds every element id in `next`: an element that only moved to
 * another layer is left to that layer's el.add, since el.del would remove it there.
 */
function diffLayer(before, after, nextElIds, ops) {
  const flags = {}
  for (const key of LAYER_FLAGS) {
    if (before[key] !== after[key]) flags[key] = after[key]
  }
  if (Object.keys(flags).length) ops.push({ op: 'layer.set', id: after.id, set: flags })

  const prevEls = new Map(before.elements.map(el => [el.id, el]))
  for (const el of before.elements) {
    if (!nextElIds.has(el.id)) ops.push({ op: 'el.del', id: el.id })
  }
  after.elements.forEach((el, index) => {
    if (!prevEls.has(el.id)) ops.push({ op: 'el.add', layer: after.id, index, el })
  })
  for (const el of after.elements) {
    const old = prevEls.get(el.id)
    if (!old || old === el) continue
    const set = {}
    const unset = []
    for (const key of Object.keys(el)) {
      if (!Object.hasOwn(old, key) || old[key] !== el[key]) set[key] = el[key]
    }
    for (const key of Object.keys(old)) {
      if (!Object.hasOwn(el, key)) unset.push(key)
    }
    if (!Object.keys(set).length && !unset.length) continue
    ops.push(unset.length ? { op: 'el.set', id: el.id, set, unset } : { op: 'el.set', id: el.id, set })
  }
  if (!sameRelativeOrder(before.elements, after.elements)) {
    ops.push({ op: 'el.order', layer: after.id, ids: after.elements.map(el => el.id) })
  }
}

/**
 * Ops that turn `prev` into `next`, both `{ layers, background }`. Layers and
 * elements are matched by id, and a changed one is one that is `!==` between the
 * states. `applyOps(prev, diffState(prev, next))` deep-equals `next`.
 */
export function diffState(prev, next) {
  const ops = []
  const prevById = new Map(prev.layers.map(layer => [layer.id, layer]))
  const nextById = new Map(next.layers.map(layer => [layer.id, layer]))
  const gone = prev.layers.filter(layer => !nextById.has(layer.id))
  const added = next.layers
    .map((layer, index) => ({ layer, index }))
    .filter(({ layer }) => !prevById.has(layer.id))

  // The server skips layer.del of the only layer, so when every previous layer
  // is going, the first new layer is added before the deletes.
  if (gone.length && gone.length === prev.layers.length && added.length) {
    const first = added.shift()
    ops.push({ op: 'layer.add', index: first.index, layer: first.layer })
  }
  for (const layer of gone) ops.push({ op: 'layer.del', id: layer.id })
  for (const { layer, index } of added) ops.push({ op: 'layer.add', index, layer })

  const nextElIds = new Set(next.layers.flatMap(layer => layer.elements.map(el => el.id)))
  for (const layer of next.layers) {
    const before = prevById.get(layer.id)
    if (before && before !== layer) diffLayer(before, layer, nextElIds, ops)
  }
  if (!sameRelativeOrder(prev.layers, next.layers)) {
    ops.push({ op: 'layer.order', ids: next.layers.map(layer => layer.id) })
  }
  if (prev.background !== next.background) {
    ops.push({ op: 'doc.set', set: { background: next.background } })
  }
  return ops
}
