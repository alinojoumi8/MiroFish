import axios from 'axios'
import i18n from '../i18n'
import { useToast } from '../composables/useToast'

// 创建axios实例
// 默认使用相对路径 (''），让请求落在当前页面 origin，由 Vite dev server 的 /api 代理转发到后端。
// 这样无论是 host 上的 `npm run dev` 还是 Docker 内部署，都不会出现 CORS / 端口不匹配的问题。
// 如果想覆盖（例如前后端分离部署到不同域名），通过 VITE_API_BASE_URL 设置完整 URL。
const service = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? '',
  timeout: 300000, // 5分钟超时（本体生成可能需要较长时间）
  headers: {
    'Content-Type': 'application/json'
  }
})

// 请求拦截器
service.interceptors.request.use(
  config => {
    config.headers['Accept-Language'] = i18n.global.locale.value
    return config
  },
  error => {
    console.error('Request error:', error)
    return Promise.reject(error)
  }
)

// 响应拦截器（容错重试机制）
service.interceptors.response.use(
  response => {
    const res = response.data

    if (!res.success && res.success !== undefined) {
      const msg = res.error || res.message || 'Unknown error'
      console.error('API Error:', msg)
      const { showToast } = useToast()
      showToast(msg, 'error')
      return Promise.reject(new Error(msg))
    }

    return res
  },
  error => {
    console.error('Response error:', error)
    const { showToast } = useToast()

    if (error.code === 'ECONNABORTED' && error.message.includes('timeout')) {
      showToast('Request timed out — please try again', 'error')
    } else if (error.message === 'Network Error') {
      showToast('Network error — please check your connection', 'error')
    } else if (error.message && !error.message.startsWith('Request failed')) {
      // Avoid double-toasting errors already shown above
      showToast(error.message, 'error')
    }

    return Promise.reject(error)
  }
)

// 带重试的请求函数
export const requestWithRetry = async (requestFn, maxRetries = 3, delay = 1000) => {
  for (let i = 0; i < maxRetries; i++) {
    try {
      return await requestFn()
    } catch (error) {
      if (i === maxRetries - 1) throw error
      
      console.warn(`Request failed, retrying (${i + 1}/${maxRetries})...`)
      await new Promise(resolve => setTimeout(resolve, delay * Math.pow(2, i)))
    }
  }
}

export default service
