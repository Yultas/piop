/**
 * Device Fingerprint Collector
 * Captures stable hardware & browser entropy components:
 * - Canvas 2D rendering buffer
 * - OfflineAudioContext frequency response
 * - Screen geometry & color depth
 * - Hardware concurrency & touch capability
 * - Operating system platform & timezone
 *
 * Produces a deterministic raw entropy string sent to backend for cryptographic hashing.
 */

async function getCanvasEntropy() {
  try {
    const canvas = document.createElement('canvas')
    canvas.width = 240
    canvas.height = 60
    const ctx = canvas.getContext('2d')
    if (!ctx) return 'canvas_no_context'

    // Render complex text, colors, geometric shapes, and alpha blending
    ctx.textBaseline = 'top'
    ctx.font = '14px Arial, sans-serif'
    ctx.fillStyle = '#f60'
    ctx.fillRect(125, 1, 62, 20)

    ctx.fillStyle = '#069'
    ctx.fillText('E-Ink Workspace Fingerprint ✒️ 123', 2, 15)
    ctx.fillStyle = 'rgba(102, 204, 0, 0.7)'
    ctx.fillText('Security & Integrity', 4, 35)

    // Draw an arc
    ctx.beginPath()
    ctx.arc(200, 30, 15, 0, Math.PI * 2, true)
    ctx.closePath()
    ctx.fill()

    return canvas.toDataURL()
  } catch (e) {
    return `canvas_err:${e.message}`
  }
}

async function getAudioEntropy() {
  return new Promise((resolve) => {
    try {
      const AudioCtx = window.OfflineAudioContext || window.webkitOfflineAudioContext
      if (!AudioCtx) {
        resolve('audio_unsupported')
        return
      }

      // 1 channel, 44100 Hz, 4410 samples (0.1 sec)
      const context = new AudioCtx(1, 44100, 44100)
      const oscillator = context.createOscillator()
      oscillator.type = 'triangle'
      oscillator.frequency.setValueAtTime(10000, context.currentTime)

      const compressor = context.createDynamicsCompressor()
      compressor.threshold.setValueAtTime(-50, context.currentTime)
      compressor.knee.setValueAtTime(40, context.currentTime)
      compressor.ratio.setValueAtTime(12, context.currentTime)
      compressor.reduction.setValueAtTime(-20, context.currentTime)
      compressor.attack.setValueAtTime(0, context.currentTime)
      compressor.release.setValueAtTime(0.25, context.currentTime)

      oscillator.connect(compressor)
      compressor.connect(context.destination)
      oscillator.start(0)

      context.oncomplete = (event) => {
        try {
          const samples = event.renderedBuffer.getChannelData(0)
          let sum = 0
          for (let i = 4500; i < 5000 && i < samples.length; i++) {
            sum += Math.abs(samples[i])
          }
          resolve(`audio_hash:${sum.toFixed(8)}`)
        } catch {
          resolve('audio_buffer_error')
        }
      }

      context.startRendering().catch(() => {
        resolve('audio_render_rejected')
      })
    } catch (e) {
      resolve(`audio_err:${e.message}`)
    }
  })
}

function getScreenEntropy() {
  const width = window.screen?.width || 0
  const height = window.screen?.height || 0
  const colorDepth = window.screen?.colorDepth || 0
  const pixelRatio = window.devicePixelRatio || 1
  return `${width}x${height}x${colorDepth}@${pixelRatio}`
}

function getHardwareEntropy() {
  const cores = navigator.hardwareConcurrency || 0
  const touch = navigator.maxTouchPoints || 0
  return `cores:${cores}|touch:${touch}`
}

function getPlatformEntropy() {
  const platform = navigator.platform || ''
  const lang = navigator.language || ''
  let tz = ''
  try {
    tz = Intl.DateTimeFormat().resolvedOptions().timeZone || ''
  } catch {
    tz = 'unknown'
  }
  const offset = new Date().getTimezoneOffset()
  return `platform:${platform}|lang:${lang}|tz:${tz}|offset:${offset}`
}

/**
 * Computes and returns the consolidated raw entropy string of the client device.
 */
export async function getDeviceFingerprintEntropy() {
  const [canvas, audio] = await Promise.all([
    getCanvasEntropy(),
    getAudioEntropy()
  ])

  const screen = getScreenEntropy()
  const hardware = getHardwareEntropy()
  const platform = getPlatformEntropy()

  const rawEntropy = [
    `canvas:${canvas}`,
    `audio:${audio}`,
    `screen:${screen}`,
    `hw:${hardware}`,
    `platform:${platform}`
  ].join(';;;')

  return rawEntropy
}

/**
 * Returns a brief visual representation/hash for UI display.
 */
export async function getFingerprintPreview(rawEntropy) {
  try {
    if (window.crypto?.subtle) {
      const msgBuffer = new TextEncoder().encode(rawEntropy)
      const hashBuffer = await window.crypto.subtle.digest('SHA-256', msgBuffer)
      const hashArray = Array.from(new Uint8Array(hashBuffer))
      const hashHex = hashArray.map(b => b.toString(16).padStart(2, '0')).join('')
      return hashHex.slice(0, 16)
    }
  } catch {
    // fallback
  }
  return 'fp_' + Math.abs(rawEntropy.split('').reduce((a, b) => ((a << 5) - a) + b.charCodeAt(0), 0)).toString(16).slice(0, 8)
}

export default getDeviceFingerprintEntropy
