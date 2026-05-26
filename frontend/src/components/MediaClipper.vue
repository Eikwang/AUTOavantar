<template>
  <div class="media-clipper" :class="{ 'dark-theme': isDarkTheme }">
    <!-- 剪辑按钮 -->
    <el-button
      v-if="!showClipper"
      type="warning"
      size="small"
      class="clip-trigger-btn"
      @click="openClipper"
      title="剪辑此媒体"
    >
      <el-icon><Scissor /></el-icon>
      剪辑
    </el-button>

    <!-- 剪辑面板 -->
    <div v-show="showClipper" class="clipper-panel">
      <!-- 波形/帧显示区域 -->
      <div class="timeline-container">
        <!-- 视频：显示帧预览 -->
        <div v-if="mediaType === 'video'" class="video-timeline">
          <div class="frame-ruler">
            <span v-for="marker in frameMarkers" :key="marker.frame" class="frame-marker">
              {{ marker.label }}
            </span>
          </div>
          <div
            ref="timelineRef"
            class="timeline-track"
            @mousedown="handleTimelineMouseDown"
            @mousemove="handleTimelineMouseMove"
            @mouseup="handleTimelineMouseUp"
            @mouseleave="handleTimelineMouseUp"
          >
            <!-- 可选：视频缩略图序列 -->
            <div v-if="thumbnails.length > 0" class="thumbnails-strip">
              <img
                v-for="(thumb, idx) in thumbnails"
                :key="idx"
                :src="thumb"
                class="thumbnail-frame"
              />
            </div>

            <!-- 播放头 -->
            <div
              v-if="isDragging"
              class="playhead"
              :style="{ left: playheadPosition + '%' }"
            >
              <div class="playhead-line"></div>
              <div class="playhead-time">{{ formatTime(currentTime) }}</div>
            </div>
          </div>
        </div>

        <!-- 音频：显示波形 -->
        <div v-else class="audio-timeline">
          <div
            ref="waveformRef"
            class="waveform-container"
            @mousedown="handleWaveformMouseDown"
            @mousemove="handleWaveformMouseMove"
            @mouseup="handleWaveformMouseUp"
            @mouseleave="handleWaveformMouseUp"
          >
            <!-- 波形 Canvas -->
            <canvas ref="waveformCanvas" class="waveform-canvas"></canvas>

            <!-- 播放头 -->
            <div
              v-if="isDragging"
              class="playhead"
              :style="{ left: playheadPosition + '%' }"
            >
              <div class="playhead-line"></div>
              <div class="playhead-time">{{ formatTime(currentTime) }}</div>
            </div>
          </div>
        </div>

        <!-- 剪辑区域选择器 -->
        <div
          class="clip-region"
          :style="{
            left: clipStartPercent + '%',
            width: (clipEndPercent - clipStartPercent) + '%'
          }"
        >
          <!-- 左手柄 -->
          <div
            class="clip-handle clip-handle-left"
            @mousedown="handleLeftHandleMouseDown"
          >
            <el-icon><ArrowLeft /></el-icon>
          </div>

          <!-- 右手柄 -->
          <div
            class="clip-handle clip-handle-right"
            @mousedown="handleRightHandleMouseDown"
          >
            <el-icon><ArrowRight /></el-icon>
          </div>

          <!-- 剪辑区域标签 -->
          <div class="clip-duration-label">
            {{ formatTime(clipDuration) }}
          </div>
        </div>
      </div>

      <!-- 时间显示 -->
      <div class="time-display">
        <span class="time-label">开始：</span>
        <span class="time-value">{{ formatTime(clipStartTime) }}</span>
        <span class="time-label" style="margin-left: 20px;">结束：</span>
        <span class="time-value">{{ formatTime(clipEndTime) }}</span>
        <span class="time-label" style="margin-left: 20px;">时长：</span>
        <span class="time-value highlight">{{ formatTime(clipDuration) }}</span>
        <span v-if="mediaType === 'video'" class="frame-info">
          ({{ currentFrame }} / {{ totalFrames }} 帧)
        </span>
      </div>

      <!-- 操作按钮 -->
      <div class="clipper-actions">
        <el-button size="small" @click="closeClipper">取消</el-button>
        <el-button
          size="small"
          @click="resetClip"
          :disabled="isClipping"
        >
          重置
        </el-button>
        <el-button
          v-if="mediaType === 'video'"
          size="small"
          type="warning"
          @click="setToFullVideo"
          :disabled="isClipping"
        >
          全选
        </el-button>
        <el-button
          size="small"
          type="primary"
          :loading="isClipping"
          :disabled="!canClip"
          @click="confirmClip"
        >
          <el-icon><Check /></el-icon>
          {{ isClipping ? '剪辑中...' : '保存并替换' }}
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { Scissor, ArrowLeft, ArrowRight, Check } from '@element-plus/icons-vue'
import { mediaClipApi } from '@/services/api'

const props = defineProps({
  filePath: {
    type: String,
    required: true
  },
  mediaType: {
    type: String,
    default: 'video', // 'video' or 'audio'
    validator: (val) => ['video', 'audio'].includes(val)
  },
  isDarkTheme: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['clipped', 'cancel'])

// 状态
const showClipper = ref(false)
const isClipping = ref(false)
const isDragging = ref(false)
const dragMode = ref(null) // 'left', 'right', 'playhead'

// 媒体信息
const duration = ref(0)
const fps = ref(30)
const totalFrames = ref(0)
const currentFrame = ref(0)
const currentTime = ref(0)

// 波形数据
const waveformPeaks = ref([])
const waveformCanvas = ref(null)
const waveformRef = ref(null)

// 剪辑范围
const clipStartTime = ref(0)
const clipEndTime = ref(0)

// 计算属性
const clipStartPercent = computed(() => {
  if (duration.value === 0) return 0
  return (clipStartTime.value / duration.value) * 100
})

const clipEndPercent = computed(() => {
  if (duration.value === 0) return 100
  return (clipEndTime.value / duration.value) * 100
})

const clipDuration = computed(() => {
  return clipEndTime.value - clipStartTime.value
})

const playheadPosition = computed(() => {
  if (duration.value === 0) return 0
  return (currentTime.value / duration.value) * 100
})

const canClip = computed(() => {
  return clipDuration.value > 0.1 && clipEndTime.value <= duration.value
})

const frameMarkers = computed(() => {
  const markers = []
  const step = Math.max(1, Math.floor(totalFrames.value / 20))
  for (let i = 0; i <= totalFrames.value; i += step) {
    const time = i / fps.value
    markers.push({
      frame: i,
      label: formatTime(time)
    })
  }
  return markers
})

const thumbnails = ref([]) // 预留视频缩略图序列

// 初始化
onMounted(() => {
  if (showClipper.value) {
    loadMediaInfo()
  }
})

watch(showClipper, (val) => {
  if (val) {
    loadMediaInfo()
  }
})

// 加载媒体信息
const loadMediaInfo = async () => {
  try {
    const isAudio = props.mediaType === 'audio' ||
      props.filePath.endsWith('.mp3') ||
      props.filePath.endsWith('.wav') ||
      props.filePath.endsWith('.m4a') ||
      props.filePath.endsWith('.flac')

    const response = await mediaClipApi.getInfo({
      file_path: props.filePath,
      file_type: isAudio ? 'audio' : 'video'
    })

    if (response.code === 200) {
      duration.value = response.data.duration || 0

      if (isAudio) {
        fps.value = 44100 // 音频采样率
        totalFrames.value = Math.floor(duration.value * 44100)
      } else {
        fps.value = response.data.fps || 30
        totalFrames.value = response.data.total_frames || Math.floor(duration.value * fps.value)
      }

      // 初始化剪辑范围为全片
      clipStartTime.value = 0
      clipEndTime.value = duration.value
      currentFrame.value = 0
      currentTime.value = 0

      // 如果是音频，加载波形
      if (isAudio) {
        await loadWaveform()
      }
    }
  } catch (error) {
    console.error('加载媒体信息失败:', error)
    ElMessage.error('加载媒体信息失败')
  }
}

// 加载音频波形
const loadWaveform = async () => {
  try {
    const response = await mediaClipApi.getWaveform({
      file_path: props.filePath,
      samples: 500
    })

    if (response.code === 200) {
      waveformPeaks.value = response.data.peaks || []
      await nextTick()
      drawWaveform()
    }
  } catch (error) {
    console.error('加载波形失败:', error)
  }
}

// 绘制波形
const drawWaveform = () => {
  if (!waveformCanvas.value || waveformPeaks.value.length === 0) return

  const canvas = waveformCanvas.value
  const ctx = canvas.getContext('2d')
  const width = canvas.width
  const height = canvas.height

  // 清空画布
  ctx.clearRect(0, 0, width, height)

  // 背景
  ctx.fillStyle = props.isDarkTheme ? '#1a1f26' : '#f5f7fa'
  ctx.fillRect(0, 0, width, height)

  // 绘制波形
  const peaks = waveformPeaks.value
  const barWidth = width / peaks.length
  const centerY = height / 2

  for (let i = 0; i < peaks.length; i++) {
    const amplitude = peaks[i]
    const barHeight = amplitude * height * 0.9

    // 渐变颜色
    const gradient = ctx.createLinearGradient(0, centerY - barHeight / 2, 0, centerY + barHeight / 2)
    if (props.isDarkTheme) {
      gradient.addColorStop(0, '#00d9ff')
      gradient.addColorStop(1, '#00ff88')
    } else {
      gradient.addColorStop(0, '#409eff')
      gradient.addColorStop(1, '#67c23a')
    }

    ctx.fillStyle = gradient
    ctx.fillRect(
      i * barWidth,
      centerY - barHeight / 2,
      Math.max(1, barWidth - 1),
      barHeight
    )
  }

  // 绘制剪辑区域覆盖层
  const startPercent = clipStartPercent.value / 100
  const endPercent = clipEndPercent.value / 100

  // 左侧覆盖
  ctx.fillStyle = 'rgba(0, 0, 0, 0.5)'
  ctx.fillRect(0, 0, startPercent * width, height)

  // 右侧覆盖
  ctx.fillRect(endPercent * width, 0, (1 - endPercent) * width, height)
}

watch([clipStartTime, clipEndTime, waveformPeaks, isDarkTheme], () => {
  if (props.mediaType === 'audio') {
    drawWaveform()
  }
}, { immediate: true })

// 鼠标交互
const handleTimelineMouseDown = (e) => {
  isDragging.value = true
  dragMode.value = 'playhead'
  updatePlayhead(e)
}

const handleTimelineMouseMove = (e) => {
  if (!isDragging.value) return
  if (dragMode.value === 'playhead') {
    updatePlayhead(e)
  }
}

const handleTimelineMouseUp = () => {
  isDragging.value = false
  dragMode.value = null
}

const updatePlayhead = (e) => {
  const rect = e.currentTarget.getBoundingClientRect()
  const x = e.clientX - rect.left
  const percent = Math.max(0, Math.min(1, x / rect.width))
  currentTime.value = percent * duration.value
  currentFrame.value = Math.floor(currentTime.value * fps.value)
}

// 音频波形交互
const handleWaveformMouseDown = (e) => {
  const rect = waveformRef.value.getBoundingClientRect()
  const x = e.clientX - rect.left
  const percent = x / rect.width

  const clickTime = percent * duration.value
  const clipStart = clipStartTime.value
  const clipEnd = clipEndTime.value

  // 检测点击位置
  if (clickTime < clipStart + 0.1) {
    isDragging.value = true
    dragMode.value = 'left'
  } else if (clickTime > clipEnd - 0.1) {
    isDragging.value = true
    dragMode.value = 'right'
  } else if (clickTime >= clipStart && clickTime <= clipEnd) {
    isDragging.value = true
    dragMode.value = 'move'
  } else {
    // 点击外部，跳转到该位置
    currentTime.value = clickTime
    currentFrame.value = Math.floor(currentTime.value * fps.value)
  }
}

const handleWaveformMouseMove = (e) => {
  if (!isDragging.value) return

  const rect = waveformRef.value.getBoundingClientRect()
  const x = e.clientX - rect.left
  const percent = Math.max(0, Math.min(1, x / rect.width))
  const time = percent * duration.value

  if (dragMode.value === 'left') {
    clipStartTime.value = Math.max(0, Math.min(time, clipEndTime.value - 0.1))
  } else if (dragMode.value === 'right') {
    clipEndTime.value = Math.max(clipStartTime.value + 0.1, Math.min(time, duration.value))
  } else if (dragMode.value === 'move') {
    const clipDuration = clipEndTime.value - clipStartTime.value
    clipStartTime.value = Math.max(0, Math.min(time - clipDuration / 2, duration.value - clipDuration))
    clipEndTime.value = clipStartTime.value + clipDuration
  }

  currentTime.value = time
  currentFrame.value = Math.floor(currentTime.value * fps.value)
}

const handleWaveformMouseUp = () => {
  isDragging.value = false
  dragMode.value = null
}

// 手柄拖拽
const handleLeftHandleMouseDown = (e) => {
  e.stopPropagation()
  isDragging.value = true
  dragMode.value = 'left'
}

const handleRightHandleMouseDown = (e) => {
  e.stopPropagation()
  isDragging.value = true
  dragMode.value = 'right'
}

// 全局鼠标事件
const handleGlobalMouseMove = (e) => {
  if (!isDragging.value) return

  if (dragMode.value === 'left') {
    // 左边界拖拽逻辑已在波形处理中
  } else if (dragMode.value === 'right') {
    // 右边界拖拽逻辑已在波形处理中
  }
}

const handleGlobalMouseUp = () => {
  isDragging.value = false
  dragMode.value = null
}

onMounted(() => {
  window.addEventListener('mousemove', handleGlobalMouseMove)
  window.addEventListener('mouseup', handleGlobalMouseUp)
})

onMounted(() => {
  window.removeEventListener('mousemove', handleGlobalMouseMove)
  window.removeEventListener('mouseup', handleGlobalMouseUp)
})

// 操作
const openClipper = () => {
  showClipper.value = true
  emit('cancel')
}

const closeClipper = () => {
  showClipper.value = false
  emit('cancel')
}

const resetClip = () => {
  clipStartTime.value = 0
  clipEndTime.value = duration.value
  currentTime.value = 0
  currentFrame.value = 0
}

const setToFullVideo = () => {
  clipStartTime.value = 0
  clipEndTime.value = duration.value
}

const confirmClip = async () => {
  if (!canClip.value) {
    ElMessage.warning('请选择有效的剪辑范围')
    return
  }

  isClipping.value = true

  try {
    const response = await mediaClipApi.clip({
      file_path: props.filePath,
      start_time: clipStartTime.value,
      end_time: clipEndTime.value,
      replace_original: true
    })

    if (response.code === 200) {
      ElMessage.success('剪辑成功')
      emit('clipped', {
        filePath: props.filePath,
        startTime: clipStartTime.value,
        endTime: clipEndTime.value,
        duration: clipDuration.value
      })
      closeClipper()
    } else {
      ElMessage.error(response.message || '剪辑失败')
    }
  } catch (error) {
    console.error('剪辑失败:', error)
    ElMessage.error('剪辑失败：' + (error.message || '未知错误'))
  } finally {
    isClipping.value = false
  }
}

// 格式化时间
const formatTime = (seconds) => {
  if (!seconds) return '00:00'
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  const ms = Math.floor((seconds % 1) * 100)
  return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}.${ms.toString().padStart(2, '0')}`
}

// 暴露方法给父组件
defineExpose({
  openClipper,
  closeClipper
})
</script>

<style scoped lang="scss">
.media-clipper {
  position: relative;
}

.clip-trigger-btn {
  font-weight: 500;
  border: 2px solid currentColor;
  transition: all 0.2s ease;

  &:hover {
    transform: scale(1.05);
    box-shadow: 0 2px 8px rgba(230, 162, 60, 0.4);
  }

  .el-icon {
    font-size: 18px;
    margin-right: 4px;
  }
}

.clipper-panel {
  margin-top: 10px;
  padding: 15px;
  background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.dark-theme .clipper-panel {
  background: linear-gradient(135deg, #1f1f1f 0%, #262626 100%);
  border-color: #424242;
}

.timeline-container {
  position: relative;
  margin-bottom: 15px;
  user-select: none;
}

.video-timeline,
.audio-timeline {
  position: relative;
}

.frame-ruler {
  display: flex;
  justify-content: space-between;
  padding: 5px 0;
  font-size: 11px;
  color: #64748b;
  border-bottom: 1px solid #e2e8f0;
}

.dark-theme .frame-ruler {
  border-color: #424242;
  color: #9e9e9e;
}

.timeline-track {
  height: 60px;
  background: #eef2f6;
  border-radius: 4px;
  cursor: pointer;
  position: relative;
  overflow: hidden;
}

.dark-theme .timeline-track {
  background: #2d2d2d;
}

.thumbnails-strip {
  display: flex;
  height: 100%;
  overflow: hidden;
}

.thumbnail-frame {
  height: 100%;
  object-fit: cover;
  flex-shrink: 0;
}

.waveform-container {
  position: relative;
  height: 100px;
  background: #eef2f6;
  border-radius: 4px;
  cursor: pointer;
  overflow: hidden;
}

.dark-theme .waveform-container {
  background: #2d2d2d;
}

.waveform-canvas {
  width: 100%;
  height: 100%;
}

.playhead {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 2px;
  background: #ff4444;
  pointer-events: none;
  z-index: 10;
}

.playhead-line {
  width: 2px;
  height: 100%;
  background: #ff4444;
}

.playhead-time {
  position: absolute;
  top: -25px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(255, 68, 68, 0.9);
  color: white;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  white-space: nowrap;
}

.clip-region {
  position: absolute;
  top: 0;
  bottom: 0;
  background: rgba(64, 158, 255, 0.2);
  border-left: 2px solid #409eff;
  border-right: 2px solid #409eff;
  cursor: move;
  z-index: 5;
  transition: background 0.2s;

  &:hover {
    background: rgba(64, 158, 255, 0.3);
  }
}

.clip-handle {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  width: 20px;
  height: 40px;
  background: #409eff;
  border-radius: 4px;
  cursor: ew-resize;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  opacity: 0;
  transition: opacity 0.2s;

  &:hover {
    opacity: 1;
  }
}

.clip-region:hover .clip-handle {
  opacity: 1;
}

.clip-handle-left {
  left: -10px;
}

.clip-handle-right {
  right: -10px;
}

.clip-duration-label {
  position: absolute;
  top: -25px;
  left: 50%;
  transform: translateX(-50%);
  background: #409eff;
  color: white;
  padding: 2px 10px;
  border-radius: 4px;
  font-size: 12px;
  white-space: nowrap;
  opacity: 0;
  transition: opacity 0.2s;
}

.clip-region:hover .clip-duration-label {
  opacity: 1;
}

.time-display {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 10px 0;
  font-size: 13px;
  border-top: 1px solid #e2e8f0;
}

.dark-theme .time-display {
  border-color: #424242;
}

.time-label {
  color: #64748b;
}

.dark-theme .time-label {
  color: #9e9e9e;
}

.time-value {
  font-family: 'Courier New', monospace;
  color: #303133;
  font-weight: 500;

  &.highlight {
    color: #409eff;
    font-weight: 600;
  }
}

.dark-theme .time-value {
  color: #e0e0e0;

  &.highlight {
    color: #00d9ff;
  }
}

.frame-info {
  color: #909399;
  font-size: 12px;
}

.clipper-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding-top: 10px;
  border-top: 1px solid #e2e8f0;
}

.dark-theme .clipper-actions {
  border-color: #424242;
}
</style>
