import request from '@/utils/request'

// 认证相关 API
export const authApi = {
  // 登录
  login: (username, password) => request.post('/api/auth/login', { username, password }),
  
  // 注册
  register: (username, email, password) => request.post('/api/auth/register', { username, email, password }),
  
  // 刷新令牌
  refreshToken: (refreshToken) => request.post('/api/auth/refresh', { refresh_token: refreshToken })
}

// 任务相关 API
export const taskApi = {
  // 获取任务列表
  getTasks: () => request.get('/api/tasks'),
  
  // 获取任务详情
  getTask: (taskId) => request.get(`/api/tasks/${taskId}`),
  
  // 创建任务
  createTask: (data) => request.post('/api/tasks', data),
  
  // 更新任务
  updateTask: (taskId, data) => request.put(`/api/tasks/${taskId}`, data),
  
  // 删除任务
  deleteTask: (taskId) => request.delete(`/api/tasks/${taskId}`),
  delete: (taskId) => request.delete(`/api/tasks/${taskId}`),
  
  // 任务控制 (start/cancel/priority/pause/resume/retry)
  control: (taskId, action) => request.post(`/api/tasks/${taskId}/${action}`),
  
  // 取消任务
  cancelTask: (taskId) => request.post(`/api/tasks/${taskId}/cancel`),

  // 生成文案
  generateScript: (data) => request.post('/api/generate-script', data),
  
  // 提取音频
  extractAudio: (videoPath) => request.post(`/api/tasks/extract-audio?video_path=${encodeURIComponent(videoPath)}`),
  
  // 音频降噪
  denoiseAudio: (audioPath) => request.post('/api/audio-denoise', { audio_path: audioPath }),

  // 面部分析（同步接口，保留向后兼容）
  analyzeFace: (videoPath) => request.post(`/api/tasks/analyze-face?video_path=${encodeURIComponent(videoPath)}`),

  // 异步面部分析 → AC-227
  analyzeFaceAsync: (videoPath) => request.post('/api/face-analysis-async', { video_path: videoPath }),

  // 查询面部分析任务状态 → AC-227
  getFaceAnalysisStatus: (taskId) => request.get(`/api/face-analysis-status/${taskId}`),

  // 取消面部分析任务 → AC-230
  cancelFaceAnalysis: (taskId) => request.post(`/api/face-analysis-cancel/${taskId}`)
}

// 素材相关 API
export const materialApi = {
  // 获取素材列表（按类型）
  getMaterials: (type) => request.get('/api/materials', { params: { type } }),

  // 获取素材详情
  getMaterial: (materialId) => request.get(`/api/materials/${materialId}`),

  // 创建素材 - 使用查询参数，因为后端期望 query.type 和 query.name
  create: (data) => {
    const params = { type: data.type, name: data.name }
    if (data.type === 'role') {
      params.role_type = data.role_type
      params.scenes = data.scenes
      params.opening_video = data.opening_video
      params.loop_videos = JSON.stringify(data.loop_videos || [])
      params.ending_video = data.ending_video
      params.audio_id = data.audio_id
      params.is_double_mode = data.is_double_mode || false
      if (data.is_double_mode) {
        params.left_audio_id = data.left_audio_id
        params.right_audio_id = data.right_audio_id
      }
    }
    if (data.type === 'scene') {
      params.scene_videos = JSON.stringify(data.scene_videos || [])
    }
    if (data.type === 'audio') {
      params.audio_clips = JSON.stringify(data.audio_clips)
      params.duration = data.duration
    }
    if (data.type === 'bgm') {
      params.bgm_path = data.bgm_path
      params.duration = data.duration
    }
    return request.post('/api/materials', null, { params })
  },

  // 更新素材 - 使用查询参数
  update: (materialId, data) => {
    const params = { type: data.type, name: data.name }
    if (data.type === 'role') {
      params.role_type = data.role_type
      params.scenes = data.scenes
      params.opening_video = data.opening_video
      params.loop_videos = JSON.stringify(data.loop_videos || [])
      params.ending_video = data.ending_video
      params.audio_id = data.audio_id
      params.is_double_mode = data.is_double_mode || false
      if (data.is_double_mode) {
        params.left_audio_id = data.left_audio_id
        params.right_audio_id = data.right_audio_id
      }
    }
    if (data.type === 'scene') {
      params.scene_videos = JSON.stringify(data.scene_videos || [])
    }
    if (data.type === 'audio') {
      params.audio_clips = JSON.stringify(data.audio_clips)
    }
    if (data.type === 'bgm') {
      params.bgm_path = data.bgm_path
      params.duration = data.duration
    }
    return request.put(`/api/materials/${materialId}`, null, { params })
  },

  // 删除素材
  delete: (materialId, type) => request.delete(`/api/materials/${materialId}`, { params: { type } }),

  // 获取BGM列表
  getBGM: () => request.get('/api/materials/bgm'),

  // 上传素材文件
  uploadMaterial: (formData) => request.post('/api/materials/upload', formData, {
    headers: {
      'Content-Type': 'multipart/form-data'
    }
  })
}

// 设置相关 API
export const settingsApi = {
  // 获取所有设置
  getSettings: () => request.get('/api/settings'),

  // 更新 API Key 配置
  updateApiKeys: (data) => request.post('/api/settings/api-keys', data),

  // 更新提示词模版
  updatePromptTemplates: (data) => request.post('/api/settings/prompt-templates', data),

  // 更新默认参数
  updateDefaultParams: (data) => request.post('/api/settings/default-params', data),

  // 保存所有设置
  saveAllSettings: (data) => request.post('/api/settings', data),

  // 清理缓存
  clearCache: () => request.post('/api/settings/clear-cache'),

  // 获取主题设置
  getTheme: () => request.get('/api/settings/theme'),

  // 更新主题设置
  updateTheme: (theme) => request.post('/api/settings/theme', { theme })
}

// 服务管理相关 API
export const servicesApi = {
  // 获取所有服务状态
  getStatus: () => request.get('/api/services/status'),

  // 重启服务
  restart: (serviceName) => request.post(`/api/services/${serviceName}/restart`),

  // 启动服务
  start: (serviceName) => request.post(`/api/services/${serviceName}/start`),

  // 停止服务
  stop: (serviceName) => request.post(`/api/services/${serviceName}/stop`)
}

// 系统配置相关 API
export const systemApi = {
  // 获取系统配置
  getConfig: () => request.get('/api/system/config'),

  // 更新系统配置
  updateConfig: (data) => request.put('/api/system/config', data)
}

// 功能相关 API
export const functionsApi = {
  // 提取视频首帧
  extractFrame: (videoPath) => request.post('/api/extract-frame', { video_path: videoPath }),

  // 打开输出目录
  openOutputDir: () => request.post('/api/open-output-dir')
}

// 标签相关 API
export const tagApi = {
  // 获取标签组列表
  getTagGroups: () => request.get('/api/tags/groups'),
  
  // 创建标签组
  createTagGroup: (data) => request.post('/api/tags/groups', data),
  
  // 更新标签组
  updateTagGroup: (groupId, data) => request.put(`/api/tags/groups/${groupId}`, data),
  
  // 删除标签组
  deleteTagGroup: (groupId) => request.delete(`/api/tags/groups/${groupId}`),
  
  // 获取标签组内的标签
  getTagsByGroup: (groupId) => request.get(`/api/tags/groups/${groupId}/tags`),
  
  // 添加标签到标签组
  addTagToGroup: (groupId, data) => request.post(`/api/tags/groups/${groupId}/tags`, data),
  
  // 更新标签
  updateTag: (tagId, data) => request.put(`/api/tags/${tagId}`, data),
  
  // 删除标签
  deleteTag: (tagId) => request.delete(`/api/tags/${tagId}`),
  
  // 获取情绪标签列表
  getEmotionTags: () => request.get('/api/tags/emotions'),
  
  // 创建情绪标签
  createEmotionTag: (data) => request.post('/api/tags/emotions', data),
  
  // 更新情绪标签
  updateEmotionTag: (tagId, data) => request.put(`/api/tags/emotions/${tagId}`, data),
  
  // 删除情绪标签
  deleteEmotionTag: (tagId) => request.delete(`/api/tags/emotions/${tagId}`),
  
  // 同步情绪标签到 YAML
  syncEmotionsToYaml: () => request.post('/api/tags/emotions/sync')
}

// 许可证相关 API
export const licenseApi = {
  // 获取许可证状态
  getStatus: () => request.get('/api/license/status'),

  // 激活许可证
  activate: (activationCode) => request.post('/api/license/activate', { activation_code: activationCode }),

  // 检查配额
  checkQuota: () => request.get('/api/license/quota'),

  // 消耗配额
  consumeQuota: () => request.post('/api/license/quota/consume')
}

// 智能裁剪相关 API
export const smartCutApi = {
  // 上传视频
  upload: (formData) => request.post('/api/smart-cut/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  }),

  // 创建裁剪任务
  createTask: (data) => request.post('/api/smart-cut/tasks', data),

  // 获取任务状态
  getTask: (taskId) => request.get(`/api/smart-cut/tasks/${taskId}`),

  // 获取片段列表
  getSegments: (taskId) => request.get(`/api/smart-cut/tasks/${taskId}/segments`),

  // 提取音频
  extractAudio: (data) => request.post('/api/smart-cut/extract-audio', data),

  // 合成视频
  merge: (data) => request.post('/api/smart-cut/merge', data),

  // 删除任务
  deleteTask: (taskId) => request.delete(`/api/smart-cut/tasks/${taskId}`),

  // 获取历史记录列表
  getHistory: () => request.get('/api/smart-cut/history'),

  // 保存到素材库
  saveToMaterial: (data) => request.post('/api/smart-cut/save-to-material', data),

  // 获取合成视频列表
  getMergedVideos: () => request.get('/api/smart-cut/merged-videos'),

  // 删除合成视频
  deleteMergedVideo: (filename) => request.delete(`/api/smart-cut/merged-videos/${filename}`)
}

// 音视频剪辑相关 API
export const mediaClipApi = {
  // 健康检查
  health: () => request.get('/api/media-clip/health'),

  // 获取媒体信息
  getInfo: (data) => request.post('/api/media-clip/info', data),

  // 剪辑媒体（按时间）
  clip: (data) => request.post('/api/media-clip/clip', data),

  // 剪辑媒体（按帧，视频专用）
  clipByFrame: (data) => request.post('/api/media-clip/clip-by-frame', data),

  // 获取音频波形
  getWaveform: (data) => request.post('/api/media-clip/waveform', data),

  // 获取视频音频波形
  getVideoWaveform: (data) => request.post('/api/media-clip/video/waveform', data)
}

// 导出便捷方法
export const login = (username, password) => authApi.login(username, password)
export const register = (username, email, password) => authApi.register(username, email, password)

export default {
  auth: authApi,
  task: taskApi,
  material: materialApi,
  settings: settingsApi,
  functions: functionsApi,
  tag: tagApi,
  services: servicesApi,
  system: systemApi,
  license: licenseApi,
  smartCut: smartCutApi,
  mediaClip: mediaClipApi
}