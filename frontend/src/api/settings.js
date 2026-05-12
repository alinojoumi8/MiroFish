import service from './index'

export const getLlmProvider = () => service.get('/api/settings/llm-provider')

export const setLlmProvider = (provider, model = null) =>
  service.post('/api/settings/llm-provider', { provider, model })
