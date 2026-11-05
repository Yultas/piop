/**
 * Open a live connection to one board. Reconnects with backoff (1 s doubling to 15 s) unless the server
 * closed with 4401/4403/4404, or close() was called.
 */
export function connectBoard({ workspaceId, boardId, onInit, onOps, onAck, onReset, onPeers, onStatus }) {
  let ws = null
  let seq = 0
  let delay = 1000
  let pingTimer = null
  let retryTimer = null
  let closed = false

  function open() {
    onStatus('connecting')
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    ws = new WebSocket(`${proto}://${location.host}/api/workspaces/${workspaceId}/documents/${boardId}/ws`)
    ws.onopen = () => {
      pingTimer = setInterval(() => ws.send(JSON.stringify({ t: 'ping' })), 30000)
    }
    ws.onmessage = e => {
      if (closed) return
      let msg
      try { msg = JSON.parse(e.data) } catch { return }
      if (msg.t === 'init') {
        delay = 1000
        onStatus('live')
        onInit(msg)
      } else if (msg.t === 'ops') onOps(msg)
      else if (msg.t === 'ack') onAck(msg.cid)
      else if (msg.t === 'reset') onReset(msg)
      else if (msg.t === 'peers') onPeers(msg.peers)
    }
    ws.onclose = e => {
      clearInterval(pingTimer)
      ws = null
      if (closed) return
      if ([4401, 4403, 4404].includes(e.code)) return onStatus('denied')
      onStatus('offline')
      retryTimer = setTimeout(open, delay)
      delay = Math.min(delay * 2, 15000)
    }
  }

  open()

  return {
    send(ops) {
      if (!ws || ws.readyState !== WebSocket.OPEN) return null
      seq += 1
      ws.send(JSON.stringify({ t: 'ops', cid: seq, ops }))
      return seq
    },
    close() {
      closed = true
      clearInterval(pingTimer)
      clearTimeout(retryTimer)
      ws?.close()
      ws = null
    }
  }
}
