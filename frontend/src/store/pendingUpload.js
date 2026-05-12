/**
 * 临时存储待上传的文件、URL 列表和需求
 * 用于首页点击启动引擎后立即跳转，在Process页面再进行API调用
 */
import { reactive } from 'vue'

const state = reactive({
  files: [],
  urls: [],
  simulationRequirement: '',
  isPending: false
})

export function setPendingUpload(files, requirement, urls = []) {
  state.files = files
  state.urls = urls
  state.simulationRequirement = requirement
  state.isPending = true
}

export function getPendingUpload() {
  return {
    files: state.files,
    urls: state.urls,
    simulationRequirement: state.simulationRequirement,
    isPending: state.isPending
  }
}

export function clearPendingUpload() {
  state.files = []
  state.urls = []
  state.simulationRequirement = ''
  state.isPending = false
}

export default state
