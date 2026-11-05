import { test } from 'node:test'
import assert from 'node:assert/strict'
import { applyOps, diffState } from './sync.js'

const el = (id, props = {}) => ({ id, type: 'rect', x: 0, y: 0, ...props })
const layer = (id, elements = [], props = {}) => ({ id, name: id, visible: true, locked: false, elements, ...props })
/** Compact view of layers: [[layerId, [elementIds]], ...]. */
const shape = layers => layers.map(l => [l.id, l.elements.map(e => e.id)])

function deepFreeze(value) {
  if (value && typeof value === 'object' && !Object.isFrozen(value)) {
    Object.freeze(value)
    for (const v of Object.values(value)) deepFreeze(v)
  }
  return value
}

function mulberry32(seed) {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const BACKGROUNDS = ['dots', 'grid', 'none']

/** Seeded random prev/next pair; `next` is built copy-on-write from `prev`. */
function randomCase(seed) {
  const rand = mulberry32(seed)
  const int = n => Math.floor(rand() * n)
  const pick = list => list[int(list.length)]
  let count = 0
  const newId = prefix => `${prefix}${++count}`
  const newEl = () => {
    const e = { id: newId('e'), type: pick(['rect', 'ellipse', 'text']), x: int(100), y: int(100) }
    if (rand() < 0.5) e.label = `t${int(9)}`
    return e
  }
  const newLayer = n => ({
    id: newId('l'),
    name: `Layer ${count}`,
    visible: rand() < 0.8,
    locked: rand() < 0.2,
    elements: Array.from({ length: n }, newEl)
  })
  const shuffle = list => {
    const out = list.slice()
    for (let i = out.length - 1; i > 0; i--) {
      const j = int(i + 1)
      ;[out[i], out[j]] = [out[j], out[i]]
    }
    return out
  }

  const prev = {
    layers: Array.from({ length: 1 + int(4) }, () => newLayer(int(5))),
    background: pick(BACKGROUNDS)
  }

  let layers = prev.layers.slice()
  let background = prev.background
  const setElements = (li, elements) => {
    layers[li] = { ...layers[li], elements }
  }

  const actions = [
    () => { // modify an element: assign a key, or unset one
      const li = int(layers.length)
      const els = layers[li].elements
      if (!els.length) return
      const ei = int(els.length)
      const e = { ...els[ei] }
      const r = rand()
      if (r < 0.4) e.x = int(100)
      else if (r < 0.7) e.label = `t${int(9)}`
      else delete e.label
      const copy = els.slice()
      copy[ei] = e
      setElements(li, copy)
    },
    () => { // add an element
      const li = int(layers.length)
      const copy = layers[li].elements.slice()
      copy.splice(int(copy.length + 1), 0, newEl())
      setElements(li, copy)
    },
    () => { // remove an element
      const li = int(layers.length)
      if (!layers[li].elements.length) return
      const copy = layers[li].elements.slice()
      copy.splice(int(copy.length), 1)
      setElements(li, copy)
    },
    () => { // move an element to another layer
      if (layers.length < 2) return
      const src = int(layers.length)
      if (!layers[src].elements.length) return
      const dst = (src + 1 + int(layers.length - 1)) % layers.length
      const srcCopy = layers[src].elements.slice()
      const [moved] = srcCopy.splice(int(srcCopy.length), 1)
      const dstCopy = layers[dst].elements.slice()
      dstCopy.splice(int(dstCopy.length + 1), 0, moved)
      setElements(src, srcCopy)
      setElements(dst, dstCopy)
    },
    () => { // reorder elements within a layer
      const li = int(layers.length)
      setElements(li, shuffle(layers[li].elements))
    },
    () => { // add a layer
      layers.splice(int(layers.length + 1), 0, newLayer(int(3)))
    },
    () => { // remove a layer, keeping at least one
      if (layers.length > 1) layers.splice(int(layers.length), 1)
    },
    () => { // rename or toggle a layer flag
      const li = int(layers.length)
      const r = rand()
      if (r < 0.33) layers[li] = { ...layers[li], name: `Renamed ${int(9)}` }
      else if (r < 0.66) layers[li] = { ...layers[li], visible: !layers[li].visible }
      else layers[li] = { ...layers[li], locked: !layers[li].locked }
    },
    () => { // reorder layers
      layers = shuffle(layers)
    },
    () => { // change background
      background = pick(BACKGROUNDS)
    },
    () => { // move an element into a brand-new layer
      const src = int(layers.length)
      if (!layers[src].elements.length) return
      const srcCopy = layers[src].elements.slice()
      const [moved] = srcCopy.splice(int(srcCopy.length), 1)
      setElements(src, srcCopy)
      layers.splice(int(layers.length + 1), 0, { ...newLayer(0), elements: [moved] })
    }
  ]

  const steps = 1 + int(6)
  for (let s = 0; s < steps; s++) {
    if (rand() < 0.08) {
      // replace every layer, so no previous layer survives
      layers = [newLayer(int(3)), newLayer(1 + int(2))]
    } else {
      actions[int(actions.length)]()
    }
  }
  return { prev, next: { layers, background } }
}

// ---------- applyOps ----------

test('el.add inserts at the index and clamps it to the layer bounds', () => {
  const s = { layers: [layer('A', [el('a'), el('b')])], background: 'dots' }
  const at = index => shape(applyOps(s, [{ op: 'el.add', layer: 'A', index, el: el('c') }]).layers)
  assert.deepStrictEqual(at(1), [['A', ['a', 'c', 'b']]])
  assert.deepStrictEqual(at(99), [['A', ['a', 'b', 'c']]])
  assert.deepStrictEqual(at(-5), [['A', ['c', 'a', 'b']]])
})

test('el.add of an existing id moves the element (remove, then insert)', () => {
  const s = { layers: [layer('A', [el('a'), el('b')]), layer('B', [el('c')])], background: 'dots' }
  const across = applyOps(s, [{ op: 'el.add', layer: 'B', index: 0, el: el('a') }])
  assert.deepStrictEqual(shape(across.layers), [['A', ['b']], ['B', ['a', 'c']]])
  const within = applyOps(s, [{ op: 'el.add', layer: 'A', index: 2, el: el('a') }])
  assert.deepStrictEqual(shape(within.layers), [['A', ['b', 'a']], ['B', ['c']]])
})

test('el.add to a missing layer is skipped without removing the element', () => {
  const s = { layers: [layer('A', [el('a')])], background: 'dots' }
  const out = applyOps(s, [{ op: 'el.add', layer: 'Z', index: 0, el: el('a') }])
  assert.deepStrictEqual(shape(out.layers), [['A', ['a']]])
})

test('el.set assigns and unsets keys; a missing element is skipped', () => {
  const s = { layers: [layer('A', [el('a', { label: 'x', w: 1 })])], background: 'dots' }
  const out = applyOps(s, [{ op: 'el.set', id: 'a', set: { x: 5, w: 2 }, unset: ['label'] }])
  assert.deepStrictEqual(out.layers[0].elements[0], { id: 'a', type: 'rect', x: 5, y: 0, w: 2 })
  assert.deepStrictEqual(applyOps(s, [{ op: 'el.set', id: 'nope', set: { x: 1 } }]).layers, s.layers)
})

test('el.del removes the element and ignores a missing id', () => {
  const s = { layers: [layer('A', [el('a'), el('b')])], background: 'dots' }
  assert.deepStrictEqual(shape(applyOps(s, [{ op: 'el.del', id: 'a' }]).layers), [['A', ['b']]])
  assert.deepStrictEqual(shape(applyOps(s, [{ op: 'el.del', id: 'zz' }]).layers), [['A', ['a', 'b']]])
})

test('el.order lists ids first and appends unlisted elements in current order', () => {
  const s = { layers: [layer('A', [el('a'), el('b'), el('c'), el('d')]), layer('B', [el('x')])], background: 'dots' }
  const out = applyOps(s, [{ op: 'el.order', layer: 'A', ids: ['c', 'x', 'missing', 'a', 'c'] }])
  assert.deepStrictEqual(shape(out.layers), [['A', ['c', 'a', 'b', 'd']], ['B', ['x']]])
})

test('layer.add inserts at the clamped index and takes elements away from other layers', () => {
  const s = { layers: [layer('A', [el('a'), el('b')]), layer('B', [el('c')])], background: 'dots' }
  const out = applyOps(s, [{ op: 'layer.add', index: 1, layer: layer('N', [el('b'), el('n')]) }])
  assert.deepStrictEqual(shape(out.layers), [['A', ['a']], ['N', ['b', 'n']], ['B', ['c']]])
  const end = applyOps(s, [{ op: 'layer.add', index: 50, layer: layer('M') }])
  assert.deepStrictEqual(shape(end.layers).map(([id]) => id), ['A', 'B', 'M'])
})

test('layer.add replaces an existing layer with the same id', () => {
  const s = { layers: [layer('A', [el('a')]), layer('B')], background: 'dots' }
  const out = applyOps(s, [{ op: 'layer.add', index: 0, layer: layer('A', [el('z')]) }])
  assert.deepStrictEqual(shape(out.layers), [['A', ['z']], ['B', []]])
})

test('layer.set assigns name, visible and locked; a missing layer is skipped', () => {
  const s = { layers: [layer('A')], background: 'dots' }
  const out = applyOps(s, [{ op: 'layer.set', id: 'A', set: { name: 'Ink', visible: false, locked: true } }])
  assert.deepStrictEqual(out.layers[0], { id: 'A', name: 'Ink', visible: false, locked: true, elements: [] })
  assert.deepStrictEqual(applyOps(s, [{ op: 'layer.set', id: 'Z', set: { name: 'x' } }]).layers, s.layers)
})

test('layer.del removes a layer but skips the only one', () => {
  const s = { layers: [layer('A'), layer('B')], background: 'dots' }
  assert.deepStrictEqual(shape(applyOps(s, [{ op: 'layer.del', id: 'A' }]).layers), [['B', []]])
  const one = { layers: [layer('A')], background: 'dots' }
  assert.deepStrictEqual(shape(applyOps(one, [{ op: 'layer.del', id: 'A' }]).layers), [['A', []]])
})

test('layer.order lists ids first and appends unlisted layers', () => {
  const s = { layers: [layer('A'), layer('B'), layer('C')], background: 'dots' }
  const out = applyOps(s, [{ op: 'layer.order', ids: ['C', 'A'] }])
  assert.deepStrictEqual(out.layers.map(l => l.id), ['C', 'A', 'B'])
})

test('doc.set changes background; title and unknown ops are ignored', () => {
  const s = { layers: [layer('A')], background: 'dots' }
  const out = applyOps(s, [
    { op: 'doc.set', set: { background: 'grid' } },
    { op: 'title', title: 'Board' },
    { op: 'bogus', x: 1 }
  ])
  assert.deepStrictEqual(out, { layers: s.layers, background: 'grid' })
})

test('applyOps keeps untouched layers and elements by identity and never mutates its input', () => {
  const a1 = el('a1')
  const a2 = el('a2')
  const b1 = el('b1')
  const A = layer('A', [a1, a2])
  const B = layer('B', [b1])
  const C = layer('C')
  const state = deepFreeze({ layers: [A, B, C], background: 'dots' })
  const snapshot = structuredClone(state)
  const ops = deepFreeze([
    { op: 'el.set', id: 'a2', set: { x: 9 } },
    { op: 'el.del', id: 'b1' }
  ])

  const out = applyOps(state, ops)

  assert.notEqual(out.layers[0], A)
  assert.equal(out.layers[0].elements[0], a1)
  assert.notEqual(out.layers[1], B)
  assert.equal(out.layers[2], C)
  assert.deepStrictEqual(state, snapshot)
})

// ---------- diffState ----------

test('diffState emits nothing for identical state', () => {
  const s = { layers: [layer('A', [el('a')])], background: 'dots' }
  assert.deepStrictEqual(diffState(s, s), [])
  assert.deepStrictEqual(diffState(s, { layers: s.layers.slice(), background: 'dots' }), [])
})

test('diffState: element add and remove emit el.del and el.add, no el.order', () => {
  const b = el('b')
  const c = el('c')
  const prev = { layers: [layer('A', [el('a'), b])], background: 'dots' }
  const next = { layers: [layer('A', [b, c])], background: 'dots' }
  assert.deepStrictEqual(diffState(prev, next), [
    { op: 'el.del', id: 'a' },
    { op: 'el.add', layer: 'A', index: 1, el: c }
  ])
})

test('diffState: changed keys become el.set with set and unset', () => {
  const prev = { layers: [layer('A', [el('a', { label: 'hi', x: 0 })])], background: 'dots' }
  const next = { layers: [layer('A', [el('a', { x: 5 })])], background: 'dots' }
  assert.deepStrictEqual(diffState(prev, next), [{ op: 'el.set', id: 'a', set: { x: 5 }, unset: ['label'] }])
})

test('diffState: a reorder within a layer emits el.order with the full next id list', () => {
  const a = el('a')
  const b = el('b')
  const c = el('c')
  const prev = { layers: [layer('A', [a, b, c])], background: 'dots' }
  const next = { layers: [layer('A', [c, a, b])], background: 'dots' }
  assert.deepStrictEqual(diffState(prev, next), [{ op: 'el.order', layer: 'A', ids: ['c', 'a', 'b'] }])
})

test('diffState: layer add, delete, flag change and reorder', () => {
  const A = layer('A')
  const B = layer('B')
  const C = layer('C')
  const N = layer('N')
  assert.deepStrictEqual(
    diffState({ layers: [A, B], background: 'dots' }, { layers: [A, N, B], background: 'dots' }),
    [{ op: 'layer.add', index: 1, layer: N }]
  )
  assert.deepStrictEqual(
    diffState({ layers: [A, B], background: 'dots' }, { layers: [A], background: 'dots' }),
    [{ op: 'layer.del', id: 'B' }]
  )
  assert.deepStrictEqual(
    diffState({ layers: [A], background: 'dots' }, { layers: [{ ...A, name: 'x', locked: true }], background: 'dots' }),
    [{ op: 'layer.set', id: 'A', set: { name: 'x', locked: true } }]
  )
  assert.deepStrictEqual(
    diffState({ layers: [A, B, C], background: 'dots' }, { layers: [C, A, B], background: 'dots' }),
    [{ op: 'layer.order', ids: ['C', 'A', 'B'] }]
  )
})

test('diffState: background change emits doc.set', () => {
  const layers = [layer('A')]
  assert.deepStrictEqual(
    diffState({ layers, background: 'dots' }, { layers, background: 'grid' }),
    [{ op: 'doc.set', set: { background: 'grid' } }]
  )
})

test('round-trip holds when an element moves out of a layer that is processed later', () => {
  const e = el('e')
  const f = el('f')
  const prev = { layers: [layer('A', [e, f]), layer('B')], background: 'dots' }
  const movedToNew = { layers: [layer('N', [e]), layer('A', [f]), layer('B')], background: 'dots' }
  assert.deepStrictEqual(applyOps(prev, diffState(prev, movedToNew)), movedToNew)

  const prev2 = { layers: [layer('A', [e]), layer('B')], background: 'dots' }
  const movedToB = { layers: [layer('B', [e]), layer('A')], background: 'dots' }
  assert.deepStrictEqual(applyOps(prev2, diffState(prev2, movedToB)), movedToB)
})

test('round-trip holds for moves between layers and full layer replacement', () => {
  const e = el('e')
  const prev = { layers: [layer('A', [e]), layer('B')], background: 'dots' }
  const moved = { layers: [layer('A'), layer('B', [e])], background: 'dots' }
  assert.deepStrictEqual(applyOps(prev, diffState(prev, moved)), moved)

  const single = { layers: [layer('A', [el('a')])], background: 'dots' }
  const replaced = { layers: [layer('N', [el('n')])], background: 'grid' }
  assert.deepStrictEqual(applyOps(single, diffState(single, replaced)), replaced)
})

// ---------- round trip ----------

test('round-trip: applyOps(prev, diffState(prev, next)) deep-equals next over 200 seeded cases', () => {
  let opCount = 0
  for (let seed = 1; seed <= 200; seed++) {
    const { prev, next } = randomCase(seed)
    deepFreeze(prev)
    deepFreeze(next)
    const ops = diffState(prev, next)
    opCount += ops.length
    assert.deepStrictEqual(applyOps(prev, ops), next, `seed ${seed}`)
  }
  assert.ok(opCount > 200, 'the random cases must produce real changes')
})
