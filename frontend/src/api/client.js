/**
 * E-Ink Workspace HTTP API Client
 * Wraps native fetch with cookie-based auth (HttpOnly session cookie sent via
 * credentials: 'same-origin'), the X-Piop-CSRF header on every request,
 * consistent JSON parsing, and structured ApiError handling for i18n-ready
 * error details.
 */

export class ApiError extends Error {
  constructor(status, detail, data = null) {
    super(typeof detail === 'string' ? detail : JSON.stringify(detail))
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.data = data
  }
}

// Required on cookie-authenticated non-GET requests; raw fetch callers spread this in
export const csrfHeaders = { 'X-Piop-CSRF': '1' }

async function request(endpoint, options = {}) {
  const headers = new Headers(options.headers || {})

  // Always send the CSRF marker header; the session itself travels in the HttpOnly cookie
  headers.set('X-Piop-CSRF', csrfHeaders['X-Piop-CSRF'])

  // Set default JSON Content-Type if sending body and not FormData
  if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const url = endpoint.startsWith('http') ? endpoint : endpoint

  try {
    const response = await fetch(url, {
      ...options,
      headers,
      credentials: 'same-origin'
    })

    // Handle 204 No Content
    if (response.status === 204) {
      return null
    }

    const contentType = response.headers.get('content-type') || ''
    const isJson = contentType.includes('application/json')
    const responseData = isJson ? await response.json() : await response.text()

    if (!response.ok) {
      let detail = 'common.error'
      if (isJson && responseData) {
        detail = responseData.detail || responseData.message || detail
      } else if (typeof responseData === 'string' && responseData.length < 200) {
        detail = responseData
      }

      // If unauthorized on protected route, emit event or clear token if not already logging in
      if (response.status === 401 && !endpoint.includes('/api/auth/login')) {
        window.dispatchEvent(new CustomEvent('eink:unauthorized'))
      }

      throw new ApiError(response.status, detail, responseData)
    }

    return responseData
  } catch (err) {
    if (err instanceof ApiError) {
      throw err
    }
    throw new ApiError(0, err.message || 'Network Error')
  }
}

export const api = {
  get: (url, options = {}) => request(url, { method: 'GET', ...options }),
  post: (url, body, options = {}) =>
    request(url, {
      method: 'POST',
      body: body instanceof FormData ? body : (body !== undefined ? JSON.stringify(body) : undefined),
      ...options
    }),
  put: (url, body, options = {}) =>
    request(url, {
      method: 'PUT',
      body: body instanceof FormData ? body : (body !== undefined ? JSON.stringify(body) : undefined),
      ...options
    }),
  patch: (url, body, options = {}) =>
    request(url, {
      method: 'PATCH',
      body: body instanceof FormData ? body : (body !== undefined ? JSON.stringify(body) : undefined),
      ...options
    }),
  delete: (url, options = {}) => request(url, { method: 'DELETE', ...options })
}

export default api
