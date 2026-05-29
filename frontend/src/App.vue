<template>
  <div id="app" :class="{ 'dark-theme': isDarkTheme }">
    <!-- 启动等待页面 -->
    <div v-if="!isBackendReady" class="loading-screen" :class="{ 'dark-theme': isDarkTheme }">
      <div class="loading-content">
        <div class="loading-logo">
          <svg class="logo-icon" viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect width="40" height="40" rx="8" fill="url(#logoGrad)"/>
            <path d="M12 14L20 10L28 14V26L20 30L12 26V14Z" stroke="white" stroke-width="2" fill="none"/>
            <circle cx="20" cy="20" r="4" fill="white"/>
            <defs>
              <linearGradient id="logoGrad" x1="0" y1="0" x2="40" y2="40">
                <stop stop-color="#00d9ff"/>
                <stop offset="1" stop-color="#00ff88"/>
              </linearGradient>
            </defs>
          </svg>
        </div>
        <h1 class="loading-title">AUTO<span class="highlight">Avantar</span></h1>
        <div class="loading-spinner">
          <el-icon class="is-loading" :size="32">
            <Loading />
          </el-icon>
        </div>
        <p class="loading-text">{{ loadingMessage }}</p>
        <p class="loading-hint" v-if="loadingHint">{{ loadingHint }}</p>
      </div>
    </div>

    <!-- 主应用界面 -->
    <el-container v-else class="layout-container">
      <!-- 主内容区 -->
      <el-container class="main-container">
        <!-- 顶部导航 -->
        <el-header class="header">
          <div class="header-left">
            <div class="logo" @click="toggleTheme" title="点击切换主题">
              <svg class="logo-icon" viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
                <rect width="40" height="40" rx="8" fill="url(#logoGrad)"/>
                <path d="M12 14L20 10L28 14V26L20 30L12 26V14Z" stroke="white" stroke-width="2" fill="none"/>
                <circle cx="20" cy="20" r="4" fill="white"/>
                <defs>
                  <linearGradient id="logoGrad" x1="0" y1="0" x2="40" y2="40">
                    <stop stop-color="#00d9ff"/>
                    <stop offset="1" stop-color="#00ff88"/>
                  </linearGradient>
                </defs>
              </svg>
              <span class="logo-text">AUTO<span class="highlight">Avantar</span></span>
            </div>
          </div>
          <div class="header-right">
            <!-- 统一导航 -->
            <nav class="nav-links">
              <router-link
                v-for="item in navItems"
                :key="item.route"
                :to="item.route"
                class="nav-link"
                :class="{ 'is-active': currentRoute === item.name }"
              >
                <el-icon><component :is="item.icon" /></el-icon>
                {{ item.label }}
              </router-link>
            </nav>

            <!-- 主题切换图标 -->
            <el-button
              circle
              class="theme-toggle-btn"
              @click="toggleTheme"
              :title="isDarkTheme ? '切换到亮色主题' : '切换到暗色主题'"
            >
              <el-icon>
                <Sunny v-if="isDarkTheme" />
                <Moon v-else />
              </el-icon>
            </el-button>

            <el-badge :value="pendingTasks" class="task-badge" v-if="pendingTasks > 0">
              <el-icon size="20"><Bell /></el-icon>
            </el-badge>
          </div>
        </el-header>

        <!-- 内容区域 -->
        <el-main class="main-content">
          <router-view v-slot="{ Component }">
            <transition name="fade-transform" mode="out-in">
              <component :is="Component" />
            </transition>
          </router-view>
        </el-main>

        <!-- 页脚 -->
        <el-footer class="footer">
          <span>© 2025 AUTOavantar - 数字人视频生成系统</span>
        </el-footer>
      </el-container>
    </el-container>

    <!-- CUDA 警告弹窗 -->
    <CUDAWarningDialog
      v-model="showCUDAWarning"
      :message="cudaWarningMessage"
      :gpu-info="cudaInfo"
      @close="handleCUDAWarningClose"
    />

    <!-- 版本更新弹窗 -->
    <UpdateDialog
      v-model="showUpdateDialog"
      :local-version="localVersion"
      :remote-version="remoteVersion"
      @update="handleUpdate"
      @defer="handleDeferUpdate"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, provide, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useTaskStore } from '@/stores/taskStore'
import { wsManager } from '@/utils/websocket'
import websocketService from '@/services/websocket'
import { settingsApi } from '@/services/api'
import { ElMessage } from 'element-plus'
import { Collection, Setting, HomeFilled, Bell, Sunny, Moon, Loading, Scissor } from '@element-plus/icons-vue'
import CUDAWarningDialog from '@/components/CUDAWarningDialog.vue'
import UpdateDialog from '@/components/UpdateDialog.vue'

const route = useRoute()
const taskStore = useTaskStore()

// 统一导航项
const navItems = [
  { name: 'Dashboard', route: '/', label: '首页', icon: HomeFilled },
  { name: 'SmartCut', route: '/smart-cut', label: '智能裁剪', icon: Scissor },
  { name: 'Materials', route: '/materials', label: '素材库', icon: Collection },
  { name: 'Settings', route: '/settings', label: '设置', icon: Setting },
]

// 后端就绪状态
const isBackendReady = ref(false)
const loadingMessage = ref('系统启动中...')
const loadingHint = ref('')

// CUDA 检测状态
const showCUDAWarning = ref(false)
const cudaWarningMessage = ref('')
const cudaInfo = ref(null)

// 版本更新状态
const showUpdateDialog = ref(false)
const localVersion = ref('1.0.0')
const remoteVersion = ref('1.0.0')

// 检查后端是否就绪
const checkBackendReady = async () => {
  try {
    const response = await fetch('/api/health')
    if (response.ok) {
      isBackendReady.value = true
      loadingMessage.value = '系统就绪'
      return true
    }
  } catch (error) {
    // 后端未就绪
  }
  return false
}

// 检测 CUDA 状态
const checkCUDAStatus = async () => {
  try {
    const response = await fetch('/api/system/cuda-status')
    const data = await response.json()
    if (!data.is_supported) {
      cudaWarningMessage.value = data.message
      cudaInfo.value = data
      showCUDAWarning.value = true
    }
    console.log('CUDA 检测结果:', data)
  } catch (error) {
    console.error('CUDA 检测失败:', error)
  }
}

// 检测版本更新
const checkVersionUpdate = async () => {
  try {
    const response = await fetch('/api/system/version')
    const data = await response.json()
    localVersion.value = data.local_version
    remoteVersion.value = data.remote_version || data.local_version
    if (data.has_update) {
      showUpdateDialog.value = true
    }
    console.log('版本检测结果:', data)
  } catch (error) {
    console.error('版本检测失败:', error)
  }
}

// 处理 CUDA 警告关闭
const handleCUDAWarningClose = () => {
  showCUDAWarning.value = false
}

// 处理更新
const handleUpdate = async () => {
  try {
    const response = await fetch('/api/system/update', { method: 'POST' })
    const data = await response.json()
    if (data.success) {
      ElMessage.success('更新已启动，系统将在 3 秒后自动退出')
      // 系统会自动退出，前端只需显示提示
      // 不需要手动关闭窗口，后端会发送 SIGTERM 退出进程
    }
  } catch (error) {
    console.error('触发更新失败:', error)
    ElMessage.error('更新失败，请稍后重试')
  }
}

// 处理稍后更新
const handleDeferUpdate = () => {
  showUpdateDialog.value = false
}

// 等待后端就绪
const waitForBackend = async () => {
  const maxAttempts = 120 // 最多等待 2 分钟
  let attempts = 0

  while (!isBackendReady.value && attempts < maxAttempts) {
    attempts++
    loadingMessage.value = `系统启动中... (${attempts}s)`

    if (attempts > 10) {
      loadingHint.value = '引擎正在加载中，请耐心等待'
    }
    if (attempts > 30) {
      loadingHint.value = '首次启动可能需要较长时间，请继续等待'
    }

    await checkBackendReady()

    if (!isBackendReady.value) {
      await new Promise(resolve => setTimeout(resolve, 1000))
    }
  }

  if (!isBackendReady.value) {
    loadingMessage.value = '启动超时，请刷新页面重试'
    loadingHint.value = '如果问题持续，请检查后端日志'
  }
}

const pendingTasks = computed(() => taskStore.pendingCount)

const currentRoute = computed(() => {
  return route.name || ''
})

const isDarkTheme = ref(false)

const prefersDarkScheme = window.matchMedia('(prefers-color-scheme: dark)')

// 从后端加载主题设置
const loadThemeFromServer = async () => {
  try {
    const response = await settingsApi.getTheme()
    if (response.code === 200 && response.data?.theme) {
      isDarkTheme.value = response.data.theme === 'dark'
      console.log('从服务器加载主题:', response.data.theme)
    }
  } catch (error) {
    console.error('加载主题设置失败:', error)
    // 失败时使用 localStorage 或系统偏好
    const savedTheme = localStorage.getItem('theme')
    if (savedTheme) {
      isDarkTheme.value = savedTheme === 'dark'
    } else {
      isDarkTheme.value = prefersDarkScheme.matches
    }
  }
}

const toggleTheme = async () => {
  isDarkTheme.value = !isDarkTheme.value
  const theme = isDarkTheme.value ? 'dark' : 'light'

  // 保存到 localStorage 作为备份
  localStorage.setItem('theme', theme)

  // 保存到后端
  try {
    await settingsApi.updateTheme(theme)
    console.log('主题已保存到服务器:', theme)
  } catch (error) {
    console.error('保存主题设置失败:', error)
  }
}

watch(isDarkTheme, (newValue) => {
  if (newValue) {
    document.body.classList.add('dark-theme')
    console.log('Body dark-theme class added')
  } else {
    document.body.classList.remove('dark-theme')
    console.log('Body dark-theme class removed')
  }
  console.log('Current body classes:', document.body.className)
}, { immediate: true })

provide('isDarkTheme', isDarkTheme)
provide('toggleTheme', toggleTheme)

let unsubscribeStatus = null
let unsubscribeCompleted = null
let unsubscribeFailed = null

const setupWebSocketListeners = () => {
  unsubscribeStatus = websocketService.onStatusUpdate((message) => {
    console.log('[App] 收到状态更新:', message)
    taskStore.updateTaskFromWebSocket(message)
  })

  unsubscribeCompleted = websocketService.onCompleted((message) => {
    console.log('[App] 任务完成:', message)
    taskStore.updateTaskFromWebSocket({
      task_id: message.task_id,
      status: 'completed',
      progress: 100,
      output_path: message.output_path
    })
    const task = taskStore.tasks.find(t => t.task_id === message.task_id)
    ElMessage.success(`任务 ${task?.name || message.task_id} 已完成`)
  })

  unsubscribeFailed = websocketService.onFailed((message) => {
    console.log('[App] 任务失败:', message)
    taskStore.updateTaskFromWebSocket({
      task_id: message.task_id,
      status: 'failed',
      error_message: message.error_message || message.message
    })
    const task = taskStore.tasks.find(t => t.task_id === message.task_id)
    ElMessage.error(`任务 ${task?.name || message.task_id} 失败`)
  })
}

const connectToRunningTasks = async () => {
  const runningTasks = taskStore.tasks.filter(t => 
    ['pending', 'processing', 'running', 'queued'].includes(t.status)
  )
  
  console.log('[App] 连接运行中的任务:', runningTasks.map(t => t.task_id))
  
  for (const task of runningTasks) {
    try {
      await websocketService.connect(task.task_id)
      console.log(`[App] 已连接任务 ${task.task_id}`)
    } catch (error) {
      console.error(`[App] 连接任务 ${task.task_id} WebSocket 失败:`, error)
    }
  }
}

onMounted(async () => {
  // 先等待后端就绪
  await waitForBackend()

  if (!isBackendReady.value) {
    return // 启动超时，不继续初始化
  }

  // 加载主题设置（必须先完成）
  await loadThemeFromServer()

  prefersDarkScheme.addEventListener('change', (e) => {
    if (!localStorage.getItem('theme')) {
      isDarkTheme.value = e.matches
    }
  })

  // 初始化 WebSocket 可见性处理器
  websocketService.initVisibilityHandler()

  setupWebSocketListeners()

  await taskStore.fetchTasks()

  await connectToRunningTasks()

  taskStore.startPolling()

  console.log('[App] WebSocket 监听器已设置')

  // 后台执行 CUDA 和版本检测（不阻塞 UI 渲染）
  // 使用 setTimeout 确保在下一个事件循环中执行
  setTimeout(() => {
    checkCUDAStatus()
    checkVersionUpdate()
  }, 100)
})

onUnmounted(() => {
  if (unsubscribeStatus) unsubscribeStatus()
  if (unsubscribeCompleted) unsubscribeCompleted()
  if (unsubscribeFailed) unsubscribeFailed()
  
  taskStore.stopPolling()
  
  console.log('[App] 组件卸载，但保持 WebSocket 连接')
})
</script>

<style scoped>
/* 启动等待页面样式 */
.loading-screen {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-page-gradient);
  z-index: var(--z-loading);
}

.dark-theme.loading-screen {
  background: var(--bg-page-gradient);
}

.loading-content {
  text-align: center;
}

.loading-logo {
  margin-bottom: 24px;
}

.loading-logo .logo-icon {
  width: 80px;
  height: 80px;
  animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% {
    transform: scale(1);
    opacity: 1;
  }
  50% {
    transform: scale(1.05);
    opacity: 0.8;
  }
}

.loading-title {
  font-size: var(--font-size-5xl);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin-bottom: var(--space-2xl);
}

.dark-theme .loading-title {
  color: var(--color-text-primary);
}

.loading-title .highlight {
  background: var(--brand-gradient);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.loading-spinner {
  margin-bottom: var(--space-xl);
  color: var(--color-primary);
}

.dark-theme .loading-spinner {
  color: var(--color-primary);
}

.loading-text {
  font-size: var(--font-size-lg);
  color: var(--color-text-regular);
  margin-bottom: var(--space-sm);
}

.dark-theme .loading-text {
  color: var(--color-text-regular);
}

.loading-hint {
  font-size: var(--font-size-base);
  color: var(--color-text-secondary);
}

.dark-theme .loading-hint {
  color: var(--color-text-secondary);
}

.layout-container {
  min-height: 100vh;
}

.logo {
  display: flex;
  align-items: center;
  cursor: pointer;
  transition: opacity var(--transition-normal);
}

.logo:hover {
  opacity: 0.8;
}

.logo-icon {
  width: 40px;
  height: 40px;
  margin-right: var(--space-md);
}

.logo-text {
  color: var(--color-text-primary);
  font-size: var(--font-size-2xl);
  font-weight: var(--font-weight-semibold);
  white-space: nowrap;
}

.logo-text .highlight {
  background: var(--brand-gradient);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.main-container {
  background-color: var(--bg-page);
  transition: background-color var(--transition-normal);
}

.header {
  background-color: var(--bg-card-solid);
  box-shadow: var(--shadow-md);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--space-3xl);
  height: var(--header-height);
  transition: background-color var(--transition-normal), box-shadow var(--transition-normal);
}

.header-right {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}

.nav-links {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
}

.nav-link {
  display: inline-flex;
  align-items: center;
  gap: var(--space-xs);
  padding: var(--space-sm) var(--space-md);
  border-radius: var(--radius-md);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-regular);
  text-decoration: none;
  transition: all var(--transition-fast);
  white-space: nowrap;
}

.nav-link:hover {
  color: var(--color-primary);
  background: var(--color-primary-bg);
}

.nav-link.is-active {
  color: var(--color-primary);
  background: var(--color-primary-bg);
  font-weight: var(--font-weight-semibold);
}

.theme-toggle-btn {
  margin-left: var(--space-sm);
}

.task-badge {
  cursor: pointer;
  margin-left: var(--space-sm);
}

.main-content {
  padding: var(--space-lg);
  overflow-y: auto;
  min-height: calc(100vh - var(--header-height) - var(--footer-height));
}

.footer {
  background-color: var(--bg-card-solid);
  text-align: center;
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
  line-height: var(--footer-height);
  border-top: 1px solid var(--color-border-strong);
  transition: background-color var(--transition-normal), border-color var(--transition-normal);
}

/* 暗色主题样式 */
.dark-theme .main-container {
  background-color: var(--bg-page);
}

.dark-theme .header {
  background-color: var(--bg-card-solid);
  box-shadow: var(--shadow-md);
}

.dark-theme .logo-text {
  color: var(--color-text-primary);
}

.dark-theme .footer {
  background-color: var(--bg-card-solid);
  color: var(--color-text-regular);
  border-top-color: var(--color-border-strong);
}

/* 暗色主题下的Element Plus对话框样式 */
body.dark-theme .el-dialog {
  background: #1a1f26 !important;
  border: 1px solid rgba(255, 255, 255, 0.1) !important;
  color: rgba(255, 255, 255, 0.8) !important;
}

body.dark-theme .el-dialog__header {
  border-bottom: 1px solid rgba(255, 255, 255, 0.1) !important;
  background: #1a1f26 !important;
}

body.dark-theme .el-dialog__title {
  color: #fff !important;
}

body.dark-theme .el-dialog__body {
  background: #1a1f26 !important;
  color: rgba(255, 255, 255, 0.8) !important;
}

body.dark-theme .el-dialog__footer {
  border-top: 1px solid rgba(255, 255, 255, 0.1) !important;
  background: #1a1f26 !important;
}

/* 路由过渡动画 */
.fade-transform-enter-active,
.fade-transform-leave-active {
  transition: all 0.3s ease;
}

.fade-transform-enter-from {
  opacity: 0;
  transform: translateX(-20px);
}

.fade-transform-leave-to {
  opacity: 0;
  transform: translateX(20px);
}
</style>

<!-- 全局样式 -->
<style>
/* 暗色主题下的Element Plus对话框样式 - 全局 */
body.dark-theme .el-dialog {
  background: #1a1f26 !important;
  border: 1px solid rgba(255, 255, 255, 0.1) !important;
  color: rgba(255, 255, 255, 0.8) !important;
}

body.dark-theme .el-dialog__header {
  border-bottom: 1px solid rgba(255, 255, 255, 0.1) !important;
  background: #1a1f26 !important;
}

body.dark-theme .el-dialog__title {
  color: #fff !important;
}

body.dark-theme .el-dialog__body {
  background: #1a1f26 !important;
  color: rgba(255, 255, 255, 0.8) !important;
}

body.dark-theme .el-dialog__footer {
  border-top: 1px solid rgba(255, 255, 255, 0.1) !important;
  background: #1a1f26 !important;
}
</style>
