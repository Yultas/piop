/**
 * Vector whiteboard engine: document model, geometry, rendering and export.
 *
 * Everything is stored in world coordinates. The camera maps world to screen as
 * screen = world * zoom + offset. Elements are immutable: any change produces a
 * new object, which keeps undo cheap (snapshots share untouched elements) and
 * lets render caches key on object identity.
 */
import { getStroke } from 'perfect-freehand'

export const MIN_ZOOM = 0.05
export const MAX_ZOOM = 20

// Brush presets passed to perfect-freehand
export const BRUSHES = {
  pen: { thinning: 0.6, smoothing: 0.5, streamline: 0.45, opacityScale: 1 },
  pencil: { thinning: 0.25, smoothing: 0.35, streamline: 0.3, opacityScale: 0.85, sizeScale: 0.55 },
  marker: { thinning: 0, smoothing: 0.6, streamline: 0.5, opacityScale: 0.45, sizeScale: 2.2 }
}

let idCounter = 0
export function uid(prefix = 'e') {
  idCounter += 1
  return `${prefix}${Date.now().toString(36)}${idCounter.toString(36)}${Math.random().toString(36).slice(2, 6)}`
}

// ---------- document ----------

export function createLayer(name) {
  return { id: uid('l'), name, visible: true, locked: false, elements: [] }
}

export function createDocument(layerName = 'Layer 1') {
  const layer = createLayer(layerName)
  return { version: 2, layers: [layer], activeLayerId: layer.id, background: 'dots', view: { x: 0, y: 0, zoom: 1 } }
}

/** Parse stored content; old raster boards (PNG data URLs) become an image element. */
export function parseDocument(raw, layerName) {
  if (raw && raw.startsWith('data:image')) {
    const doc = createDocument(layerName)
    doc.layers[0].elements.push({ id: uid(), type: 'image', x: 0, y: 0, w: 0, h: 0, src: raw, autoSize: true })
    return doc
  }
  try {
    const doc = JSON.parse(raw)
    if (doc && doc.version === 2 && Array.isArray(doc.layers) && doc.layers.length) {
      return { background: 'dots', view: { x: 0, y: 0, zoom: 1 }, ...doc }
    }
  } catch {
    // fall through to an empty board
  }
  return createDocument(layerName)
}

export function serializeDocument(doc) {
  return JSON.stringify(doc)
}

// ---------- geometry ----------

export function roundPoint(v, digits = 1) {
  const f = 10 ** digits
  return Math.round(v * f) / f
}

export function elementBounds(el) {
  if (el._bounds) return el._bounds
  let b
  if (el.type === 'stroke') {
    const pts = el.points
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
    for (let i = 0; i < pts.length; i += 3) {
      if (pts[i] < minX) minX = pts[i]
      if (pts[i] > maxX) maxX = pts[i]
      if (pts[i + 1] < minY) minY = pts[i + 1]
      if (pts[i + 1] > maxY) maxY = pts[i + 1]
    }
    const pad = strokeWidth(el)
    b = { minX: minX - pad, minY: minY - pad, maxX: maxX + pad, maxY: maxY + pad }
  } else if (el.type === 'line' || el.type === 'rect' || el.type === 'ellipse') {
    const pad = el.size / 2 + 1
    b = {
      minX: Math.min(el.x1, el.x2) - pad, minY: Math.min(el.y1, el.y2) - pad,
      maxX: Math.max(el.x1, el.x2) + pad, maxY: Math.max(el.y1, el.y2) + pad
    }
  } else if (el.type === 'text') {
    const lines = el.text.split('\n')
    const width = Math.max(...lines.map((l) => l.length)) * el.size * 0.6
    b = { minX: el.x, minY: el.y, maxX: el.x + width, maxY: el.y + lines.length * el.size * 1.3 }
  } else {
    b = { minX: el.x, minY: el.y, maxX: el.x + el.w, maxY: el.y + el.h }
  }
  // Cached on the (immutable) element, hidden from JSON
  Object.defineProperty(el, '_bounds', { value: b, enumerable: false })
  return b
}

export function unionBounds(list) {
  if (!list.length) return null
  const b = { minX: Infinity, minY: Infinity, maxX: -Infinity, maxY: -Infinity }
  for (const el of list) {
    const e = elementBounds(el)
    b.minX = Math.min(b.minX, e.minX)
    b.minY = Math.min(b.minY, e.minY)
    b.maxX = Math.max(b.maxX, e.maxX)
    b.maxY = Math.max(b.maxY, e.maxY)
  }
  return b
}

export function boundsIntersect(a, b) {
  return a.minX <= b.maxX && a.maxX >= b.minX && a.minY <= b.maxY && a.maxY >= b.minY
}

function distToSegment(px, py, ax, ay, bx, by) {
  const dx = bx - ax
  const dy = by - ay
  const len2 = dx * dx + dy * dy
  let t = len2 ? ((px - ax) * dx + (py - ay) * dy) / len2 : 0
  t = Math.max(0, Math.min(1, t))
  const x = ax + t * dx
  const y = ay + t * dy
  return Math.hypot(px - x, py - y)
}

export function strokeWidth(el) {
  return el.size * (BRUSHES[el.tool]?.sizeScale || 1)
}

/** Does a circle at (x, y) with radius r touch the element? */
export function hitTest(el, x, y, r) {
  const b = elementBounds(el)
  if (x < b.minX - r || x > b.maxX + r || y < b.minY - r || y > b.maxY + r) return false
  if (el.type === 'stroke') {
    const pts = el.points
    const reach = r + strokeWidth(el) / 2
    if (pts.length === 3) return Math.hypot(pts[0] - x, pts[1] - y) <= reach
    for (let i = 0; i < pts.length - 3; i += 3) {
      if (distToSegment(x, y, pts[i], pts[i + 1], pts[i + 3], pts[i + 4]) <= reach) return true
    }
    return false
  }
  const reach = r + (el.size || 0) / 2
  if (el.type === 'line') return distToSegment(x, y, el.x1, el.y1, el.x2, el.y2) <= reach
  if (el.type === 'rect') {
    const { x1, y1, x2, y2 } = el
    return (
      distToSegment(x, y, x1, y1, x2, y1) <= reach || distToSegment(x, y, x2, y1, x2, y2) <= reach ||
      distToSegment(x, y, x2, y2, x1, y2) <= reach || distToSegment(x, y, x1, y2, x1, y1) <= reach
    )
  }
  if (el.type === 'ellipse') {
    const cx = (el.x1 + el.x2) / 2
    const cy = (el.y1 + el.y2) / 2
    const rx = Math.abs(el.x2 - el.x1) / 2 || 1
    const ry = Math.abs(el.y2 - el.y1) / 2 || 1
    const d = Math.hypot((x - cx) / rx, (y - cy) / ry)
    return Math.abs(d - 1) * Math.min(rx, ry) <= reach
  }
  return true // text and images: inside the bounding box
}

/**
 * Cut the part of a stroke under the eraser circle.
 * Segments crossing the circle are subdivided first, so fast strokes with
 * sparse samples are still cut exactly where the eraser passes.
 * Returns null when the stroke is untouched, otherwise the remaining pieces.
 */
export function eraseFromStroke(el, x, y, r) {
  const pts = el.points
  const reach = r + strokeWidth(el) / 2
  let touched = false
  const dense = []
  const n = pts.length / 3
  for (let i = 0; i < n; i++) {
    const ax = pts[i * 3], ay = pts[i * 3 + 1], ap = pts[i * 3 + 2]
    dense.push(ax, ay, ap)
    if (i === n - 1) break
    const bx = pts[i * 3 + 3], by = pts[i * 3 + 4], bp = pts[i * 3 + 5]
    if (distToSegment(x, y, ax, ay, bx, by) <= reach) {
      touched = true
      const steps = Math.ceil(Math.hypot(bx - ax, by - ay) / Math.max(1, reach / 3))
      for (let s = 1; s < steps; s++) {
        const t = s / steps
        dense.push(ax + (bx - ax) * t, ay + (by - ay) * t, ap + (bp - ap) * t)
      }
    }
  }
  if (n === 1 && Math.hypot(pts[0] - x, pts[1] - y) <= reach) touched = true
  if (!touched) return null

  const pieces = []
  let run = []
  for (let i = 0; i < dense.length; i += 3) {
    if (Math.hypot(dense[i] - x, dense[i + 1] - y) <= reach) {
      if (run.length >= 6) pieces.push(run)
      run = []
    } else {
      run.push(dense[i], dense[i + 1], dense[i + 2])
    }
  }
  if (run.length >= 6) pieces.push(run)
  return pieces.map((p) => ({ ...el, id: uid(), points: p }))
}

export function pointInPolygon(x, y, poly) {
  let inside = false
  for (let i = 0, j = poly.length - 2; i < poly.length; j = i, i += 2) {
    const xi = poly[i], yi = poly[i + 1], xj = poly[j], yj = poly[j + 1]
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside
  }
  return inside
}

/** Lasso selection: most of a stroke's samples, or a shape's centre, must lie inside. */
export function insideLasso(el, poly) {
  if (el.type === 'stroke') {
    const pts = el.points
    const step = Math.max(1, Math.floor(pts.length / 3 / 24)) * 3
    let inside = 0, total = 0
    for (let i = 0; i < pts.length; i += step) {
      total += 1
      if (pointInPolygon(pts[i], pts[i + 1], poly)) inside += 1
    }
    return inside / total >= 0.6
  }
  const b = elementBounds(el)
  return pointInPolygon((b.minX + b.maxX) / 2, (b.minY + b.maxY) / 2, poly)
}

/** Apply translate and scale (around an anchor) to an element, returning a new one. */
export function transformElement(el, { dx = 0, dy = 0, sx = 1, sy = 1, ax = 0, ay = 0 }) {
  const tx = (x) => ax + (x - ax) * sx + dx
  const ty = (y) => ay + (y - ay) * sy + dy
  const k = Math.sqrt(Math.abs(sx * sy))
  if (el.type === 'stroke') {
    const pts = new Array(el.points.length)
    for (let i = 0; i < el.points.length; i += 3) {
      pts[i] = roundPoint(tx(el.points[i]))
      pts[i + 1] = roundPoint(ty(el.points[i + 1]))
      pts[i + 2] = el.points[i + 2]
    }
    return { ...el, points: pts, size: roundPoint(el.size * k, 2) }
  }
  if (el.type === 'line' || el.type === 'rect' || el.type === 'ellipse') {
    return { ...el, x1: tx(el.x1), y1: ty(el.y1), x2: tx(el.x2), y2: ty(el.y2), size: roundPoint(el.size * k, 2) }
  }
  if (el.type === 'text') return { ...el, x: tx(el.x), y: ty(el.y), size: roundPoint(el.size * k, 2) }
  return { ...el, x: tx(el.x), y: ty(el.y), w: el.w * sx, h: el.h * sy }
}

// ---------- rendering ----------

const pathCache = new WeakMap()
const imageCache = new Map()

function strokeOutline(points, el, last) {
  const brush = BRUSHES[el.tool] || BRUSHES.pen
  const input = []
  let hasPressure = false
  for (let i = 0; i < points.length; i += 3) {
    input.push([points[i], points[i + 1], points[i + 2]])
    if (points[i + 2] !== 0.5) hasPressure = true
  }
  return getStroke(input, {
    size: strokeWidth(el),
    thinning: brush.thinning,
    smoothing: brush.smoothing,
    streamline: brush.streamline,
    simulatePressure: !hasPressure && brush.thinning > 0,
    last
  })
}

function outlineToPath(outline) {
  const path = new Path2D()
  if (!outline.length) return path
  path.moveTo(outline[0][0], outline[0][1])
  for (let i = 1; i < outline.length; i++) {
    const [x0, y0] = outline[i]
    const [x1, y1] = outline[(i + 1) % outline.length]
    path.quadraticCurveTo(x0, y0, (x0 + x1) / 2, (y0 + y1) / 2)
  }
  path.closePath()
  return path
}

export function outlineToSvgPath(outline) {
  if (!outline.length) return ''
  let d = `M${outline[0][0].toFixed(1)} ${outline[0][1].toFixed(1)}`
  for (let i = 1; i < outline.length; i++) {
    const [x0, y0] = outline[i]
    const [x1, y1] = outline[(i + 1) % outline.length]
    d += ` Q${x0.toFixed(1)} ${y0.toFixed(1)} ${((x0 + x1) / 2).toFixed(1)} ${((y0 + y1) / 2).toFixed(1)}`
  }
  return d + ' Z'
}

function shapePath(el) {
  const path = new Path2D()
  if (el.type === 'line') {
    path.moveTo(el.x1, el.y1)
    path.lineTo(el.x2, el.y2)
  } else if (el.type === 'rect') {
    path.rect(Math.min(el.x1, el.x2), Math.min(el.y1, el.y2), Math.abs(el.x2 - el.x1), Math.abs(el.y2 - el.y1))
  } else {
    path.ellipse(
      (el.x1 + el.x2) / 2, (el.y1 + el.y2) / 2,
      Math.abs(el.x2 - el.x1) / 2, Math.abs(el.y2 - el.y1) / 2, 0, 0, Math.PI * 2
    )
  }
  return path
}

function getImage(src, onLoad) {
  let img = imageCache.get(src)
  if (!img) {
    img = new Image()
    img.onload = onLoad
    img.src = src
    imageCache.set(src, img)
  }
  return img.complete && img.naturalWidth ? img : null
}

/**
 * Time budget for building stroke outlines within one frame. Strokes past the
 * budget are drawn as a plain polyline and refined on following frames, so a
 * large board appears immediately instead of freezing on first render.
 */
export function createBudget(ms = 8) {
  return { deadline: performance.now() + ms, deferred: false }
}

function drawQuickStroke(ctx, el) {
  const pts = el.points
  ctx.strokeStyle = el.color
  ctx.lineWidth = strokeWidth(el) * 0.75
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
  ctx.beginPath()
  ctx.moveTo(pts[0], pts[1])
  for (let i = 3; i < pts.length; i += 3) ctx.lineTo(pts[i], pts[i + 1])
  if (pts.length === 3) ctx.lineTo(pts[0] + 0.01, pts[1])
  ctx.stroke()
}

/** Draw one element on a context already transformed to world coordinates. */
export function drawElement(ctx, el, { live = false, onImageLoad, budget = null } = {}) {
  ctx.globalAlpha = (el.opacity ?? 1) * (el.type === 'stroke' ? (BRUSHES[el.tool]?.opacityScale ?? 1) : 1)
  if (el.type === 'stroke') {
    let path = live ? null : pathCache.get(el)
    if (!path && budget && performance.now() > budget.deadline) {
      budget.deferred = true
      drawQuickStroke(ctx, el)
      ctx.globalAlpha = 1
      return
    }
    if (!path) {
      path = outlineToPath(strokeOutline(el.points, el, !live))
      if (!live) pathCache.set(el, path)
    }
    ctx.fillStyle = el.color
    ctx.fill(path)
  } else if (el.type === 'line' || el.type === 'rect' || el.type === 'ellipse') {
    let path = pathCache.get(el)
    if (!path) {
      path = shapePath(el)
      pathCache.set(el, path)
    }
    ctx.strokeStyle = el.color
    ctx.lineWidth = el.size
    ctx.lineCap = 'round'
    ctx.lineJoin = 'round'
    ctx.stroke(path)
  } else if (el.type === 'text') {
    ctx.fillStyle = el.color
    ctx.font = `${el.size}px Inter, system-ui, sans-serif`
    ctx.textBaseline = 'top'
    el.text.split('\n').forEach((line, i) => ctx.fillText(line, el.x, el.y + i * el.size * 1.3))
  } else if (el.type === 'image') {
    const img = getImage(el.src, onImageLoad)
    if (img) ctx.drawImage(img, el.x, el.y, el.w || img.naturalWidth, el.h || img.naturalHeight)
  }
  ctx.globalAlpha = 1
}

/** Images saved before their size was known (legacy raster boards) get it once loaded. */
export function resolveImageSize(el) {
  if (el.type !== 'image' || !el.autoSize) return null
  const img = imageCache.get(el.src)
  if (!img || !img.naturalWidth) return null
  const { autoSize, ...rest } = el
  return { ...rest, w: img.naturalWidth, h: img.naturalHeight }
}

export function drawBackground(ctx, kind, view, width, height) {
  if (kind === 'none') return
  // Grid spacing adapts to zoom so it never gets too dense or too sparse
  let step = 24 * view.zoom
  while (step < 12) step *= 4
  while (step > 96) step /= 4
  const ox = ((view.x % step) + step) % step
  const oy = ((view.y % step) + step) % step
  ctx.fillStyle = '#c9c9c4'
  ctx.strokeStyle = '#e4e4df'
  ctx.lineWidth = 1
  if (kind === 'dots') {
    for (let x = ox; x < width; x += step) {
      for (let y = oy; y < height; y += step) ctx.fillRect(Math.round(x) - 1, Math.round(y) - 1, 2, 2)
    }
  } else {
    ctx.beginPath()
    for (let x = ox; x < width; x += step) {
      ctx.moveTo(Math.round(x) + 0.5, 0)
      ctx.lineTo(Math.round(x) + 0.5, height)
    }
    for (let y = oy; y < height; y += step) {
      ctx.moveTo(0, Math.round(y) + 0.5)
      ctx.lineTo(width, Math.round(y) + 0.5)
    }
    ctx.stroke()
  }
}

export function visibleWorldBounds(view, width, height) {
  return {
    minX: -view.x / view.zoom, minY: -view.y / view.zoom,
    maxX: (width - view.x) / view.zoom, maxY: (height - view.y) / view.zoom
  }
}

// ---------- export ----------

export function contentBounds(doc) {
  return unionBounds(doc.layers.filter((l) => l.visible).flatMap((l) => l.elements))
}

export async function exportPng(doc, scale = 2, padding = 32) {
  const b = contentBounds(doc)
  if (!b) return null
  const w = Math.ceil((b.maxX - b.minX + padding * 2) * scale)
  const h = Math.ceil((b.maxY - b.minY + padding * 2) * scale)
  const canvas = document.createElement('canvas')
  canvas.width = Math.min(w, 16384)
  canvas.height = Math.min(h, 16384)
  const ctx = canvas.getContext('2d')
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  ctx.setTransform(scale, 0, 0, scale, (padding - b.minX) * scale, (padding - b.minY) * scale)
  for (const layer of doc.layers) {
    if (!layer.visible) continue
    for (const el of layer.elements) drawElement(ctx, el)
  }
  return new Promise((resolve) => canvas.toBlob(resolve, 'image/png'))
}

function escapeXml(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))
}

export function exportSvg(doc, padding = 32) {
  const b = contentBounds(doc)
  if (!b) return null
  const w = b.maxX - b.minX + padding * 2
  const h = b.maxY - b.minY + padding * 2
  const parts = []
  for (const layer of doc.layers) {
    if (!layer.visible) continue
    parts.push(`<g id="${escapeXml(layer.name)}">`)
    for (const el of layer.elements) {
      const opacity = (el.opacity ?? 1) * (el.type === 'stroke' ? (BRUSHES[el.tool]?.opacityScale ?? 1) : 1)
      const op = opacity < 1 ? ` opacity="${opacity.toFixed(2)}"` : ''
      if (el.type === 'stroke') {
        parts.push(`<path d="${outlineToSvgPath(strokeOutline(el.points, el, true))}" fill="${el.color}"${op}/>`)
      } else if (el.type === 'line') {
        parts.push(`<line x1="${el.x1}" y1="${el.y1}" x2="${el.x2}" y2="${el.y2}" stroke="${el.color}" stroke-width="${el.size}" stroke-linecap="round"${op}/>`)
      } else if (el.type === 'rect') {
        parts.push(`<rect x="${Math.min(el.x1, el.x2)}" y="${Math.min(el.y1, el.y2)}" width="${Math.abs(el.x2 - el.x1)}" height="${Math.abs(el.y2 - el.y1)}" fill="none" stroke="${el.color}" stroke-width="${el.size}" stroke-linejoin="round"${op}/>`)
      } else if (el.type === 'ellipse') {
        parts.push(`<ellipse cx="${(el.x1 + el.x2) / 2}" cy="${(el.y1 + el.y2) / 2}" rx="${Math.abs(el.x2 - el.x1) / 2}" ry="${Math.abs(el.y2 - el.y1) / 2}" fill="none" stroke="${el.color}" stroke-width="${el.size}"${op}/>`)
      } else if (el.type === 'text') {
        el.text.split('\n').forEach((line, i) => {
          parts.push(`<text x="${el.x}" y="${el.y + i * el.size * 1.3}" font-size="${el.size}" font-family="Inter, sans-serif" dominant-baseline="hanging" fill="${el.color}"${op}>${escapeXml(line)}</text>`)
        })
      } else if (el.type === 'image') {
        parts.push(`<image href="${el.src}" x="${el.x}" y="${el.y}" width="${el.w}" height="${el.h}"/>`)
      }
    }
    parts.push('</g>')
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${b.minX - padding} ${b.minY - padding} ${w} ${h}" width="${w}" height="${h}"><rect x="${b.minX - padding}" y="${b.minY - padding}" width="${w}" height="${h}" fill="#ffffff"/>${parts.join('')}</svg>`
}
