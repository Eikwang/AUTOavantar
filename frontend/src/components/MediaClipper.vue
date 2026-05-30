<template>
  <div class="media-clipper" :class="{ 'dark-theme': isDarkTheme }">
    <!-- 播放器工具栏 -->
    <div class="player-toolbar">
      <div class="toolbar-left">
        <el-button-group>
          <el-button size="small" :type="isPlaying ? 'primary' : 'default'" @click="togglePlay">
            <el-icon><VideoPlay v-if="!isPlaying" /><VideoPause v-else /></el-icon>
          </el-button>
        </el-button-group>
        <el-slider
          v-model="volume"
          :min="0"
          :max="100"
          :show-tooltip="false"
          size="small"
          class="volume-slider"
          @input="handleVolumeChange"
        />
        <el-icon class="volume-icon"><component :is="volumeIcon" /></el-icon>
      </div>
      <div class="toolbar-right">
        <el-button
          size="small"
          :type="activeMode === 'trim' ? 'warning' : 'default'"
          @click="switchMode('trim')"
          title="时间剪辑"
        >
          <el-icon><Scissor /></el-icon>
          时间裁剪
          <span v-if="pendingTrim" class="pending-badge">●</span>
        </el-button>
        <el-button
          v-if="mediaType === 'video'"
          size="small"
          :type="activeMode === 'crop' ? 'warning' : 'default'"
          @click="switchMode('crop')"
          title="画面裁剪"
        >
          <el-icon><Crop /></el-icon>
          画面裁剪
          <span v-if="pendingCrop" class="pending-badge">●</span>
        </el-button>
        <el-button
          v-if="activeMode"
          size="small"
          type="success"
          :loading="isProcessing"
          :disabled="!canSave"
          @click="handleSave"
        >
          <el-icon><Check /></el-icon>
          {{ activeMode === 'trim' ? '保存剪辑' : '保存裁剪' }}
        </el-button>
        <el-button
          v-if="activeMode"
          size="small"
          @click="handleReset"
        >
          <el-icon><RefreshRight /></el-icon>
          重置
        </el-button>
      </div>
    </div>

    <!-- 媒体播放器 -->
    <div class="media-player-container" ref="playerContainerRef">
      <video
        v-if="mediaType === 'video'"
        ref="mediaRef"
        :src="getFileUrl(props.filePath)"
        class="media-player video-player"
        controls
        @loadedmetadata="handleLoadedMetadata"
        @timeupdate="handleTimeUpdate"
        @ended="handleEnded"
      ></video>
      <audio
        v-else
        ref="mediaRef"
        :src="getFileUrl(props.filePath)"
        class="media-player audio-player"
        controls
        @loadedmetadata="handleLoadedMetadata"
        @timeupdate="handleTimeUpdate"
        @ended="handleEnded"
      ></audio>

      <!-- 画面裁剪叠加层（放在播放器容器内，仅覆盖视频实际渲染区域） -->
      <div v-if="activeMode === 'crop' && mediaType === 'video'" class="crop-overlay" :style="videoRenderStyle">
        <!-- 四块遮罩 -->
        <div class="crop-mask crop-mask-top" :style="{ height: cropRect.y * 100 + '%' }"></div>
        <div class="crop-mask crop-mask-bottom" :style="{ top: (cropRect.y + cropRect.h) * 100 + '%' }"></div>
        <div
          class="crop-mask crop-mask-left"
          :style="{ top: cropRect.y * 100 + '%', height: cropRect.h * 100 + '%', width: cropRect.x * 100 + '%' }"
        ></div>
        <div
          class="crop-mask crop-mask-right"
          :style="{ top: cropRect.y * 100 + '%', left: (cropRect.x + cropRect.w) * 100 + '%', height: cropRect.h * 100 + '%' }"
        ></div>
        <!-- 裁剪区域 -->
        <div
          class="crop-box"
          :style="{
            left: cropRect.x * 100 + '%',
            top: cropRect.y * 100 + '%',
            width: cropRect.w * 100 + '%',
            height: cropRect.h * 100 + '%'
          }"
          @mousedown="startCropDrag('move', $event)"
        >
          <!-- 8个手柄 -->
          <div class="crop-handle crop-handle-tl" @mousedown.stop="startCropDrag('tl', $event)"></div>
          <div class="crop-handle crop-handle-tc" @mousedown.stop="startCropDrag('tc', $event)"></div>
          <div class="crop-handle crop-handle-tr" @mousedown.stop="startCropDrag('tr', $event)"></div>
          <div class="crop-handle crop-handle-ml" @mousedown.stop="startCropDrag('ml', $event)"></div>
          <div class="crop-handle crop-handle-mr" @mousedown.stop="startCropDrag('mr', $event)"></div>
          <div class="crop-handle crop-handle-bl" @mousedown.stop="startCropDrag('bl', $event)"></div>
          <div class="crop-handle crop-handle-bc" @mousedown.stop="startCropDrag('bc', $event)"></div>
          <div class="crop-handle crop-handle-br" @mousedown.stop="startCropDrag('br', $event)"></div>
          <!-- 尺寸标注 -->
          <div class="crop-size-label">{{ cropPixelW }}x{{ cropPixelH }}</div>
          <!-- 比例锁定控制区 - 移到底部控制面板 -->
          <div class="aspect-lock-control" v-if="false">
            <el-switch
              v-model="aspectLockEnabled"
              size="small"
              active-text="锁定"
              inactive-text=""
            />
            <el-select
              v-model="aspectRatio"
              size="small"
              :disabled="!aspectLockEnabled"
              class="aspect-ratio-select"
            >
              <el-option value="original" label="原始比例" />
              <el-option value="16:9" label="16:9" />
              <el-option value="9:16" label="9:16" />
              <el-option value="1:1" label="1:1" />
            </el-select>
          </div>
        </div>
      </div>
    </div>

    <!-- 画面裁剪控制面板 - 移到底部时间轴位置 -->
    <div v-if="activeMode === 'crop' && mediaType === 'video'" class="crop-control-panel">
      <div class="crop-control-row">
        <el-switch
          v-model="aspectLockEnabled"
          size="small"
          active-text="锁定比例"
          inactive-text=""
        />
        <el-select
          v-model="aspectRatio"
          size="small"
          :disabled="!aspectLockEnabled"
          class="aspect-ratio-select"
        >
          <el-option value="original" label="原始比例" />
          <el-option value="16:9" label="16:9" />
          <el-option value="9:16" label="9:16" />
          <el-option value="1:1" label="1:1" />
        </el-select>
        <span class="crop-size-display">{{ cropPixelW }}x{{ cropPixelH }}</span>
      </div>
    </div>

    <!-- 时间剪辑面板 -->
    <div v-if="activeMode === 'trim'" class="trim-panel">
      <!-- 音频：波形 -->
      <div v-if="isAudio" class="audio-timeline">
        <div
          ref="waveformRef"
          class="waveform-container"
          @mousedown="handleWaveformMouseDown"
          @mousemove="handleWaveformMouseMove"
          @mouseup="handleWaveformMouseUp"
          @mouseleave="handleWaveformMouseUp"
        >
          <canvas ref="waveformCanvas" class="waveform-canvas"></canvas>
          <!-- 播放头 -->
          <div
            v-if="isDragging && dragType === 'playhead'"
            class="playhead"
            :style="{ left: playheadPercent + '%' }"
          >
            <div class="playhead-line"></div>
            <div class="playhead-time">{{ formatTime(currentTime) }}</div>
          </div>
        </div>
      </div>

      <!-- 视频：帧标尺时间线 -->
      <div v-else class="video-timeline">
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
          <!-- 播放头 -->
          <div
            v-if="isDragging && dragType === 'playhead'"
            class="playhead"
            :style="{ left: playheadPercent + '%' }"
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
        <div class="clip-handle clip-handle-left" @mousedown.stop="startClipDrag('left', $event)">
          <el-icon><ArrowLeft /></el-icon>
        </div>
        <div class="clip-handle clip-handle-right" @mousedown.stop="startClipDrag('right', $event)">
          <el-icon><ArrowRight /></el-icon>
        </div>
        <div class="clip-duration-label">{{ formatTime(clipDuration) }}</div>
      </div>

      <!-- 时间显示 -->
      <div class="time-display">
        <span class="time-label">开始：</span>
        <span class="time-value">{{ formatTime(clipStartTime) }}</span>
        <span class="time-label" style="margin-left: var(--space-base);">结束：</span>
        <span class="time-value">{{ formatTime(clipEndTime) }}</span>
        <span class="time-label" style="margin-left: var(--space-base);">时长：</span>
        <span class="time-value highlight">{{ formatTime(clipDuration) }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import {
  VideoPlay, VideoPause, Scissor, Crop, Check, RefreshRight,
  ArrowLeft, ArrowRight, Mute, Notification, Microphone
} from '@element-plus/icons-vue'
import { mediaClipApi } from '@/services/api'

const props = defineProps({
  filePath: {
    type: String,
    required: true
  },
  mediaType: {
    type: String,
    default: 'video',
    validator: (val) => ['video', 'audio'].includes(val)
  },
  mode: {
    type: String,
    default: 'trim',
    validator: (val) => ['trim', 'crop'].includes(val)
  },
  defaultMode: {
    type: String,
    default: 'trim',
    validator: (val) => ['trim', 'crop'].includes(val)
  },
  isDarkTheme: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['clipped', 'cropped', 'cancel'])

// === 播放器状态 ===
const isPlaying = ref(false)
const volume = ref(80)
const currentTime = ref(0)
const mediaRef = ref(null)

// === 模式状态 ===
const activeMode = ref(props.defaultMode || 'trim') // null | 'trim' | 'crop'

// === 媒体信息 ===
const duration = ref(0)
const fps = ref(30)
const totalFrames = ref(0)
const videoWidth = ref(0)
const videoHeight = ref(0)
const isProcessing = ref(false)

// === 时间剪辑状态 ===
const clipStartTime = ref(0)
const clipEndTime = ref(0)
const isDragging = ref(false)
const dragType = ref(null) // 'left', 'right', 'move', 'playhead'

// === 波形状态 ===
const waveformPeaks = ref([])
const waveformCanvas = ref(null)
const waveformRef = ref(null)
const timelineRef = ref(null)
const waveformLoading = ref(false)
const waveformError = ref('')

// === 画面裁剪状态 ===
const cropRect = ref({ x: 0, y: 0, w: 1, h: 1 })
// 暂存参数：切换模式时保留已设置的参数，支持同时进行时间剪辑+画面裁剪
const pendingTrim = ref(null) // { startTime, endTime } | null
const pendingCrop = ref(null) // { x, y, w, h } | null
const cropDragType = ref(null) // 'tl','tc','tr','ml','mr','bl','bc','br','move'
const playerContainerRef = ref(null)
const cropDragStart = ref({ mx: 0, my: 0, rect: {} })

// === 画面裁剪锁定比例状态 ===
const aspectLockEnabled = ref(true) // 默认开启锁定
const aspectRatio = ref('original') // 默认原始比例
const currentOriginalAspect = ref(16/9) // 当前裁剪区域的原始比例（用于"原始比例"选项）

// 比例选项常量
const aspectRatios = {
  '16:9': 16/9,
  '9:16': 9/16,
  '1:1': 1,
  'original': null
}

// 更新当前原始比例（当裁剪区域变化时）- 使用像素比例
const updateOriginalAspect = () => {
  if (aspectRatio.value === 'original' && cropRect.value.w > 0 && cropRect.value.h > 0 && videoWidth.value && videoHeight.value) {
    // 将当前裁剪框的百分比比例转换为像素比例
    const percentAspect = cropRect.value.w / cropRect.value.h
    currentOriginalAspect.value = percentAspect * (videoWidth.value / videoHeight.value)
  }
}

// 监听比例锁定设置变化，自动调整裁剪框到目标比例
watch([aspectRatio, aspectLockEnabled], () => {
  if (!aspectLockEnabled.value || !aspectRatio.value) return
  if (!cropRect.value.w || !cropRect.value.h || !videoWidth.value || !videoHeight.value) return

  let targetAspect = null
  if (aspectRatio.value === 'original') {
    targetAspect = currentOriginalAspect.value
  } else {
    targetAspect = aspectRatios[aspectRatio.value]
  }

  if (!targetAspect) return

  // cropRect 是百分比(0-1)，targetAspect 是像素比例(如 16:9=1.78)
  // 需要将像素比例转换为百分比比例
  // percentAspect = targetAspect * (vh / vw)
  const percentAspect = targetAspect * (videoHeight.value / videoWidth.value)

  const currentAspect = cropRect.value.w / cropRect.value.h

  // 如果当前比例与目标比例差异超过 1%，则调整
  if (Math.abs(currentAspect - percentAspect) > 0.01) {
    const r = cropRect.value

    let newW, newH
    if (percentAspect > currentAspect) {
      // 目标更宽 → 以高度为基准
      newH = r.h
      newW = newH * percentAspect
    } else {
      // 目标更窄 → 以宽度为基准
      newW = r.w
      newH = newW / percentAspect
    }

    // 确保不超出边界
    let newX = r.x
    let newY = r.y
    if (newW > 1) {
      newW = 1
      newH = newW / percentAspect
    }
    if (newH > 1) {
      newH = 1
      newW = newH * percentAspect
    }

    // 居中调整：保持中心点不变
    newX = r.x + (r.w - newW) / 2
    newY = r.y + (r.h - newH) / 2

    cropRect.value = { x: newX, y: newY, w: newW, h: newH }
  }
})

// === 计算属性 ===
const isAudio = computed(() => {
  return props.mediaType === 'audio' ||
    (props.filePath && props.filePath.endsWith('.mp3')) ||
    (props.filePath && props.filePath.endsWith('.wav')) ||
    (props.filePath && props.filePath.endsWith('.m4a')) ||
    (props.filePath && props.filePath.endsWith('.flac'))
})

const clipStartPercent = computed(() => duration.value ? (clipStartTime.value / duration.value) * 100 : 0)
const clipEndPercent = computed(() => duration.value ? (clipEndTime.value / duration.value) * 100 : 100)
const clipDuration = computed(() => clipEndTime.value - clipStartTime.value)
const playheadPercent = computed(() => duration.value ? (currentTime.value / duration.value) * 100 : 0)

const canSave = computed(() => {
  if (activeMode.value === 'trim') {
    return clipDuration.value > 0.1 && clipEndTime.value <= duration.value + 0.01 && clipStartTime.value >= 0
  }
  if (activeMode.value === 'crop') {
    const r = cropRect.value
    return r.w > 0.05 && r.h > 0.05 && r.x >= 0 && r.y >= 0 && (r.x + r.w) <= 1.01 && (r.y + r.h) <= 1.01
  }
  return false
})

const cropPixelW = computed(() => Math.round(videoWidth.value * cropRect.value.w))
const cropPixelH = computed(() => Math.round(videoHeight.value * cropRect.value.h))

// === 视频渲染区域计算（object-fit: contain） ===
const videoRenderRect = ref({ left: 0, top: 0, width: 100, height: 100 })
const videoRenderStyle = computed(() => ({
  position: 'absolute',
  left: videoRenderRect.value.left + '%',
  top: videoRenderRect.value.top + '%',
  width: videoRenderRect.value.width + '%',
  height: videoRenderRect.value.height + '%',
}))

const updateVideoRenderRect = () => {
  const container = playerContainerRef.value
  const video = mediaRef.value
  if (!container || !video || !videoWidth.value || !videoHeight.value) return

  const cw = container.clientWidth
  const ch = container.clientHeight
  const vw = videoWidth.value
  const vh = videoHeight.value

  // object-fit: contain 计算实际渲染区域
  const containerAspect = cw / ch
  const videoAspect = vw / vh

  let renderW, renderH, renderL, renderT
  if (videoAspect > containerAspect) {
    // 视频更宽，左右撑满，上下留黑边
    renderW = 100
    renderH = (containerAspect / videoAspect) * 100
    renderL = 0
    renderT = (100 - renderH) / 2
  } else {
    // 视频更高，上下撑满，左右留黑边
    renderH = 100
    renderW = (videoAspect / containerAspect) * 100
    renderT = 0
    renderL = (100 - renderW) / 2
  }

  videoRenderRect.value = { left: renderL, top: renderT, width: renderW, height: renderH }
}

watch([videoWidth, videoHeight], () => {
  nextTick(updateVideoRenderRect)
})

const frameMarkers = computed(() => {
  const markers = []
  const step = Math.max(1, Math.floor(totalFrames.value / 20))
  for (let i = 0; i <= totalFrames.value; i += step) {
    markers.push({ frame: i, label: formatTime(i / fps.value) })
  }
  return markers
})

const volumeIcon = computed(() => {
  if (volume.value === 0) return Mute
  if (volume.value < 50) return Microphone
  return Notification
})

// === 播放器控制 ===
const togglePlay = () => {
  if (!mediaRef.value) return
  if (isPlaying.value) {
    mediaRef.value.pause()
  } else {
    mediaRef.value.play()
  }
  isPlaying.value = !isPlaying.value
}

const handleVolumeChange = () => {
  if (mediaRef.value) {
    mediaRef.value.volume = volume.value / 100
  }
}

const handleLoadedMetadata = () => {
  if (mediaRef.value) {
    duration.value = mediaRef.value.duration || 0
    clipStartTime.value = 0
    clipEndTime.value = duration.value
    // 从 video 元素获取渲染尺寸，更新裁剪叠加层位置
    if (props.mediaType === 'video' && mediaRef.value.videoWidth) {
      videoWidth.value = mediaRef.value.videoWidth
      videoHeight.value = mediaRef.value.videoHeight
    }
    nextTick(updateVideoRenderRect)
  }
}

const handleTimeUpdate = () => {
  if (mediaRef.value) {
    currentTime.value = mediaRef.value.currentTime
  }
}

const handleEnded = () => {
  isPlaying.value = false
}

const getFileUrl = (path) => {
  if (!path) return ''
  if (path.startsWith('http')) return path
  if (path.startsWith('/api/files/')) return path.replace('/api/files/', '/files/')
  if (path.startsWith('/files/')) return path
  return '/files/' + path
}

// === 模式切换 ===
const hasUnsavedEdits = () => {
  if (activeMode.value === 'trim') {
    return clipStartTime.value > 0.01 || clipEndTime.value < duration.value - 0.01
  }
  if (activeMode.value === 'crop') {
    return cropRect.value.x > 0.01 || cropRect.value.y > 0.01 ||
      cropRect.value.w < 0.99 || cropRect.value.h < 0.99
  }
  return false
}

const switchMode = (newMode) => {
  if (activeMode.value === newMode) {
    // 再次点击同一模式按钮：暂存当前参数，取消激活
    if (activeMode.value === 'trim' && hasTrimEdit()) {
      pendingTrim.value = { startTime: clipStartTime.value, endTime: clipEndTime.value }
    }
    if (activeMode.value === 'crop' && hasCropEdit()) {
      pendingCrop.value = { ...cropRect.value }
    }
    activeMode.value = null
    return
  }

  // 切换前：暂存当前模式的已修改参数
  if (activeMode.value === 'trim' && hasTrimEdit()) {
    pendingTrim.value = { startTime: clipStartTime.value, endTime: clipEndTime.value }
  }
  if (activeMode.value === 'crop' && hasCropEdit()) {
    pendingCrop.value = { ...cropRect.value }
  }

  activeMode.value = newMode

  // 切换后：恢复暂存的参数，若无暂存则初始化为默认值
  if (newMode === 'trim') {
    if (pendingTrim.value) {
      clipStartTime.value = pendingTrim.value.startTime
      clipEndTime.value = pendingTrim.value.endTime
    } else {
      clipStartTime.value = 0
      clipEndTime.value = duration.value
    }
    if (isAudio.value) loadWaveform()
  } else if (newMode === 'crop') {
    if (pendingCrop.value) {
      cropRect.value = { ...pendingCrop.value }
    } else {
      cropRect.value = { x: 0, y: 0, w: 1, h: 1 }
    }
    // 初始化原始比例
    if (videoWidth.value > 0 && videoHeight.value > 0) {
      currentOriginalAspect.value = videoWidth.value / videoHeight.value
    }
  }

  // 加载媒体信息（如果尚未加载）
  if (duration.value === 0) {
    loadMediaInfo()
  }
}

const hasTrimEdit = () => {
  return clipStartTime.value > 0.01 || clipEndTime.value < duration.value - 0.01
}

const hasCropEdit = () => {
  const r = cropRect.value
  return r.x > 0.01 || r.y > 0.01 || r.w < 0.99 || r.h < 0.99
}

// === 媒体信息加载 ===
const cleanFilePath = (path) => {
  if (!path) return ''
  // 先标准化反斜杠为正斜杠
  let cleaned = path.replace(/\\/g, '/')
  // 去除各种URL前缀
  cleaned = cleaned
    .replace(/^\/api\/files\//, '')
    .replace(/^\/files\//, '')
    .replace(/^\/api\//, '')
    .replace(/^files\//, '')
  console.log('[MediaClipper] cleanFilePath:', { input: path, output: cleaned })
  return cleaned
}

const loadMediaInfo = async () => {
  console.log('[MediaClipper] loadMediaInfo 开始:', { filePath: props.filePath, mediaType: props.mediaType })
  try {
    const response = await mediaClipApi.getInfo({
      file_path: cleanFilePath(props.filePath),
      file_type: isAudio.value ? 'audio' : 'video'
    })

    console.log('[MediaClipper] getInfo 响应:', { code: response.code, data: response.data })
    if (response.code === 200) {
      duration.value = response.data.duration || 0

      if (isAudio.value) {
        fps.value = 44100
        totalFrames.value = Math.floor(duration.value * 44100)
      } else {
        fps.value = response.data.fps || 30
        totalFrames.value = response.data.total_frames || Math.floor(duration.value * fps.value)
        videoWidth.value = response.data.width || 0
        videoHeight.value = response.data.height || 0
      }

      clipStartTime.value = 0
      clipEndTime.value = duration.value
      currentTime.value = 0

      // 视频尺寸加载后更新渲染区域
      if (!isAudio.value) {
        await nextTick()
        updateVideoRenderRect()
      }

      if (isAudio.value) {
        try {
          await loadWaveform()
        } catch (e) {
          console.warn('波形加载失败，将在切换模式时重试:', e)
        }
      }
    }
  } catch (error) {
    console.error('加载媒体信息失败:', error)
    ElMessage.error('加载媒体信息失败')
  }
}

// === 波形 ===
const loadWaveform = async () => {
  if (!props.filePath) return
  waveformLoading.value = true
  waveformError.value = ''
  try {
    const filePath = cleanFilePath(props.filePath)
    console.log('[MediaClipper] 加载波形, path:', filePath, 'isAudio:', isAudio.value)
    // 音频用 /waveform，视频用 /video/waveform
    const apiCall = isAudio.value
      ? mediaClipApi.getWaveform({ file_path: filePath, samples: 500 })
      : mediaClipApi.getVideoWaveform({ file_path: filePath, samples: 500 })
    const response = await apiCall
    if (response.code === 200 && response.data) {
      waveformPeaks.value = response.data.peaks || []
      if (response.data.duration && !duration.value) {
        duration.value = response.data.duration
        clipEndTime.value = response.data.duration
      }
      await nextTick()
      drawWaveform()
    } else {
      waveformError.value = response.message || '波形加载失败'
      console.warn('[MediaClipper] 波形加载失败:', response.message)
    }
  } catch (error) {
    waveformError.value = error.response?.data?.message || error.message || '波形加载异常'
    console.error('[MediaClipper] 波形加载异常:', error)
  } finally {
    waveformLoading.value = false
  }
}

const drawWaveform = () => {
  if (!waveformCanvas.value || waveformPeaks.value.length === 0) return

  const canvas = waveformCanvas.value
  const rect = canvas.getBoundingClientRect()
  canvas.width = rect.width || canvas.width
  canvas.height = rect.height || canvas.height

  if (canvas.width === 0 || canvas.height === 0) {
    nextTick(() => drawWaveform())
    return
  }

  const ctx = canvas.getContext('2d')
  const width = canvas.width
  const height = canvas.height

  // Canvas 不支持 CSS 变量，以下颜色需与 main.css 变量保持同步
  // 亮色: bg=#f5f7fa(--bg-page), primary=#409EFF(--color-primary), success=#67c23a(--color-success)
  // 暗色: bg=#161b22(--bg-card-solid), primary=#00d9ff(--color-primary), success=#00ff88(--color-success)
  const bgColor = props.isDarkTheme ? '#161b22' : '#f5f7fa'
  const waveStartColor = props.isDarkTheme ? '#00d9ff' : '#409eff'
  const waveEndColor = props.isDarkTheme ? '#00ff88' : '#67c23a'

  ctx.clearRect(0, 0, width, height)

  // 背景
  ctx.fillStyle = bgColor
  ctx.fillRect(0, 0, width, height)

  // 波形
  const peaks = waveformPeaks.value
  const barWidth = width / peaks.length
  const centerY = height / 2

  for (let i = 0; i < peaks.length; i++) {
    const amplitude = peaks[i]
    const barHeight = amplitude * height * 0.9

    const gradient = ctx.createLinearGradient(0, centerY - barHeight / 2, 0, centerY + barHeight / 2)
    gradient.addColorStop(0, waveStartColor)
    gradient.addColorStop(1, waveEndColor)

    ctx.fillStyle = gradient
    ctx.fillRect(i * barWidth, centerY - barHeight / 2, Math.max(1, barWidth - 1), barHeight)
  }

  // 剪辑区域覆盖
  const startPct = clipStartPercent.value / 100
  const endPct = clipEndPercent.value / 100

  ctx.fillStyle = 'rgba(0, 0, 0, 0.5)'
  ctx.fillRect(0, 0, startPct * width, height)
  ctx.fillRect(endPct * width, 0, (1 - endPct) * width, height)
}

watch([clipStartTime, clipEndTime, waveformPeaks, () => props.isDarkTheme], () => {
  if (isAudio.value && waveformPeaks.value.length > 0) {
    drawWaveform()
  }
}, { immediate: true })

// === 时间剪辑拖拽 ===
const startClipDrag = (type, e) => {
  isDragging.value = true
  dragType.value = type
  e.preventDefault()
}

const handleTimelineMouseDown = (e) => {
  isDragging.value = true
  dragType.value = 'playhead'
  updatePlayhead(e)
}

const handleTimelineMouseMove = (e) => {
  if (!isDragging.value || dragType.value !== 'playhead') return
  updatePlayhead(e)
}

const handleTimelineMouseUp = () => {
  if (isDragging.value && dragType.value === 'playhead') {
    isDragging.value = false
    dragType.value = null
  }
}

const updatePlayhead = (e) => {
  const rect = e.currentTarget.getBoundingClientRect()
  const x = e.clientX - rect.left
  const percent = Math.max(0, Math.min(1, x / rect.width))
  const time = percent * duration.value
  currentTime.value = time
  if (mediaRef.value) {
    mediaRef.value.currentTime = time
  }
}

const handleWaveformMouseDown = (e) => {
  const rect = waveformRef.value.getBoundingClientRect()
  const x = e.clientX - rect.left
  const percent = x / rect.width
  const clickTime = percent * duration.value
  const start = clipStartTime.value
  const end = clipEndTime.value

  if (clickTime < start + 0.1) {
    isDragging.value = true
    dragType.value = 'left'
  } else if (clickTime > end - 0.1) {
    isDragging.value = true
    dragType.value = 'right'
  } else if (clickTime >= start && clickTime <= end) {
    isDragging.value = true
    dragType.value = 'move'
  } else {
    currentTime.value = clickTime
  }
}

const handleWaveformMouseMove = (e) => {
  if (!isDragging.value) return

  const rect = waveformRef.value.getBoundingClientRect()
  const x = e.clientX - rect.left
  const percent = Math.max(0, Math.min(1, x / rect.width))
  const time = percent * duration.value

  if (dragType.value === 'left') {
    clipStartTime.value = Math.max(0, Math.min(time, clipEndTime.value - 0.1))
  } else if (dragType.value === 'right') {
    clipEndTime.value = Math.max(clipStartTime.value + 0.1, Math.min(time, duration.value))
  } else if (dragType.value === 'move') {
    const dur = clipEndTime.value - clipStartTime.value
    clipStartTime.value = Math.max(0, Math.min(time - dur / 2, duration.value - dur))
    clipEndTime.value = clipStartTime.value + dur
  }

  currentTime.value = time
}

const handleWaveformMouseUp = () => {
  isDragging.value = false
  dragType.value = null
}

// 全局鼠标事件（手柄拖拽时鼠标可能移出组件）
const handleGlobalMouseMove = (e) => {
  if (!isDragging.value) return

  // 裁剪框拖拽
  if (cropDragType.value) {
    handleCropMouseMove(e)
    return
  }

  // 时间剪辑手柄拖拽 — 需要根据容器计算
  if (dragType.value === 'left' || dragType.value === 'right' || dragType.value === 'move') {
    const container = isAudio.value ? waveformRef.value : timelineRef.value
    if (!container) return

    const rect = container.getBoundingClientRect()
    const x = e.clientX - rect.left
    const percent = Math.max(0, Math.min(1, x / rect.width))
    const time = percent * duration.value

    if (dragType.value === 'left') {
      clipStartTime.value = Math.max(0, Math.min(time, clipEndTime.value - 0.1))
    } else if (dragType.value === 'right') {
      clipEndTime.value = Math.max(clipStartTime.value + 0.1, Math.min(time, duration.value))
    } else if (dragType.value === 'move') {
      const dur = clipEndTime.value - clipStartTime.value
      clipStartTime.value = Math.max(0, Math.min(time - dur / 2, duration.value - dur))
      clipEndTime.value = clipStartTime.value + dur
    }

    currentTime.value = time
    if (mediaRef.value) {
      mediaRef.value.currentTime = time
    }
  }
}

const handleGlobalMouseUp = () => {
  isDragging.value = false
  dragType.value = null
  cropDragType.value = null
}

// === 画面裁剪拖拽 ===
const startCropDrag = (type, e) => {
  cropDragType.value = type
  isDragging.value = true
  cropDragStart.value = {
    mx: e.clientX,
    my: e.clientY,
    rect: { ...cropRect.value }
  }
  e.preventDefault()
}

const handleCropMouseMove = (e) => {
  if (!cropDragType.value || !playerContainerRef.value) return

  const containerRect = playerContainerRef.value.getBoundingClientRect()
  // 裁剪叠加层仅覆盖视频渲染区域，需用渲染区域尺寸计算百分比偏移
  const renderW = containerRect.width * (videoRenderRect.value.width / 100)
  const renderH = containerRect.height * (videoRenderRect.value.height / 100)

  const dx = (e.clientX - cropDragStart.value.mx) / renderW
  const dy = (e.clientY - cropDragStart.value.my) / renderH

  const start = cropDragStart.value.rect
  let { x, y, w, h } = start
  const MIN = 0.1

  // 获取目标比例
  let targetAspect = null
  if (aspectLockEnabled.value) {
    if (aspectRatio.value === 'original') {
      // 使用当前原始比例
      targetAspect = currentOriginalAspect.value
    } else {
      targetAspect = aspectRatios[aspectRatio.value]
    }
  }

  // 根据是否锁定比例应用不同的拖拽逻辑
  if (cropDragType.value === 'move') {
    // 移动模式：不管是否锁定比例，都只移动位置不改变尺寸
    w = start.w
    h = start.h
    x = Math.max(0, Math.min(start.x + dx, 1 - w))
    y = Math.max(0, Math.min(start.y + dy, 1 - h))
  } else if (aspectLockEnabled.value && targetAspect && videoWidth.value && videoHeight.value) {
    // === 锁定比例模式 ===
    // targetAspect 是像素比例(如 16:9 = 1.78)，需要转换为百分比比例
    // percentAspect = targetAspect * (videoHeight / videoWidth)
    const percentAspect = targetAspect * (videoHeight.value / videoWidth.value)

    // 简化逻辑：基于拖动方向增量，按比例缩放
    let delta = 0

    // 计算增量：哪个方向拖动大就用哪个
    if (Math.abs(dx) > Math.abs(dy)) {
      // 水平拖动为主
      const edgeExpand = (cropDragType.value === 'mr' || cropDragType.value === 'tr' || cropDragType.value === 'br')
      delta = dx * start.w * 2
      if (!edgeExpand) delta = -delta
    } else {
      // 垂直拖动为主
      const edgeExpand = (cropDragType.value === 'bc' || cropDragType.value === 'bl' || cropDragType.value === 'br')
      delta = dy * start.h * 2
      if (!edgeExpand) delta = -delta
    }

    // 基于宽度计算，保持百分比比例
    let newW = start.w + delta
    newW = Math.max(MIN, Math.min(newW, 1))
    const newH = newW / percentAspect

    if (newH > 1) {
      // 高度超出边界，以高度为基准
      w = start.h * percentAspect
      h = start.h
    } else {
      w = newW
      h = newH
    }

    // 调整位置保持对应边不动
    switch (cropDragType.value) {
      case 'tl': // 左上角 - 保持右下角
        x = start.x + start.w - w
        y = start.y + start.h - h
        break
      case 'tc': // 上边中心 - 保持下边
        y = start.y + start.h - h
        x = start.x + (start.w - w) / 2
        break
      case 'tr': // 右上角 - 保持左下角
        y = start.y + start.h - h
        break
      case 'ml': // 左边中心 - 保持右边
        x = start.x + start.w - w
        y = start.y + (start.h - h) / 2
        break
      case 'mr': // 右边中心 - 保持左边
        y = start.y + (start.h - h) / 2
        break
      case 'bl': // 左下角 - 保持右上角
        x = start.x + start.w - w
        break
      case 'bc': // 下边中心 - 保持上边
        x = start.x + (start.w - w) / 2
        break
      case 'br': // 右下角 - 保持左上角
        // 默认位置不变
        break
    }
  } else {
    // === 自由模式 ===
    switch (cropDragType.value) {
      case 'tl':
        x = Math.max(0, Math.min(x + dx, x + w - MIN))
        y = Math.max(0, Math.min(y + dy, y + h - MIN))
        w = start.x + start.w - x
        h = start.y + start.h - y
        break
      case 'tc':
        y = Math.max(0, Math.min(y + dy, y + h - MIN))
        h = start.y + start.h - y
        break
      case 'tr':
        w = Math.max(MIN, Math.min(start.w + dx, 1 - start.x))
        y = Math.max(0, Math.min(y + dy, y + h - MIN))
        h = start.y + start.h - y
        break
      case 'ml':
        x = Math.max(0, Math.min(x + dx, x + w - MIN))
        w = start.x + start.w - x
        break
      case 'mr':
        w = Math.max(MIN, Math.min(start.w + dx, 1 - start.x))
        break
      case 'bl':
        x = Math.max(0, Math.min(x + dx, x + w - MIN))
        w = start.x + start.w - x
        h = Math.max(MIN, Math.min(start.h + dy, 1 - start.y))
        break
      case 'bc':
        h = Math.max(MIN, Math.min(start.h + dy, 1 - start.y))
        break
      case 'br':
        w = Math.max(MIN, Math.min(start.w + dx, 1 - start.x))
        h = Math.max(MIN, Math.min(start.h + dy, 1 - start.y))
        break
      case 'move':
        const newW = start.w
        const newH = start.h
        let newX = start.x + dx
        let newY = start.y + dy
        newX = Math.max(0, Math.min(newX, 1 - newW))
        newY = Math.max(0, Math.min(newY, 1 - newH))
        x = newX
        y = newY
        w = newW
        h = newH
        break
    }

    // 边界约束
    if (x + w > 1) w = 1 - x
    if (y + h > 1) h = 1 - y
    if (x < 0) x = 0
    if (y < 0) y = 0
  }

  cropRect.value = { x, y, w, h }

  // 如果选择了"原始比例"，更新当前比例（转换为像素比例）
  if (aspectRatio.value === 'original' && w > 0 && h > 0 && videoWidth.value && videoHeight.value) {
    const percentAspect = w / h
    currentOriginalAspect.value = percentAspect * (videoWidth.value / videoHeight.value)
  }
}

// === 操作 ===
const handleReset = () => {
  if (activeMode.value === 'trim') {
    clipStartTime.value = 0
    clipEndTime.value = duration.value
    currentTime.value = 0
    pendingTrim.value = null
  } else if (activeMode.value === 'crop') {
    cropRect.value = { x: 0, y: 0, w: 1, h: 1 }
    pendingCrop.value = null
    // 重置比例锁定状态
    aspectLockEnabled.value = true
    aspectRatio.value = 'original'
    if (videoWidth.value > 0 && videoHeight.value > 0) {
      currentOriginalAspect.value = videoWidth.value / videoHeight.value
    }
  }
}

const handleSave = async () => {
  if (!canSave.value) return

  isProcessing.value = true

  try {
    const filePath = cleanFilePath(props.filePath)

    // 确定需要执行的操作：当前模式 + 暂存的另一模式参数
    const doTrim = activeMode.value === 'trim' || pendingTrim.value
    const doCrop = (activeMode.value === 'crop' && props.mediaType === 'video') || pendingCrop.value

    // 获取实际参数
    const trimStart = activeMode.value === 'trim' ? clipStartTime.value : (pendingTrim.value?.startTime ?? 0)
    const trimEnd = activeMode.value === 'trim' ? clipEndTime.value : (pendingTrim.value?.endTime ?? duration.value)

    console.log('[MediaClipper] handleSave 开始:', {
      filePath,
      propsFilePath: props.filePath,
      mediaType: props.mediaType,
      isAudio: isAudio.value,
      doTrim,
      doCrop,
      trimStart,
      trimEnd
    })
    const cropX = activeMode.value === 'crop' ? cropRect.value.x : (pendingCrop.value?.x ?? 0)
    const cropY = activeMode.value === 'crop' ? cropRect.value.y : (pendingCrop.value?.y ?? 0)
    const cropW = activeMode.value === 'crop' ? cropRect.value.w : (pendingCrop.value?.w ?? 1)
    const cropH = activeMode.value === 'crop' ? cropRect.value.h : (pendingCrop.value?.h ?? 1)

    // 先执行时间剪辑（如果需要）
    if (doTrim) {
      const trimDuration = trimEnd - trimStart
      if (trimDuration > 0.1) {
        const response = await mediaClipApi.clip({
          file_path: filePath,
          start_time: trimStart,
          end_time: trimEnd,
          replace_original: true
        })

        if (response.code !== 200) {
          ElMessage.error(response.message || '时间剪辑失败')
          return
        }
        console.log('[MediaClipper] 准备 emit clipped 事件:', { filePath, startTime: trimStart, endTime: trimEnd, duration: trimDuration })
        emit('clipped', {
          filePath: filePath,
          startTime: trimStart,
          endTime: trimEnd,
          duration: trimDuration
        })
        console.log('[MediaClipper] clipped 事件已 emit')
      }
    }

    // 再执行画面裁剪（如果需要）
    if (doCrop && (cropW < 0.99 || cropH < 0.99)) {
      const response = await mediaClipApi.crop({
        file_path: filePath,
        x: cropX,
        y: cropY,
        width: cropW,
        height: cropH,
        replace_original: true
      })

      if (response.code !== 200) {
        ElMessage.error(response.message || '画面裁剪失败')
        return
      }
      emit('cropped', {
        filePath: filePath,
        x: cropX,
        y: cropY,
        width: cropW,
        height: cropH,
        originalWidth: response.data.original_width,
        originalHeight: response.data.original_height
      })
    }

    activeMode.value = null
    pendingTrim.value = null
    pendingCrop.value = null
  } catch (error) {
    console.error('操作失败:', error)
    ElMessage.error('操作失败：' + (error.message || '未知错误'))
  } finally {
    isProcessing.value = false
  }
}

// === 时间格式化 ===
const formatTime = (seconds) => {
  if (!seconds) return '00:00'
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  const ms = Math.floor((seconds % 1) * 100)
  return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}.${ms.toString().padStart(2, '0')}`
}

// === 生命周期 ===
let resizeObserver = null

onMounted(() => {
  window.addEventListener('mousemove', handleGlobalMouseMove)
  window.addEventListener('mouseup', handleGlobalMouseUp)
  if (props.filePath) {
    loadMediaInfo()
  }
  // 监听容器尺寸变化，更新视频渲染区域
  if (playerContainerRef.value) {
    resizeObserver = new ResizeObserver(() => updateVideoRenderRect())
    resizeObserver.observe(playerContainerRef.value)
  }
})

onUnmounted(() => {
  window.removeEventListener('mousemove', handleGlobalMouseMove)
  window.removeEventListener('mouseup', handleGlobalMouseUp)
  if (resizeObserver) {
    resizeObserver.disconnect()
    resizeObserver = null
  }
})

// watch mode prop → reset activeMode
watch(() => props.mode, (newMode) => {
  activeMode.value = newMode || props.defaultMode || 'trim'
})

// filePath 变化时重新加载
watch(() => props.filePath, (newPath) => {
  if (newPath) {
    activeMode.value = props.defaultMode || 'trim'
    loadMediaInfo()
  }
})

// 暴露方法
defineExpose({
  switchMode,
  handleReset
})
</script>

<style scoped lang="scss">
.media-clipper {
  position: relative;
  margin-top: var(--space-xs);
  min-height: 400px;
}

/* === 播放器工具栏 === */
.player-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px;
  background: var(--bg-muted);
  border-radius: var(--radius-sm);
  border: 1px solid var(--color-border-strong);
  gap: var(--space-sm);
}

.dark-theme .player-toolbar {
  background: var(--bg-card-solid);
  border-color: var(--color-border-strong);
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}

.volume-slider {
  width: 80px;
}

.volume-icon {
  font-size: var(--font-size-lg);
  color: var(--color-text-secondary);
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 6px;
}

/* === 媒体播放器 === */
.media-player-container {
  margin: var(--space-sm) 0;
  border-radius: var(--radius-sm);
  overflow: hidden;
  background: #000;
  position: relative;
}

.media-player {
  width: 100%;
  display: block;
}

.video-player {
  max-height: 400px;
  object-fit: contain;
}

.audio-player {
  height: 40px;
}

/* === 画面裁剪叠加层 === */
.crop-overlay {
  z-index: 20;
  cursor: crosshair;
}

.crop-mask {
  position: absolute;
  background: rgba(0, 0, 0, 0.5);
  pointer-events: none;
}

.dark-theme .crop-mask {
  background: rgba(0, 0, 0, 0.7);
}

.crop-mask-top {
  top: 0;
  left: 0;
  right: 0;
}

.crop-mask-bottom {
  left: 0;
  right: 0;
  bottom: 0;
}

.crop-mask-left {
  top: 0;
  bottom: 0;
  left: 0;
}

.crop-mask-right {
  top: 0;
  bottom: 0;
  right: 0;
}

.crop-box {
  position: absolute;
  border: 2px solid var(--color-primary);
  cursor: move;
  z-index: 21;
}

.crop-handle {
  position: absolute;
  width: 10px;
  height: 10px;
  background: var(--color-primary);
  border: 1px solid var(--bg-card-solid);
  border-radius: 2px;
  z-index: 22;
}

.dark-theme .crop-handle {
  border-color: var(--color-border-strong);
}

.crop-handle-tl { top: -5px; left: -5px; cursor: nw-resize; }
.crop-handle-tc { top: -5px; left: 50%; margin-left: -5px; cursor: n-resize; }
.crop-handle-tr { top: -5px; right: -5px; cursor: ne-resize; }
.crop-handle-ml { top: 50%; margin-top: -5px; left: -5px; cursor: w-resize; }
.crop-handle-mr { top: 50%; margin-top: -5px; right: -5px; cursor: e-resize; }
.crop-handle-bl { bottom: -5px; left: -5px; cursor: sw-resize; }
.crop-handle-bc { bottom: -5px; left: 50%; margin-left: -5px; cursor: s-resize; }
.crop-handle-br { bottom: -5px; right: -5px; cursor: se-resize; }

.crop-size-label {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  background: rgba(0, 0, 0, 0.7);
  color: #fff;
  padding: 2px 8px;
  border-radius: 3px;
  font-size: var(--font-size-sm);
  white-space: nowrap;
  pointer-events: none;
  z-index: 23;
}

.dark-theme .crop-size-label {
  background: rgba(255, 255, 255, 0.9);
  color: #1a1a1a;
}

.aspect-lock-control {
  position: absolute;
  top: -36px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 6px;
  background: var(--bg-card-solid);
  padding: 3px 6px;
  border-radius: 4px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  z-index: 25;
}

.dark-theme .aspect-lock-control {
  background: var(--bg-card);
  border: 1px solid var(--color-border-strong);
}

.aspect-ratio-select {
  width: 90px;
}

.aspect-ratio-select .el-input__wrapper {
  font-size: 11px;
}

/* === 画面裁剪控制面板 === */
.crop-control-panel {
  position: relative;
  margin-top: var(--space-sm);
  padding: 10px;
  background: var(--bg-muted);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border-strong);
}

.dark-theme .crop-control-panel {
  background: var(--bg-card-solid);
  border-color: var(--color-border-strong);
}

.crop-control-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.crop-size-display {
  margin-left: auto;
  font-family: 'Courier New', monospace;
  font-size: var(--font-size-sm);
  color: var(--color-text-primary);
  background: var(--bg-page);
  padding: 2px 8px;
  border-radius: 3px;
}

.dark-theme .crop-size-display {
  background: var(--bg-card);
}

/* === 时间剪辑面板 === */
.trim-panel {
  position: relative;
  margin-top: var(--space-sm);
  padding: 10px;
  background: var(--bg-muted);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border-strong);
}

.dark-theme .trim-panel {
  background: var(--bg-card-solid);
  border-color: var(--color-border-strong);
}

.audio-timeline,
.video-timeline {
  position: relative;
  user-select: none;
}

.frame-ruler {
  display: flex;
  justify-content: space-between;
  padding: var(--space-xs) 0;
  font-size: 10px;
  color: var(--color-text-secondary);
  border-bottom: 1px solid var(--color-border-strong);
}

.timeline-track {
  height: 50px;
  background: var(--bg-page);
  border-radius: var(--radius-sm);
  cursor: pointer;
  position: relative;
  overflow: hidden;
}

.dark-theme .timeline-track {
  background: var(--bg-card-solid);
}

.waveform-container {
  position: relative;
  height: 80px;
  background: var(--bg-page);
  border-radius: var(--radius-sm);
  cursor: pointer;
  overflow: hidden;
}

.dark-theme .waveform-container {
  background: var(--bg-card-solid);
}

.waveform-canvas {
  width: 100%;
  height: 100%;
}

/* 播放头 */
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
  top: -22px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(255, 68, 68, 0.9);
  color: white;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 10px;
  white-space: nowrap;
}

/* 剪辑区域 */
.clip-region {
  position: absolute;
  top: 0;
  bottom: 0;
  background: var(--color-primary-bg);
  border-left: 2px solid var(--color-primary);
  border-right: 2px solid var(--color-primary);
  cursor: move;
  z-index: 5;
  transition: background var(--transition-fast);
}

.clip-region:hover {
  background: rgba(64, 158, 255, 0.25);
}

.dark-theme .clip-region {
  background: rgba(0, 217, 255, 0.15);
}

.dark-theme .clip-region:hover {
  background: rgba(0, 217, 255, 0.25);
}

.clip-handle {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  width: var(--space-base);
  height: var(--space-2xl);
  background: var(--color-primary);
  border-radius: 3px;
  cursor: ew-resize;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--bg-card-solid);
  opacity: 0;
  transition: opacity 0.2s;
}

.dark-theme .clip-handle {
  color: #1a1a1a;
}

.clip-region:hover .clip-handle {
  opacity: 1;
}

.clip-handle-left { left: -8px; }
.clip-handle-right { right: -8px; }

.clip-duration-label {
  position: absolute;
  top: -22px;
  left: 50%;
  transform: translateX(-50%);
  background: var(--color-primary);
  color: var(--bg-card-solid);
  padding: 1px var(--space-sm);
  border-radius: 3px;
  font-size: var(--font-size-xs);
  white-space: nowrap;
  opacity: 0;
  transition: opacity 0.2s;
}

.dark-theme .clip-duration-label {
  color: #1a1a1a;
}

.clip-region:hover .clip-duration-label {
  opacity: 1;
}

/* 时间显示 */
.time-display {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  padding: var(--space-sm) 0 0;
  font-size: var(--font-size-sm);
}

.time-label {
  color: var(--color-text-secondary);
}

.time-value {
  font-family: 'Courier New', monospace;
  color: var(--color-text-primary);
  font-weight: var(--font-weight-medium);

  &.highlight {
    color: var(--color-primary);
    font-weight: var(--font-weight-semibold);
  }
}
</style>

<style scoped>
.pending-badge {
  color: var(--color-warning);
  margin-left: 2px;
  font-size: var(--font-size-xs);
}
</style>
