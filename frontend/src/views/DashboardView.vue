<template>
  <div class="dashboard-container" :class="{ 'dark-theme': isDarkTheme }">
    <div class="dashboard-content">
      <div class="action-buttons-row">
        <button class="action-button create-btn" @click="createTask">
          <div class="btn-icon">
            <el-icon><Plus /></el-icon>
          </div>
          <div class="btn-content">
            <span class="btn-title">新建任务</span>
            <span class="btn-desc">创建数字人视频生成任务</span>
          </div>
          <div class="btn-arrow">
            <el-icon><ArrowRight /></el-icon>
          </div>
        </button>
        
        <button class="action-button run-btn" @click="runAllPending">
          <div class="btn-icon">
            <el-icon><VideoPlay /></el-icon>
          </div>
          <div class="btn-content">
            <span class="btn-title">运行任务</span>
            <span class="btn-desc">执行所有等待中的任务</span>
          </div>
          <div class="btn-arrow">
            <el-icon><ArrowRight /></el-icon>
          </div>
        </button>
      </div>

      <div class="pending-panel">
        <div class="panel-header">
          <h4><el-icon><Clock /></el-icon> 等待运行</h4>
          <span class="count-badge">{{ pendingTasks.length }}</span>
        </div>
        <div class="pending-grid" v-if="pendingTasks.length > 0">
          <div
            v-for="task in pendingTasks"
            :key="task.task_id"
            class="pending-card"
          >
            <div class="pending-header">
              <span class="task-name">{{ task.name }}</span>
              <span class="task-time">{{ formatTime(task.created_at) }}</span>
            </div>
            <div class="pending-actions">
              <el-button type="success" size="small" @click="startTask(task)">
                <el-icon><VideoPlay /></el-icon>
                开始
              </el-button>
              <el-button type="danger" size="small" plain @click="deleteTask(task)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
          </div>
        </div>
        <el-empty v-else description="暂无等待任务" :image-size="60" />
      </div>

      <div class="section-middle" v-if="activeTasks.length > 0">
        <div class="panel-header">
          <h4><el-icon class="pulse"><Loading /></el-icon> 运行中</h4>
          <span class="count-badge running">{{ activeTasks.length }}</span>
        </div>
        <div class="running-grid">
          <div 
            v-for="task in activeTasks" 
            :key="task.task_id"
            class="running-card"
            :class="{ 'queued-card': task.status === 'queued' }"
          >
            <div class="running-header">
              <span class="task-name">{{ task.name }}</span>
              <el-tag size="small" :type="task.status === 'queued' ? 'info' : 'warning'" effect="dark">
                {{ task.status === 'queued' ? '等待中' : (task.current_stage || '处理中') }}
              </el-tag>
            </div>
            <div class="progress-section" v-if="task.status !== 'queued'">
              <el-progress 
                :percentage="Math.round(task.progress || 0)"
                :stroke-width="8"
                :striped="true"
                :striped-flow="true"
                status="success"
              />
              <span class="progress-text">{{ Math.round(task.progress || 0) }}%</span>
            </div>
            <div class="queued-info" v-else>
              <span class="queued-text">任务已提交，等待执行...</span>
            </div>
            <div class="running-actions">
              <el-button type="danger" size="small" plain @click="cancelTask(task)">
                <el-icon><Close /></el-icon>
                取消
              </el-button>
              <el-button type="primary" size="small" plain @click="priorityTask(task)" v-if="task.status === 'queued'">
                <el-icon><Top /></el-icon>
                插队
              </el-button>
            </div>
          </div>
        </div>
      </div>

      <div class="section-bottom">
        <div class="panel-header">
          <h4><el-icon><CircleCheck /></el-icon> 已完成</h4>
          <span class="count-badge completed">{{ allCompletedItems.length }}</span>
        </div>
        <div class="completed-grid" v-if="allCompletedItems.length > 0">
          <div
            v-for="item in allCompletedItems"
            :key="item._key"
            class="completed-card"
            :class="{ 'has-error': item._type === 'task' && item.status === 'failed' }"
          >
            <div class="card-thumbnail">
              <video v-if="item._videoPath" :src="getVideoUrl(item._videoPath)" muted @mouseenter="hoverVideo" @mouseleave="leaveVideo" />
              <div v-else class="error-placeholder">
                <el-icon><Warning /></el-icon>
                <span>生成失败</span>
              </div>
              <div class="card-overlay">
                <el-button type="primary" circle @click="previewItem(item)">
                  <el-icon><VideoPlay /></el-icon>
                </el-button>
              </div>
            </div>
            <div class="card-info">
              <span class="card-name">{{ item._name }}</span>
              <div class="card-meta">
                <el-tag v-if="item._type === 'merged'" size="small" type="info">合成</el-tag>
                <el-tag v-else-if="item.status === 'completed'" size="small" type="success">已完成</el-tag>
                <el-tag v-else size="small" type="danger">失败</el-tag>
                <span class="card-time">{{ formatTime(item._time) }}</span>
              </div>
            </div>
            <div class="card-actions">
              <el-button type="success" size="small" circle @click="downloadItem(item)" :disabled="!item._videoPath">
                <el-icon><Download /></el-icon>
              </el-button>
              <el-button type="danger" size="small" circle @click="deleteItem(item)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
          </div>
        </div>
        <el-empty v-else description="暂无已完成任务" :image-size="80" />
      </div>
    </div>

    <el-dialog v-model="showPreview" title="视频预览" width="800px" center @close="closePreview">
      <div class="preview-container">
        <video 
          ref="previewVideoRef"
          v-if="previewUrl" 
          :src="previewUrl" 
          controls 
          autoplay 
          class="preview-video"
        />
      </div>
    </el-dialog>

  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, inject } from 'vue'
import { useRouter } from 'vue-router'
import { useTaskStore } from '@/stores/taskStore'
import { taskApi, functionsApi, smartCutApi } from '@/services/api'
import { ElMessage } from 'element-plus'
import websocketService from '@/services/websocket'

const isDarkTheme = inject('isDarkTheme', ref(false))

const router = useRouter()
const taskStore = useTaskStore()

const showPreview = ref(false)
const previewUrl = ref('')
const previewVideoRef = ref(null)

const allTasks = computed(() => taskStore.tasks)

const pendingTasks = computed(() => 
  allTasks.value.filter(t => t.status === 'pending')
)

const queuedTasks = computed(() => 
  allTasks.value.filter(t => t.status === 'queued')
)

const runningTasks = computed(() =>
  allTasks.value.filter(t => t.status === 'processing' || t.status === 'running')
)

// 运行中任务排在最顶部，排队任务按优先级向下排序
const activeTasks = computed(() => {
  // 运行中的任务排在最顶部
  const running = runningTasks.value

  // 排队任务按优先级排序（插队任务在前）
  const queued = [...queuedTasks.value].sort((a, b) => {
    // 有 is_priority 标记的排在前面
    if (a.is_priority && !b.is_priority) return -1
    if (!a.is_priority && b.is_priority) return 1
    // 都没有或都有时按创建时间排序
    return new Date(a.created_at) - new Date(b.created_at)
  })

  return [...running, ...queued]
})

const completedTasks = computed(() =>
  allTasks.value.filter(t => t.status === 'completed' || t.status === 'failed')
)

// 合成视频
const mergedVideos = ref([])

// 合并后的已完成列表：任务 + 合成视频，按时间倒序
// 去重：主流程输出也保存在 output 目录，mergedVideos 会扫描到它，需排除
const allCompletedItems = computed(() => {
  const taskItems = completedTasks.value.map(task => ({
    _key: task.task_id,
    _type: 'task',
    _name: task.name,
    _videoPath: task.output_path && task.status !== 'failed' ? task.output_path : '',
    _time: task.completed_at || task.updated_at,
    status: task.status,
    task_id: task.task_id,
    output_path: task.output_path,
  }))

  // 收集已完成任务的 output_path，用于去重
  // 统一使用相对路径格式（output/xxx.mp4）进行比较，确保跨数据源去重有效
  const normalizePath = (p) => {
    if (!p) return ''
    const normalized = p.replace(/\\/g, '/')
    // 如果是绝对路径，提取 output/ 部分
    if (normalized.includes('output/')) {
      return normalized.substring(normalized.lastIndexOf('output/'))
    }
    return normalized
  }
  const taskOutputPaths = new Set(
    completedTasks.value
      .filter(t => t.output_path && t.status !== 'failed')
      .map(t => normalizePath(t.output_path))
  )

  const mergedItems = mergedVideos.value
    .filter(video => !taskOutputPaths.has(normalizePath(video.path)))
    .map(video => ({
      _key: video.path,
      _type: 'merged',
      _name: video.name,
      _videoPath: video.path,
      _time: video.created_at,
      path: video.path,
    }))

  return [...taskItems, ...mergedItems].sort((a, b) => {
    const timeA = a._time ? new Date(a._time).getTime() : 0
    const timeB = b._time ? new Date(b._time).getTime() : 0
    return timeB - timeA
  })
})

const fetchTasks = async () => {
  try {
    await taskStore.fetchTasks()
  } catch (error) {
    console.error('获取任务列表失败:', error)
  }
}

const createTask = () => {
  router.push('/tasks/create')
}

const runAllPending = async () => {
  if (pendingTasks.value.length === 0) {
    ElMessage.warning('暂无等待运行的任务')
    return
  }
  
  try {
    for (const task of pendingTasks.value) {
      await taskApi.control(task.task_id, 'start')
      try {
        await websocketService.connect(task.task_id)
      } catch (error) {
        console.error(`连接任务 ${task.task_id} WebSocket 失败:`, error)
      }
    }
    
    ElMessage.success('任务已开始运行')
    await fetchTasks()
  } catch (error) {
    ElMessage.error('操作失败: ' + (error.response?.data?.detail || error.message || '未知错误'))
  }
}

const startTask = async (task) => {
  try {
    await taskApi.control(task.task_id, 'start')
    ElMessage.success('任务已开始')
    await taskStore.fetchTasks()
    try {
      await websocketService.connect(task.task_id)
    } catch (error) {
      console.error(`连接任务 ${task.task_id} WebSocket 失败:`, error)
    }
  } catch (error) {
    ElMessage.error('启动失败: ' + (error.response?.data?.detail || error.message || '未知错误'))
  }
}

const cancelTask = async (task) => {
  try {
    // 先断开 WebSocket 连接，防止后续消息覆盖取消状态
    websocketService.disconnect(task.task_id)
    await taskApi.control(task.task_id, 'cancel')
    ElMessage.success('任务已取消')
    await fetchTasks()
  } catch (error) {
    ElMessage.error('操作失败: ' + (error.response?.data?.detail || error.message || '未知错误'))
  }
}

const priorityTask = async (task) => {
  try {
    await taskApi.control(task.task_id, 'priority')
    ElMessage.success('任务已置顶')
    await fetchTasks()
  } catch (error) {
    ElMessage.error('操作失败: ' + (error.response?.data?.detail || error.message || '未知错误'))
  }
}

const deleteTask = async (task) => {
  try {
    await taskApi.delete(task.task_id)
    ElMessage.success('删除成功')
    await fetchTasks()
  } catch (error) {
    ElMessage.error('删除失败: ' + (error.response?.data?.detail || error.message || '未知错误'))
  }
}

const previewItem = (item) => {
  if (item._videoPath) {
    previewUrl.value = getVideoUrl(item._videoPath)
    showPreview.value = true
  }
}

const closePreview = () => {
  if (previewVideoRef.value) {
    previewVideoRef.value.pause()
    previewVideoRef.value.currentTime = 0
  }
  previewUrl.value = ''
}

const downloadItem = async (item) => {
  try {
    await functionsApi.openOutputDir()
    ElMessage.success('输出目录已打开')
  } catch (error) {
    ElMessage.error('打开输出目录失败: ' + (error.message || '未知错误'))
  }
}

const deleteItem = async (item) => {
  try {
    if (item._type === 'merged') {
      const filename = item.path.split('/').pop()
      const res = await smartCutApi.deleteMergedVideo(filename)
      if (res.code === 200) {
        ElMessage.success('删除成功')
        await fetchMergedVideos()
      } else {
        ElMessage.error(res.message || '删除失败')
      }
    } else {
      await taskApi.delete(item.task_id)
      ElMessage.success('删除成功')
      await fetchTasks()
    }
  } catch (error) {
    ElMessage.error('删除失败: ' + (error.response?.data?.detail || error.message || '未知错误'))
  }
}

const getVideoUrl = (path) => {
  if (!path) return ''
  if (path.startsWith('http')) return path
  return `/files/${path.replace(/\\/g, '/')}`
}

const formatTime = (timeStr) => {
  if (!timeStr) return ''
  const date = new Date(timeStr)
  const now = new Date()
  const diff = now - date
  
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)}分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}小时前`
  return date.toLocaleDateString('zh-CN')
}

const hoverVideo = (e) => {
  e.target.play()
}

const leaveVideo = (e) => {
  e.target.pause()
  e.target.currentTime = 0
}

const fetchMergedVideos = async () => {
  try {
    const res = await smartCutApi.getMergedVideos()
    if (res.code === 200) {
      mergedVideos.value = res.data.videos || []
    }
  } catch (error) {
    console.error('获取合成视频列表失败:', error)
  }
}

onMounted(async () => {
  await fetchTasks()
  await fetchMergedVideos()
  taskStore.startPolling()
})

onUnmounted(() => {
  taskStore.stopPolling()
})
</script>

<style scoped>
.dashboard-container {
  min-height: calc(100vh - 64px - var(--space-3xl));
  background: var(--bg-page-gradient);
  padding: 0;
  transition: background var(--transition-normal);
}



.dashboard-content {
  padding: var(--space-lg);
}

.action-buttons-row {
  display: flex;
  gap: var(--space-lg);
  margin-bottom: var(--space-lg);
}

.action-button {
  flex: 1;
  display: flex;
  align-items: center;
  padding: var(--space-lg) 28px;
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.95), rgba(255, 255, 255, 0.85));
  border: 2px solid transparent;
  border-radius: var(--radius-xl);
  cursor: pointer;
  transition: all var(--transition-slow);
  box-shadow: var(--shadow-lg);
  position: relative;
  overflow: hidden;
}

.action-button::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: linear-gradient(135deg, transparent 0%, rgba(255, 255, 255, 0.2) 100%);
  opacity: 0;
  transition: opacity var(--transition-normal);
}

.action-button:hover::before {
  opacity: 1;
}

.dark-theme .action-button {
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.08), rgba(255, 255, 255, 0.04));
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
}

.action-button:hover {
  transform: translateY(-4px);
  box-shadow: var(--shadow-xl);
}

.dark-theme .action-button:hover {
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.5);
}

.create-btn {
  border-color: rgba(64, 158, 255, 0.3);
}

.create-btn:hover {
  border-color: rgba(64, 158, 255, 0.6);
  box-shadow: 0 12px 32px rgba(64, 158, 255, 0.2);
}

.dark-theme .create-btn {
  border-color: rgba(0, 217, 255, 0.3);
}

.dark-theme .create-btn:hover {
  border-color: rgba(0, 217, 255, 0.6);
  box-shadow: 0 12px 32px rgba(0, 217, 255, 0.25);
}

.run-btn {
  border-color: rgba(103, 194, 58, 0.3);
}

.run-btn:hover {
  border-color: rgba(103, 194, 58, 0.6);
  box-shadow: 0 12px 32px rgba(103, 194, 58, 0.2);
}

.dark-theme .run-btn {
  border-color: rgba(0, 255, 136, 0.3);
}

.dark-theme .run-btn:hover {
  border-color: rgba(0, 255, 136, 0.6);
  box-shadow: 0 12px 32px rgba(0, 255, 136, 0.25);
}

.btn-icon {
  width: 52px;
  height: 52px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-right: var(--space-xl);
  transition: all var(--transition-normal);
}

.create-btn .btn-icon {
  background: linear-gradient(135deg, rgba(64, 158, 255, 0.15), rgba(64, 158, 255, 0.05));
}

.dark-theme .create-btn .btn-icon {
  background: linear-gradient(135deg, rgba(0, 217, 255, 0.2), rgba(0, 217, 255, 0.05));
}

.run-btn .btn-icon {
  background: linear-gradient(135deg, rgba(103, 194, 58, 0.15), rgba(103, 194, 58, 0.05));
}

.dark-theme .run-btn .btn-icon {
  background: linear-gradient(135deg, rgba(0, 255, 136, 0.2), rgba(0, 255, 136, 0.05));
}

.btn-icon .el-icon {
  font-size: var(--font-size-3xl);
  transition: all var(--transition-normal);
}

.create-btn .btn-icon .el-icon {
  color: var(--color-primary);
}

.dark-theme .create-btn .btn-icon .el-icon {
  color: var(--brand-color-start);
}

.run-btn .btn-icon .el-icon {
  color: var(--color-success);
}

.dark-theme .run-btn .btn-icon .el-icon {
  color: var(--brand-color-end);
}

.action-button:hover .btn-icon {
  transform: scale(1.1);
}

.btn-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-xs);
}

.btn-title {
  font-size: var(--font-size-xl);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  letter-spacing: 0.5px;
  transition: color var(--transition-normal);
}

.btn-desc {
  font-size: var(--font-size-md);
  color: rgba(0, 0, 0, 0.5);
  transition: color var(--transition-normal);
}

.dark-theme .btn-desc {
  color: rgba(255, 255, 255, 0.5);
}

.btn-arrow {
  opacity: 0;
  transform: translateX(calc(-1 * var(--space-sm)));
  transition: all var(--transition-normal);
}

.action-button:hover .btn-arrow {
  opacity: 1;
  transform: translateX(0);
}

.btn-arrow .el-icon {
  font-size: var(--font-size-2xl);
  transition: color var(--transition-normal);
}

.create-btn .btn-arrow .el-icon {
  color: var(--color-primary);
}

.dark-theme .create-btn .btn-arrow .el-icon {
  color: var(--brand-color-start);
}

.run-btn .btn-arrow .el-icon {
  color: var(--color-success);
}

.dark-theme .run-btn .btn-arrow .el-icon {
  color: var(--brand-color-end);
}

.pending-panel {
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-xl);
  padding: var(--space-lg);
  max-height: 320px;
  overflow-y: auto;
  box-shadow: var(--shadow-md);
  transition: all var(--transition-normal);
  margin-bottom: var(--space-lg);
}

.dark-theme .pending-panel {
  background: var(--bg-card);
  border-color: var(--color-border);
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.3);
}

.panel-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: var(--space-base);
}

.panel-header h4 {
  margin: 0;
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  transition: color var(--transition-normal);
}

.panel-header h4 .el-icon {
  font-size: var(--font-size-xl);
}

.panel-header h4 .pulse {
  animation: pulse 1.5s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.count-badge {
  background: var(--brand-gradient);
  color: var(--bg-card-solid);
  padding: 2px 10px;
  border-radius: var(--radius-lg);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
}

.dark-theme .count-badge {
  color: var(--bg-page);
}

.count-badge.running {
  background: linear-gradient(135deg, var(--color-warning), #ff9f43);
}

.dark-theme .count-badge.running {
  background: linear-gradient(135deg, #ff9f43, #ffc107);
}

.count-badge.completed {
  background: linear-gradient(135deg, var(--color-text-secondary), #a6a9ad);
}

.dark-theme .count-badge.completed {
  background: linear-gradient(135deg, #a29bfe, #6c5ce7);
}

.pending-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--space-md);
  margin-top: var(--space-base);
}

.pending-card {
  background: rgba(255, 255, 255, 0.6);
  border: 1px solid var(--color-border-light);
  border-radius: 10px;
  padding: 14px var(--space-base);
  transition: all 0.2s;
}

.dark-theme .pending-card {
  background: var(--bg-card);
  border-color: var(--color-border-light);
}

.pending-card:hover {
  background: rgba(255, 255, 255, 0.8);
  border-color: rgba(103, 194, 58, 0.3);
  box-shadow: 0 4px 12px rgba(103, 194, 58, 0.15);
}

.dark-theme .pending-card:hover {
  background: var(--bg-card-hover);
  border-color: rgba(0, 255, 136, 0.3);
  box-shadow: 0 4px 12px rgba(0, 255, 136, 0.15);
}

.pending-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.pending-header .task-name {
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 60%;
}

.pending-header .task-time {
  font-size: var(--font-size-sm);
  color: rgba(0, 0, 0, 0.4);
  flex-shrink: 0;
}

.dark-theme .pending-header .task-time {
  color: rgba(255, 255, 255, 0.4);
}

.pending-actions {
  display: flex;
  gap: var(--space-sm);
  justify-content: flex-end;
}

.task-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.task-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-md) var(--space-base);
  background: rgba(255, 255, 255, 0.6);
  border: 1px solid var(--color-border-light);
  border-radius: 10px;
  transition: all 0.2s;
}

.dark-theme .task-item {
  background: var(--bg-card);
  border-color: var(--color-border-light);
}

.task-item:hover {
  background: rgba(255, 255, 255, 0.8);
  border-color: var(--color-border);
}

.dark-theme .task-item:hover {
  background: var(--bg-card-hover);
  border-color: rgba(255, 255, 255, 0.1);
}

.task-info {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
}

.task-name {
  font-size: var(--font-size-base);
  color: var(--color-text-primary);
  font-weight: var(--font-weight-medium);
  transition: color var(--transition-normal);
}

.task-time {
  font-size: var(--font-size-sm);
  color: rgba(0, 0, 0, 0.4);
  transition: color var(--transition-normal);
}

.dark-theme .task-time {
  color: rgba(255, 255, 255, 0.4);
}

.task-actions {
  display: flex;
  gap: var(--space-sm);
}

.section-middle {
  margin-bottom: var(--space-2xl);
  padding: var(--space-lg);
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-md);
  transition: all var(--transition-normal);
}

.dark-theme .section-middle {
  background: var(--bg-card);
  border-color: var(--color-border);
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.3);
}

.running-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--space-lg);
  margin-top: var(--space-base);
}

.running-card {
  background: rgba(255, 255, 255, 0.6);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-base);
  transition: all var(--transition-normal);
}

.dark-theme .running-card {
  background: var(--bg-elevated);
  border-color: rgba(255, 255, 255, 0.1);
}

.running-card.queued-card {
  background: rgba(64, 158, 255, 0.08);
  border-color: rgba(64, 158, 255, 0.2);
}

.dark-theme .running-card.queued-card {
  background: rgba(0, 217, 255, 0.08);
  border-color: rgba(0, 217, 255, 0.2);
}

.queued-info {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-md) 0;
  margin-bottom: var(--space-md);
}

.queued-text {
  font-size: var(--font-size-base);
  color: var(--color-text-secondary);
}

.dark-theme .queued-text {
  color: var(--color-text-regular);
}

.running-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-md);
}

.running-header .task-name {
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}

.progress-section {
  display: flex;
  align-items: center;
  gap: var(--space-md);
  margin-bottom: var(--space-md);
}

.progress-section :deep(.el-progress) {
  flex: 1;
}

.progress-section :deep(.el-progress__text) {
  color: var(--color-primary) !important;
  font-weight: var(--font-weight-semibold);
}

.dark-theme .progress-section :deep(.el-progress__text) {
  color: var(--brand-color-start) !important;
}

.progress-text {
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-semibold);
  color: var(--color-primary);
  min-width: 45px;
  transition: color var(--transition-normal);
}

.dark-theme .progress-text {
  color: var(--brand-color-start);
}

.running-actions {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
}

.section-bottom {
  padding: var(--space-lg);
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-md);
  transition: all var(--transition-normal);
}

.dark-theme .section-bottom {
  background: var(--bg-card);
  border-color: var(--color-border);
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.3);
}

.completed-grid {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: var(--space-base);
  margin-top: var(--space-base);
}

.completed-card {
  background: rgba(255, 255, 255, 0.6);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  overflow: hidden;
  transition: all var(--transition-normal);
}

.dark-theme .completed-card {
  background: var(--bg-elevated);
  border-color: var(--color-border);
}

.completed-card:hover {
  transform: translateY(-4px);
  border-color: rgba(64, 158, 255, 0.3);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.15);
}

.dark-theme .completed-card:hover {
  border-color: rgba(0, 217, 255, 0.3);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
}

.completed-card.has-error {
  border-color: rgba(245, 108, 108, 0.3);
}

.dark-theme .completed-card.has-error {
  border-color: rgba(255, 82, 82, 0.3);
}

.completed-card.has-error:hover {
  border-color: rgba(245, 108, 108, 0.5);
  box-shadow: 0 8px 24px rgba(245, 108, 108, 0.2);
}

.dark-theme .completed-card.has-error:hover {
  border-color: rgba(255, 82, 82, 0.5);
  box-shadow: 0 8px 24px rgba(255, 82, 82, 0.2);
}

.card-thumbnail {
  position: relative;
  aspect-ratio: 16/9;
  background: var(--bg-muted);
  overflow: hidden;
  transition: background var(--transition-normal);
}

.card-thumbnail video {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.error-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-sm);
  color: rgba(0, 0, 0, 0.4);
  transition: color var(--transition-normal);
}

.dark-theme .error-placeholder {
  color: rgba(255, 255, 255, 0.4);
}

.error-placeholder .el-icon {
  font-size: var(--font-size-5xl);
  color: var(--color-danger);
}

.dark-theme .error-placeholder .el-icon {
  color: #ff5252;
}

.error-placeholder span {
  font-size: var(--font-size-xs);
}

.card-overlay {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: opacity 0.3s;
}

.dark-theme .card-overlay {
  background: rgba(0, 0, 0, 0.6);
}

.completed-card:hover .card-overlay {
  opacity: 1;
}

.card-overlay .el-button {
  width: var(--space-4xl);
  height: var(--space-4xl);
}

.card-info {
  padding: var(--space-md);
}

.card-name {
  display: block;
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-primary);
  margin-bottom: 6px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  transition: color var(--transition-normal);
}

.card-meta {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}

.card-time {
  font-size: var(--font-size-xs);
  color: rgba(0, 0, 0, 0.4);
  transition: color var(--transition-normal);
}

.dark-theme .card-time {
  color: rgba(255, 255, 255, 0.4);
}

.card-actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
  padding: 0 var(--space-md) var(--space-md);
}

.preview-container {
  display: flex;
  justify-content: center;
  background: #000;
  border-radius: 8px;
  overflow: hidden;
}

.preview-video {
  width: 100%;
  max-height: 450px;
}

.deerflow-badge {
  position: fixed;
  bottom: 20px;
  right: 20px;
  font-size: 12px;
  color: rgba(0, 0, 0, 0.3);
  text-decoration: none;
  transition: all 0.3s;
  z-index: 1000;
}

.dark-theme .deerflow-badge {
  color: rgba(255, 255, 255, 0.3);
}

.deerflow-badge:hover {
  color: #409EFF;
  text-shadow: 0 0 10px rgba(64, 158, 255, 0.5);
}

.dark-theme .deerflow-badge:hover {
  color: #00d9ff;
  text-shadow: 0 0 10px rgba(0, 217, 255, 0.5);
}

:deep(.el-empty__description) {
  color: rgba(0, 0, 0, 0.4);
  transition: color 0.3s ease;
}

.dark-theme :deep(.el-empty__description) {
  color: rgba(255, 255, 255, 0.4);
}

:deep(.el-empty__image img) {
  opacity: 0.5;
  transition: opacity 0.3s ease;
}

.dark-theme :deep(.el-empty__image img) {
  opacity: 0.3;
}

@media (max-width: 1400px) {
  .completed-grid {
    grid-template-columns: repeat(4, 1fr);
  }
}

@media (max-width: 1100px) {
  .completed-grid {
    grid-template-columns: repeat(3, 1fr);
  }

  .running-grid {
    grid-template-columns: 1fr;
  }

  .pending-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .action-buttons-row {
    flex-direction: column;
  }
  
  .action-button {
    padding: 16px 20px;
  }
  
  .btn-icon {
    width: 44px;
    height: 44px;
  }
  
  .btn-icon .el-icon {
    font-size: 22px;
  }
  
  .btn-title {
    font-size: 16px;
  }
  
  .btn-desc {
    font-size: 12px;
  }
  
  .completed-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 480px) {
  .completed-grid {
    grid-template-columns: 1fr;
  }
}
</style>
