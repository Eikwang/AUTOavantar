<template>
  <div class="smart-cut-view">
    <el-card class="page-header">
      <h2 class="page-title">智能裁剪</h2>
      <p class="description">上传视频，智能识别分割点，快速提取精彩片段</p>
    </el-card>

    <!-- 历史记录区域 - 始终显示在顶部 -->
    <el-card class="history-section" v-loading="loadingHistory">
      <template #header>
        <div class="card-header">
          <span><el-icon><Clock /></el-icon> 历史记录</span>
          <el-button type="primary" text @click="loadHistory">
            <el-icon><RefreshLeft /></el-icon>
            刷新
          </el-button>
        </div>
      </template>

      <div v-if="historyList.length === 0" class="history-empty">
        <el-empty description="暂无历史记录" :image-size="80" />
      </div>

      <div v-else class="history-grid">
        <div
          v-for="item in historyList"
          :key="item.task_id"
          class="history-card"
          @click="restoreHistory(item)"
        >
          <div class="history-icon">
            <el-icon :size="32"><Document /></el-icon>
          </div>
          <div class="history-info">
            <div class="history-name">
              {{ item.video_name }}
              <el-tag
                :type="getStatusTagType(item.status)"
                size="small"
                class="status-tag"
              >{{ getStatusLabel(item.status) }}</el-tag>
            </div>
            <div class="history-meta">
              <span v-if="item.status !== 'uploaded'">{{ item.segments_count || (item.segments_info ? item.segments_info.length : 0) }} 个片段</span>
              <span v-else>未裁剪</span>
              <span>{{ formatDuration(item.video_duration) }}</span>
            </div>
            <div class="history-time">{{ formatDateTime(item.created_at) }}</div>
          </div>
          <el-button
            type="danger"
            size="small"
            circle
            class="history-delete"
            @click.stop="deleteHistory(item.task_id)"
          >
            <el-icon><Delete /></el-icon>
          </el-button>
        </div>
      </div>
    </el-card>

    <!-- 上传区域 -->
    <el-card v-if="!videoInfo" class="upload-section">
      <el-upload
        ref="uploadRef"
        class="video-uploader"
        drag
        :auto-upload="false"
        :show-file-list="false"
        :on-change="handleFileChange"
        accept=".mp4,.avi,.mov,.mkv"
      >
        <el-icon class="el-icon--upload"><upload-filled /></el-icon>
        <div class="el-upload__text">
          拖拽视频文件到此处，或 <em>点击选择文件</em>
        </div>
        <template #tip>
          <div class="el-upload__tip">
            支持 mp4、avi、mov 格式，最大 2GB
          </div>
        </template>
      </el-upload>
    </el-card>

    <!-- 上传进度 -->
    <el-card v-if="uploading" class="upload-progress">
      <div class="progress-content">
        <el-icon class="is-loading" :size="32"><Loading /></el-icon>
        <span>正在上传视频...</span>
        <el-progress :percentage="uploadProgress" :stroke-width="8" />
      </div>
    </el-card>

    <!-- 视频预览和配置 -->
    <div v-if="videoInfo && !uploading" class="video-section">
      <!-- 左侧：视频预览 -->
      <el-card class="video-preview">
        <template #header>
          <div class="card-header">
            <span>视频预览</span>
            <div class="header-actions">
              <el-button v-if="isFromHistory" type="primary" text @click="resetToHistory">
                <el-icon><Back /></el-icon>
                返回历史
              </el-button>
              <el-button type="primary" text @click="resetUpload">
                <el-icon><RefreshLeft /></el-icon>
                重新选择
              </el-button>
            </div>
          </div>
        </template>

        <div class="video-container">
          <video
            ref="videoPlayer"
            :src="videoUrl"
            controls
            class="video-player"
            @loadedmetadata="handleVideoLoaded"
          ></video>
        </div>
        <div class="video-actions-bar">
          <el-button type="warning" size="small" @click="openClipDialog(videoInfo.video_path, 'video')">
            <el-icon><Scissor /></el-icon> 剪辑视频
          </el-button>
        </div>

        <div class="video-info">
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="文件名">{{ videoInfo.video_name }}</el-descriptions-item>
            <el-descriptions-item label="时长">{{ formatDuration(videoInfo.duration) }}</el-descriptions-item>
            <el-descriptions-item label="分辨率">{{ videoInfo.width }} × {{ videoInfo.height }}</el-descriptions-item>
            <el-descriptions-item label="帧率">{{ videoInfo.fps }} fps</el-descriptions-item>
            <el-descriptions-item label="总帧数">{{ videoInfo.total_frames }}</el-descriptions-item>
          </el-descriptions>
        </div>
      </el-card>

      <!-- 右侧：参数配置 -->
      <el-card class="config-panel">
        <template #header>
          <span>裁剪配置</span>
        </template>

        <el-form :model="config" label-width="120px">
          <el-form-item label="场景识别">
            <el-tag type="success" effect="plain">默认开启</el-tag>
            <span class="config-hint">检测镜头切换点</span>
          </el-form-item>

          <el-divider content-position="left">增强识别</el-divider>

          <el-form-item label="光线明暗">
            <el-switch v-model="config.enable_brightness" />
            <span class="config-hint">检测亮度变化</span>
          </el-form-item>

          <el-form-item label="肢体动作">
            <el-switch v-model="config.enable_pose" />
            <span class="config-hint">检测姿态变化</span>
          </el-form-item>

          <el-form-item label="手势变化">
            <el-switch v-model="config.enable_motion" />
            <span class="config-hint">检测手势动作</span>
          </el-form-item>

          <el-form-item label="说话停顿">
            <el-switch v-model="config.enable_silence" />
            <span class="config-hint">检测静音点</span>
          </el-form-item>

          <el-divider content-position="left">参数设置</el-divider>

          <el-form-item label="最短片段时长">
            <el-slider
              v-model="config.min_segment_duration"
              :min="3"
              :max="240"
              :step="1"
              show-input
              :format-tooltip="(val) => `${val} 秒`"
            />
          </el-form-item>

          <el-form-item class="action-buttons-row">
            <el-button
              type="primary"
              size="large"
              :loading="processing"
              @click="startCutting"
            >
              开始裁剪
            </el-button>
            <el-button
              size="large"
              :loading="extractingOriginalAudio"
              @click="extractOriginalAudio"
            >
              提取音频
            </el-button>
          </el-form-item>
        </el-form>
      </el-card>
    </div>

    <!-- 裁剪进度 -->
    <el-card v-if="processing" class="cutting-progress">
      <div class="progress-header">
        <span>正在智能裁剪...</span>
        <el-tag :type="progressStatus === 'exception' ? 'danger' : 'info'">{{ progressInfo.current_stage || '准备中...' }}</el-tag>
      </div>
      <el-progress
        :percentage="progressInfo.progress"
        :status="progressStatus"
        :stroke-width="12"
      />
      <div class="progress-details">
        <span>已处理：{{ progressInfo.processed_frames }} / {{ progressInfo.total_frames }} 帧</span>
        <span v-if="progressInfo.estimated_time">预计剩余：{{ progressInfo.estimated_time }}</span>
      </div>
      <!-- 失败时显示重试按钮 -->
      <div v-if="taskFailed" class="progress-error">
        <el-alert type="error" :closable="false">
          <template #title>
            <span>裁剪失败：{{ errorMessage }}</span>
          </template>
        </el-alert>
        <el-button type="primary" @click="retryCutting" class="retry-button">
          <el-icon><RefreshLeft /></el-icon>
          重试
        </el-button>
      </div>
    </el-card>

    <!-- 片段预览 -->
    <el-card v-if="segments.length > 0" class="segments-section">
      <template #header>
        <div class="card-header">
          <span>裁剪片段（共 {{ segments.length }} 个）</span>
          <div>
            <el-button type="primary" text @click="resetUpload">
              <el-icon><RefreshLeft /></el-icon>
              重新裁剪
            </el-button>
          </div>
        </div>
      </template>

      <div class="segments-grid">
        <div
          v-for="seg in segments"
          :key="seg.segment_id"
          class="segment-card"
          :class="{ 'segment-selected': selectedSegments.includes(seg.segment_id) }"
          @click="previewSegment(seg)"
        >
          <div class="segment-thumbnail">
            <img :src="`/files/${seg.thumbnail}`" :alt="seg.reason_label" />
            <span class="segment-duration">{{ formatDuration(seg.duration) }}</span>
            <el-tag class="segment-reason" :type="getReasonTagType(seg.reason)" size="small">
              {{ seg.reason_label }}
            </el-tag>
            <el-button
              class="segment-delete-btn"
              type="danger"
              size="small"
              circle
              @click.stop="deleteSegment(seg.segment_id)"
            >
              <el-icon><Delete /></el-icon>
            </el-button>
            <el-button
              class="segment-select-btn"
              :type="selectedSegments.includes(seg.segment_id) ? 'primary' : 'default'"
              size="small"
              circle
              @click.stop="toggleSegmentSelect(seg.segment_id)"
            >
              <el-icon>
                <component :is="selectedSegments.includes(seg.segment_id) ? 'Check' : 'Plus'" />
              </el-icon>
            </el-button>
          </div>
          <div class="segment-info">
            <span>{{ formatDuration(seg.start_time) }} - {{ formatDuration(seg.end_time) }}</span>
          </div>
        </div>
      </div>

      <!-- 批量操作 -->
      <div v-if="selectedSegments.length > 0" class="batch-actions">
        <el-button type="primary" @click="batchAddToPending">
          批量添加（{{ selectedSegments.length }} 个）
        </el-button>
        <el-button @click="clearSelection">取消选择</el-button>
      </div>
    </el-card>

    <!-- 片段预览弹窗 -->
    <el-dialog
      v-model="previewDialogVisible"
      :title="previewSegmentInfo?.reason_label || '片段预览'"
      width="600px"
      destroy-on-close
      @opened="onPreviewOpened"
      @closed="onPreviewClosed"
    >
      <div class="preview-dialog-content">
        <div class="preview-video-container">
          <video
            ref="previewVideoPlayer"
            v-if="previewSegmentInfo"
            :src="`/files/${previewSegmentInfo.video_path}${previewSegmentInfo.timestamp ? '?t=' + previewSegmentInfo.timestamp : ''}`"
            controls
            autoplay
            class="preview-video"
          ></video>
        </div>
        <div class="preview-actions-bar">
          <el-button type="warning" size="small" @click="openClipDialog(previewSegmentInfo.video_path, 'video')">
            <el-icon><Scissor /></el-icon> 剪辑此片段
          </el-button>
        </div>
        <div v-if="previewSegmentInfo" class="preview-info">
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="时长">{{ formatDuration(previewSegmentInfo.duration) }}</el-descriptions-item>
            <el-descriptions-item label="时间范围">{{ formatDuration(previewSegmentInfo.start_time) }} - {{ formatDuration(previewSegmentInfo.end_time) }}</el-descriptions-item>
            <el-descriptions-item label="分割原因">{{ previewSegmentInfo.reason_label }}</el-descriptions-item>
          </el-descriptions>
        </div>
      </div>
      <template #footer>
        <el-button @click="previewDialogVisible = false">关闭</el-button>
        <el-button type="primary" @click="addToPending(previewSegmentInfo)">添加到待处理</el-button>
        <el-button type="success" @click="extractAudio(previewSegmentInfo)">提取音频</el-button>
      </template>
    </el-dialog>

    <!-- 待处理列表 -->
    <el-card v-if="pendingSegments.length > 0" class="pending-section">
      <template #header>
        <div class="card-header">
          <span>待处理片段（{{ pendingSegments.length }} 个）</span>
          <el-button type="danger" text @click="clearPending">
            <el-icon><Delete /></el-icon>
            清空
          </el-button>
        </div>
      </template>

      <div class="pending-list">
        <div v-for="seg in pendingSegments" :key="seg.segment_id" class="pending-item">
          <div class="pending-thumbnail">
            <img :src="`/files/${seg.thumbnail}`" :alt="seg.reason_label" />
          </div>
          <div class="pending-info">
            <span class="pending-name">{{ seg.segment_id }}</span>
            <span class="pending-duration">{{ formatDuration(seg.duration) }}</span>
          </div>
          <el-button type="danger" size="small" circle @click="removeFromPending(seg.segment_id)">
            <el-icon><Close /></el-icon>
          </el-button>
        </div>
      </div>

      <div class="pending-actions">
        <el-button type="primary" @click="showMergeDialog">
          <el-icon><VideoPlay /></el-icon>
          合成视频
        </el-button>
        <el-button @click="saveToMaterial">
          <el-icon><FolderAdd /></el-icon>
          保存到素材库
        </el-button>
      </div>
    </el-card>

    <!-- 合成配置弹窗 -->
    <el-dialog
      v-model="mergeDialogVisible"
      title="合成视频配置"
      width="600px"
      destroy-on-close
    >
      <el-form :model="mergeConfig" label-width="100px">
        <el-form-item label="输出名称">
          <el-input v-model="mergeConfig.output_name" placeholder="请输入输出文件名" />
        </el-form-item>
        <el-form-item label="分辨率">
          <el-radio-group v-model="mergeConfig.resolution">
            <el-radio-button value="720p">720p</el-radio-button>
            <el-radio-button value="1080p">1080p</el-radio-button>
            <el-radio-button value="2K">2K</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="帧率">
          <el-radio-group v-model="mergeConfig.fps">
            <el-radio-button :value="30">30 fps</el-radio-button>
            <el-radio-button :value="60">60 fps</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="转场效果">
          <div class="transition-settings">
            <!-- 转场分类 -->
            <div class="transition-row">
              <el-select v-model="mergeConfig.transitionType" placeholder="选择分类" @change="handleTransitionTypeChange" class="transition-select">
                <el-option v-for="category in transitionCategories" :key="category" :label="category" :value="category" />
              </el-select>
              <el-select v-model="mergeConfig.transition" placeholder="选择效果" :disabled="mergeConfig.transitionRandom" class="transition-select">
                <el-option v-for="effect in currentTransitionEffects" :key="effect.value" :label="effect.name" :value="effect.value" />
              </el-select>
            </div>
            <!-- 随机效果 -->
            <div class="transition-random">
              <el-checkbox v-model="mergeConfig.transitionRandom" @change="handleTransitionRandomChange">
                启用随机效果
              </el-checkbox>
              <el-checkbox v-if="mergeConfig.transitionRandom" v-model="mergeConfig.transitionRandomAll">
                每次转场都随机
              </el-checkbox>
            </div>
            <!-- 转场时长 -->
            <div class="transition-duration">
              <span class="duration-label">转场时长：</span>
              <el-slider
                v-model="mergeConfig.transitionDuration"
                :min="0.5"
                :max="5.0"
                :step="0.1"
                show-input
                style="width: 200px;"
              />
              <span>秒</span>
            </div>
          </div>
        </el-form-item>
        <el-form-item label="背景音乐">
          <el-select v-model="mergeConfig.bgm_path" placeholder="不添加BGM" clearable style="width: 100%">
            <el-option v-for="bgm in bgmList" :key="bgm.bgm_id" :label="bgm.bgm_name" :value="bgm.path" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="mergeDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="merging" @click="mergeVideos">
          开始合成
        </el-button>
      </template>
    </el-dialog>

    <!-- 音频播放弹窗 -->
    <el-dialog
      v-model="audioDialogVisible"
      title="音频播放"
      width="500px"
      destroy-on-close
      @closed="onAudioDialogClosed"
    >
      <div class="audio-dialog-content">
        <div class="audio-player-container">
          <audio
            ref="audioPlayer"
            v-if="audioInfo"
            :src="`/files/${audioInfo.audio_path}`"
            controls
            class="audio-player"
          ></audio>
        </div>
        <div v-if="audioInfo" class="audio-info">
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="来源片段">{{ audioInfo.source_segment }}</el-descriptions-item>
            <el-descriptions-item label="时长">{{ formatDuration(audioInfo.duration) }}</el-descriptions-item>
          </el-descriptions>
        </div>
      </div>
      <template #footer>
        <el-button @click="audioDialogVisible = false">关闭</el-button>
        <el-button type="primary" @click="addToReference">添加参考</el-button>
        <el-button type="success" @click="addToBGM">添加BGM</el-button>
      </template>
    </el-dialog>

    <!-- 媒体剪辑对话框 -->
    <el-dialog
      v-model="showClipDialog"
      :title="clipMediaType === 'video' ? '视频剪辑' : '音频剪辑'"
      width="900px"
      :class="['media-clip-dialog', { 'dark-theme': isDarkTheme }]"
      :close-on-click-modal="false"
    >
      <div class="media-clip-container">
        <div v-if="clipItemPath" class="media-clip-content">
          <!-- 剪辑器（自带播放器） -->
          <MediaClipper
            v-if="clipItemPath"
            :file-path="clipItemPath"
            :media-type="clipMediaType"
            :is-dark-theme="isDarkTheme"
            default-mode="trim"
            @clipped="clipMediaType === 'video' ? handleVideoClipped : handlePreviewSegmentClipped"
            @cropped="handleVideoCropped"
          />
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, inject } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  UploadFilled,
  Loading,
  RefreshLeft,
  Scissor,
  Check,
  Plus,
  Delete,
  Close,
  VideoPlay,
  FolderAdd,
  Clock,
  Document,
  Back,
  Headset
} from '@element-plus/icons-vue'
import { smartCutApi, materialApi } from '@/services/api'
import MediaClipper from '@/components/MediaClipper.vue'

const router = useRouter()

// 当前任务ID
const currentTaskId = ref('')

// 历史记录
const historyList = ref([])
const loadingHistory = ref(false)
const isFromHistory = ref(false)

// WebSocket 连接
const ws = ref(null)
const wsConnected = ref(false)

// 上传相关
const uploadRef = ref(null)
const uploading = ref(false)
const uploadProgress = ref(0)

// 视频信息
const videoInfo = ref(null)
const videoPlayer = ref(null)
const videoUrl = ref('')

// 配置
const config = reactive({
  min_segment_duration: 10,
  enable_brightness: false,
  enable_pose: false,
  enable_motion: false,
  enable_silence: false
})

// 处理状态
const processing = ref(false)
const taskFailed = ref(false)
const errorMessage = ref('')
const progressInfo = reactive({
  progress: 0,
  current_stage: '',
  processed_frames: 0,
  total_frames: 0,
  estimated_time: ''
})

// 片段列表
const segments = ref([])

// 选中的片段
const selectedSegments = ref([])

// 待处理列表
const pendingSegments = ref([])

// 预览弹窗
const previewDialogVisible = ref(false)
const previewSegmentInfo = ref(null)
const previewVideoPlayer = ref(null)

// 剪辑对话框
const showClipDialog = ref(false)
const clipItemPath = ref('')
const clipMediaType = ref('video')
const clipPlayerRef = ref(null)

// 合成弹窗
const mergeDialogVisible = ref(false)
const merging = ref(false)
const mergeConfig = reactive({
  output_name: '',
  resolution: '1080p',
  fps: 30,
  transition: 'none',
  transitionType: '淡入淡出',
  transitionRandom: false,
  transitionRandomAll: false,
  transitionDuration: 1.0,
  bgm_path: ''
})

// BGM列表
const bgmList = ref([])
const loadingBgm = ref(false)

const fetchBgmList = async () => {
  loadingBgm.value = true
  try {
    const res = await materialApi.getBGM()
    bgmList.value = Array.isArray(res) ? res : (res.data || [])
  } catch (error) {
    console.error('获取BGM列表失败:', error)
  } finally {
    loadingBgm.value = false
  }
}

// 转场效果分类
const transitionCategories = ref(['淡入淡出', '滑动擦除', '图形变换', '特效切片'])

// 转场效果映射表（分类 → 效果列表）
const transitionEffectsMap = {
  '淡入淡出': [
    { name: '无转场', value: 'none' },
    { name: '交叉淡入淡出', value: 'fade' },
    { name: '渐隐至黑', value: 'fadeblack' },
    { name: '渐隐至白', value: 'fadewhite' },
    { name: '溶解', value: 'dissolve' },
    { name: '距离过渡', value: 'distance' }
  ],
  '滑动擦除': [
    { name: '向左滑动', value: 'slideleft' },
    { name: '向右滑动', value: 'slideright' },
    { name: '向上滑动', value: 'slideup' },
    { name: '向下滑动', value: 'slidedown' },
    { name: '向左擦除', value: 'wipeleft' },
    { name: '向右擦除', value: 'wiperight' },
    { name: '向上擦除', value: 'wipeup' },
    { name: '向下擦除', value: 'wipedown' },
    { name: '平滑左滑', value: 'smoothleft' },
    { name: '平滑右滑', value: 'smoothright' },
    { name: '平滑上滑', value: 'smoothup' },
    { name: '平滑下滑', value: 'smoothdown' }
  ],
  '图形变换': [
    { name: '圆形裁剪', value: 'circlecrop' },
    { name: '矩形裁剪', value: 'rectcrop' },
    { name: '圆形展开', value: 'circleopen' },
    { name: '圆形闭合', value: 'circleclose' },
    { name: '水平展开', value: 'horzopen' },
    { name: '水平闭合', value: 'horzclose' },
    { name: '垂直展开', value: 'vertopen' },
    { name: '垂直闭合', value: 'vertclose' },
    { name: '放大过渡', value: 'zoomin' },
    { name: '水平挤压', value: 'squeezeh' },
    { name: '垂直挤压', value: 'squeezev' }
  ],
  '特效切片': [
    { name: '像素化', value: 'pixelize' },
    { name: '径向过渡', value: 'radial' },
    { name: '高斯模糊', value: 'hblur' },
    { name: '水平左切片', value: 'hlslice' },
    { name: '水平右切片', value: 'hrslice' },
    { name: '垂直上切片', value: 'vuslice' },
    { name: '垂直下切片', value: 'vdslice' }
  ]
}

// 当前分类下的转场效果列表
const currentTransitionEffects = computed(() => {
  return transitionEffectsMap[mergeConfig.transitionType] || []
})

// 处理转场分类切换
const handleTransitionTypeChange = (category) => {
  const effects = transitionEffectsMap[category]
  if (effects && effects.length > 0) {
    mergeConfig.transition = effects[0].value
  }
}

// 处理随机效果切换
const handleTransitionRandomChange = (random) => {
  if (random) {
    mergeConfig.transitionRandomAll = false
  }
}

// 音频播放弹窗
const audioDialogVisible = ref(false)
const audioInfo = ref(null)
const audioPlayer = ref(null)
const extractingOriginalAudio = ref(false)

// 计算属性
const progressStatus = computed(() => {
  if (taskFailed.value) return 'exception'
  if (progressInfo.progress >= 100) return 'success'
  return ''
})

// WebSocket 连接
const connectWebSocket = (taskId) => {
  if (ws.value) {
    ws.value.close()
  }

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const wsUrl = `${protocol}//${window.location.host}/api/ws/${taskId}`

  ws.value = new WebSocket(wsUrl)

  ws.value.onopen = () => {
    wsConnected.value = true
    console.log('WebSocket 连接成功')
  }

  ws.value.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      handleWebSocketMessage(data)
    } catch (e) {
      console.error('解析 WebSocket 消息失败:', e)
    }
  }

  ws.value.onerror = (error) => {
    console.error('WebSocket 错误:', error)
    wsConnected.value = false
  }

  ws.value.onclose = () => {
    wsConnected.value = false
    console.log('WebSocket 连接关闭')
  }
}

// 处理 WebSocket 消息
const handleWebSocketMessage = (data) => {
  console.log('收到 WebSocket 消息:', data)

  switch (data.type) {
    case 'smart_cut_progress':
      progressInfo.progress = data.progress
      progressInfo.current_stage = data.current_stage
      progressInfo.processed_frames = data.processed_frames
      progressInfo.total_frames = data.total_frames
      break

    case 'smart_cut_completed':
      processing.value = false
      progressInfo.progress = 100
      segments.value = data.segments || []
      ElMessage.success(`裁剪完成，共 ${data.segments_count} 个片段`)
      // 关闭 WebSocket
      if (ws.value) {
        ws.value.close()
      }
      break

    case 'smart_cut_failed':
      processing.value = false
      taskFailed.value = true
      errorMessage.value = data.error_message
      ElMessage.error(`裁剪失败：${data.error_message}`)
      // 关闭 WebSocket
      if (ws.value) {
        ws.value.close()
      }
      break

    case 'connected':
      console.log('WebSocket 服务器确认连接')
      break
  }
}

// 方法
const handleFileChange = async (file) => {
  // 验证文件大小
  const maxSize = 2 * 1024 * 1024 * 1024 // 2GB
  if (file.raw.size > maxSize) {
    ElMessage.error('视频文件过大，请上传小于 2GB 的文件')
    return
  }

  // 验证文件格式
  const validFormats = ['.mp4', '.avi', '.mov', '.mkv']
  const ext = file.name.substring(file.name.lastIndexOf('.')).toLowerCase()
  if (!validFormats.includes(ext)) {
    ElMessage.error('不支持的视频格式，请上传 mp4/avi/mov 文件')
    return
  }

  // 开始上传
  uploading.value = true
  uploadProgress.value = 0

  try {
    const formData = new FormData()
    formData.append('file', file.raw)

    // 模拟上传进度
    const progressInterval = setInterval(() => {
      if (uploadProgress.value < 90) {
        uploadProgress.value += 10
      }
    }, 200)

    const response = await smartCutApi.upload(formData)

    clearInterval(progressInterval)
    uploadProgress.value = 100

    if (response.code === 200) {
      videoInfo.value = response.data
      // 构建视频 URL
      videoUrl.value = `/files/${response.data.video_path}`

      ElMessage.success('视频上传成功')
    } else {
      throw new Error(response.message || '上传失败')
    }
  } catch (error) {
    console.error('上传失败:', error)
    ElMessage.error(error.message || '上传失败，请重试')
  } finally {
    uploading.value = false
  }
}

const handleVideoLoaded = () => {
  console.log('视频加载完成')
}

// 打开剪辑对话框
const openClipDialog = (path, mediaType) => {
  clipItemPath.value = path
  clipMediaType.value = mediaType
  showClipDialog.value = true
}

// 原视频剪辑回调
const handleVideoClipped = (data) => {
  ElMessage.success('剪辑成功')
  if (videoInfo.value) {
    videoInfo.value = { ...videoInfo.value, timestamp: Date.now() }
    videoUrl.value = `/files/${data.filePath}?t=${Date.now()}`
  }
  showClipDialog.value = false
}

const handleVideoCropped = (data) => {
  handleVideoClipped(data)
}

// 片段预览剪辑回调
const handlePreviewSegmentClipped = (data) => {
  ElMessage.success('剪辑成功')
  if (previewSegmentInfo.value) {
    // 更新segments数组中对应segment的视频路径
    const segIndex = segments.value.findIndex(s => s.segment_id === previewSegmentInfo.value.segment_id)
    if (segIndex !== -1) {
      // 保持原有segment_id和reason，只更新视频路径和时间戳
      segments.value[segIndex] = {
        ...segments.value[segIndex],
        video_path: data.filePath,
        timestamp: Date.now()
      }
    }
    // 同时更新预览信息以刷新播放器
    previewSegmentInfo.value = { ...previewSegmentInfo.value, video_path: data.filePath, timestamp: Date.now() }
  }
  showClipDialog.value = false
}

const handlePreviewSegmentCropped = (data) => {
  handlePreviewSegmentClipped(data)
}

const resetUpload = () => {
  videoInfo.value = null
  videoUrl.value = ''
  uploadProgress.value = 0
  segments.value = []
  progressInfo.progress = 0
  progressInfo.current_stage = ''
  taskFailed.value = false
  errorMessage.value = ''
  isFromHistory.value = false
}

const startCutting = async () => {
  if (!videoInfo.value) {
    ElMessage.warning('请先上传视频')
    return
  }

  processing.value = true
  taskFailed.value = false
  errorMessage.value = ''
  progressInfo.progress = 0
  progressInfo.current_stage = '准备中...'

  try {
    const response = await smartCutApi.createTask({
      video_path: videoInfo.value.video_path,
      video_name: videoInfo.value.video_name,
      duration: videoInfo.value.duration,
      fps: videoInfo.value.fps,
      width: videoInfo.value.width,
      height: videoInfo.value.height,
      total_frames: videoInfo.value.total_frames,
      config: { ...config }
    })

    if (response.code === 200) {
      currentTaskId.value = response.data.task_id
      ElMessage.success('裁剪任务已创建')

      // 连接 WebSocket 接收进度更新
      connectWebSocket(response.data.task_id)
    } else {
      throw new Error(response.message || '创建任务失败')
    }
  } catch (error) {
    console.error('创建任务失败:', error)
    ElMessage.error(error.message || '创建任务失败')
    processing.value = false
  }
}

const retryCutting = () => {
  taskFailed.value = false
  errorMessage.value = ''
  startCutting()
}

const formatDuration = (seconds) => {
  if (!seconds) return '00:00'
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
}

const getReasonTagType = (reason) => {
  const typeMap = {
    'scene_change': 'info',
    'silence': 'warning',
    'brightness': 'success',
    'motion': '',
    'pose': '',
    'default': ''
  }
  return typeMap[reason] || ''
}

// 片段操作
const previewSegment = (seg) => {
  previewSegmentInfo.value = seg
  previewDialogVisible.value = true
}

const onPreviewOpened = () => {
  // 弹窗打开后自动播放视频
  if (previewVideoPlayer.value) {
    previewVideoPlayer.value.play().catch(() => {
      // 自动播放可能被浏览器阻止，忽略错误
    })
  }
}

const onPreviewClosed = () => {
  // 弹窗关闭时停止播放
  if (previewVideoPlayer.value) {
    previewVideoPlayer.value.pause()
    previewVideoPlayer.value.currentTime = 0
  }
}

const toggleSegmentSelect = (segmentId) => {
  const index = selectedSegments.value.indexOf(segmentId)
  if (index > -1) {
    selectedSegments.value.splice(index, 1)
  } else {
    selectedSegments.value.push(segmentId)
  }
}

const clearSelection = () => {
  selectedSegments.value = []
}

const deleteSegment = (segmentId) => {
  const index = segments.value.findIndex(s => s.segment_id === segmentId)
  if (index > -1) {
    segments.value.splice(index, 1)
    // 如果该片段在待处理列表中，也一并移除
    removeFromPending(segmentId)
    // 如果该片段在选中列表中，也一并移除
    const selectedIndex = selectedSegments.value.indexOf(segmentId)
    if (selectedIndex > -1) {
      selectedSegments.value.splice(selectedIndex, 1)
    }
    ElMessage.success('片段已删除')
  }
}

const addToPending = (seg) => {
  if (!seg) return

  const exists = pendingSegments.value.find(s => s.segment_id === seg.segment_id)
  if (exists) {
    ElMessage.warning('该片段已在待处理列表中')
    return
  }

  pendingSegments.value.push(seg)
  ElMessage.success('已添加到待处理列表')
  previewDialogVisible.value = false
}

const removeFromPending = (segmentId) => {
  const index = pendingSegments.value.findIndex(s => s.segment_id === segmentId)
  if (index > -1) {
    pendingSegments.value.splice(index, 1)
  }
}

const clearPending = () => {
  pendingSegments.value = []
}

const batchAddToPending = () => {
  let addedCount = 0
  selectedSegments.value.forEach(segmentId => {
    const seg = segments.value.find(s => s.segment_id === segmentId)
    if (seg && !pendingSegments.value.find(s => s.segment_id === segmentId)) {
      pendingSegments.value.push(seg)
      addedCount++
    }
  })
  ElMessage.success(`已添加 ${addedCount} 个片段到待处理列表`)
  clearSelection()
}

const extractAudio = async (seg) => {
  if (!seg) return

  try {
    const response = await smartCutApi.extractAudio({
      segment_path: seg.video_path,
      name: `${seg.segment_id}_audio`
    })

    if (response.code === 200) {
      ElMessage.success('音频提取成功')
      // 关闭预览弹窗
      previewDialogVisible.value = false
      // 显示音频播放弹窗
      audioInfo.value = {
        audio_path: response.data.audio_path,
        duration: response.data.duration,
        source_segment: seg.segment_id
      }
      audioDialogVisible.value = true
    } else {
      throw new Error(response.message || '提取音频失败')
    }
  } catch (error) {
    console.error('提取音频失败:', error)
    ElMessage.error(error.message || '提取音频失败')
  }
}

// 添加到参考音频库 - 导航到素材库页面并预填充音频
const addToReference = () => {
  if (!audioInfo.value) return

  // 关闭音频弹窗
  audioDialogVisible.value = false

  // 导航到素材库页面，传递音频信息作为查询参数
  const audioData = JSON.stringify({
    path: audioInfo.value.audio_path,
    duration: audioInfo.value.duration,
    source: audioInfo.value.source_segment
  })

  router.push({
    path: '/materials',
    query: {
      action: 'create',
      type: 'audio',
      audio: audioData
    }
  })
}

// 添加到 BGM 库 - 导航到素材库页面并预填充音频
const addToBGM = () => {
  if (!audioInfo.value) return

  // 关闭音频弹窗
  audioDialogVisible.value = false

  // 导航到素材库页面，传递音频信息作为查询参数
  const audioData = JSON.stringify({
    path: audioInfo.value.audio_path,
    duration: audioInfo.value.duration,
    source: audioInfo.value.source_segment
  })

  router.push({
    path: '/materials',
    query: {
      action: 'create',
      type: 'bgm',
      audio: audioData
    }
  })
}

// 音频弹窗关闭时停止播放
const onAudioDialogClosed = () => {
  if (audioPlayer.value) {
    audioPlayer.value.pause()
    audioPlayer.value.currentTime = 0
  }
}

// 提取原视频音频
const extractOriginalAudio = async () => {
  if (!videoInfo.value || !videoInfo.value.video_path) {
    ElMessage.warning('请先上传视频')
    return
  }

  extractingOriginalAudio.value = true
  try {
    const response = await smartCutApi.extractAudio({
      segment_path: videoInfo.value.video_path,
      name: `${videoInfo.value.video_name}_audio`
    })

    if (response.code === 200) {
      ElMessage.success('音频提取成功')
      // 显示音频播放弹窗
      audioInfo.value = {
        audio_path: response.data.audio_path,
        duration: response.data.duration,
        source_segment: videoInfo.value.video_name
      }
      audioDialogVisible.value = true
    } else {
      throw new Error(response.message || '提取音频失败')
    }
  } catch (error) {
    console.error('提取音频失败:', error)
    ElMessage.error(error.message || '提取音频失败')
  } finally {
    extractingOriginalAudio.value = false
  }
}

// 合成相关
const showMergeDialog = () => {
  mergeConfig.output_name = `merged_${new Date().toISOString().slice(0, 10)}`
  mergeDialogVisible.value = true
  fetchBgmList()
}

const mergeVideos = async () => {
  if (pendingSegments.value.length === 0) {
    ElMessage.warning('请先添加片段到待处理列表')
    return
  }

  merging.value = true

  try {
    const response = await smartCutApi.merge({
      segments: pendingSegments.value.map(s => ({
        video_path: s.video_path,
        segment_id: s.segment_id
      })),
      output_name: mergeConfig.output_name,
      resolution: mergeConfig.resolution,
      fps: mergeConfig.fps,
      transition: mergeConfig.transition,
      transitionRandom: mergeConfig.transitionRandom,
      transitionRandomAll: mergeConfig.transitionRandomAll,
      transitionDuration: mergeConfig.transitionDuration,
      bgm_path: mergeConfig.bgm_path || undefined
    })

    if (response.code === 200) {
      ElMessage.success('视频合成成功')
      mergeDialogVisible.value = false
      // 显示合成结果
      ElMessage.info(`输出路径: ${response.data.output_path}`)
    } else {
      throw new Error(response.message || '合成失败')
    }
  } catch (error) {
    console.error('合成视频失败:', error)
    ElMessage.error(error.message || '合成失败')
  } finally {
    merging.value = false
  }
}

const saveToMaterial = () => {
  if (pendingSegments.value.length === 0) {
    ElMessage.warning('请先添加片段到待处理列表')
    return
  }

  // 使用 ElMessageBox 弹出选择框
  ElMessageBox.confirm(
    '请选择保存类型',
    '保存到素材库',
    {
      confirmButtonText: '角色',
      cancelButtonText: '场景',
      distinguishCancelAndClose: true,
      type: 'info'
    }
  ).then(() => {
    // 选择"角色" - 导航到素材库页面
    const videosData = JSON.stringify(
      pendingSegments.value.map(s => ({
        path: s.video_path,
        name: s.segment_id,
        duration: s.duration,
        thumbnail: s.thumbnail
      }))
    )

    router.push({
      path: '/materials',
      query: {
        action: 'create',
        type: 'character',
        videos: videosData
      }
    })
  }).catch((action) => {
    if (action === 'cancel') {
      // 选择"场景" - 导航到素材库页面
      const videosData = JSON.stringify(
        pendingSegments.value.map(s => ({
          path: s.video_path,
          name: s.segment_id,
          duration: s.duration,
          thumbnail: s.thumbnail
        }))
      )

      router.push({
        path: '/materials',
        query: {
          action: 'create',
          type: 'scene',
          videos: videosData
        }
      })
    }
    // 如果是 close（点击关闭按钮），不做任何操作
  })
}

// 加载历史记录
const loadHistory = async () => {
  loadingHistory.value = true
  try {
    const res = await smartCutApi.getHistory()
    if (res.code === 200) {
      historyList.value = res.data.history || []
    }
  } catch (error) {
    console.error('加载历史记录失败:', error)
  } finally {
    loadingHistory.value = false
  }
}

// 恢复历史记录详情
const restoreHistory = async (item) => {
  currentTaskId.value = item.task_id
  isFromHistory.value = true

  // uploaded状态：恢复上传信息，不加载片段
  if (item.status === 'uploaded') {
    videoInfo.value = {
      video_id: item.task_id,
      video_name: item.video_name,
      video_path: item.video_path,
      duration: item.video_duration,
      fps: item.video_fps,
      width: item.video_width,
      height: item.video_height,
      total_frames: item.total_frames,
      thumbnail: item.thumbnail || ''
    }
    if (item.video_path) {
      videoUrl.value = `/files/${item.video_path}`
    }
    segments.value = []
    ElMessage.success('已恢复上传状态，可继续裁剪')
    return
  }

  // 其他状态：恢复裁剪结果
  try {
    const res = await smartCutApi.getSegments(item.task_id)
    if (res.code === 200 && res.data.segments) {
      segments.value = res.data.segments
      videoInfo.value = {
        video_name: item.video_name,
        video_path: item.video_path,
        duration: item.video_duration,
        fps: item.video_fps,
        width: item.video_width,
        height: item.video_height,
        total_frames: item.total_frames
      }
      // 设置视频 URL 以便播放原视频
      if (item.video_path) {
        videoUrl.value = `/files/${item.video_path}`
      }
      ElMessage.success('已恢复历史记录')
    }
  } catch (error) {
    console.error('恢复历史记录失败:', error)
    ElMessage.error('恢复历史记录失败')
  }
}

// 状态标签映射
const getStatusLabel = (status) => {
  const map = {
    uploaded: '已上传',
    pending: '等待中',
    processing: '裁剪中',
    completed: '已完成',
    failed: '失败'
  }
  return map[status] || status
}

// 状态标签颜色映射
const getStatusTagType = (status) => {
  const map = {
    uploaded: 'info',
    pending: 'warning',
    processing: '',
    completed: 'success',
    failed: 'danger'
  }
  return map[status] || 'info'
}

// 返回历史记录列表
const resetToHistory = () => {
  videoInfo.value = null
  segments.value = []
  currentTaskId.value = ''
  isFromHistory.value = false
  pendingSegments.value = []
}

// 删除历史记录
const deleteHistory = async (taskId) => {
  try {
    await ElMessageBox.confirm('确定要删除这条历史记录吗？相关的临时文件也会被清理。', '删除确认', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning'
    })

    const res = await smartCutApi.deleteTask(taskId)
    if (res.code === 200) {
      historyList.value = historyList.value.filter(item => item.task_id !== taskId)
      ElMessage.success('删除成功')
    } else {
      ElMessage.error(res.message || '删除失败')
    }
  } catch (error) {
    if (error !== 'cancel') {
      console.error('删除历史记录失败:', error)
      ElMessage.error('删除失败')
    }
  }
}

// 格式化日期时间
const formatDateTime = (dateStr) => {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

// 组件挂载时加载历史记录
onMounted(() => {
  loadHistory()
})

// 组件卸载时关闭 WebSocket
onUnmounted(() => {
  if (ws.value) {
    ws.value.close()
  }
})
</script>

<style scoped>
.smart-cut-view {
  padding: var(--space-lg);
  max-width: 1400px;
  margin: 0 auto;
}

.page-header {
  margin-bottom: var(--space-lg);
}

.page-header h1 {
  margin: 0 0 var(--space-sm) 0;
  font-size: var(--font-size-3xl);
}

.page-header .description {
  margin: 0;
  color: var(--color-text-secondary);
}

.upload-section {
  margin-bottom: var(--space-lg);
}

.video-uploader {
  width: 100%;
}

.video-uploader :deep(.el-upload-dragger) {
  width: 100%;
  height: 200px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}

.upload-progress {
  margin-bottom: var(--space-lg);
}

.progress-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-base);
  padding: var(--space-3xl) 0;
}

.video-section {
  display: flex;
  gap: var(--space-lg);
}

.video-preview {
  flex: 2;
}

.video-preview .card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.video-preview .header-actions {
  display: flex;
  gap: var(--space-sm);
}

.video-container {
  background: #000;
  border-radius: var(--radius-md);
  overflow: hidden;
  margin-bottom: var(--space-base);
  height: 360px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.video-player {
  max-width: 100%;
  max-height: 100%;
  width: auto;
  height: auto;
  object-fit: contain;
}

.video-info {
  margin-top: var(--space-base);
}

.config-panel {
  flex: 1;
}

.config-hint {
  margin-left: var(--space-md);
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
}

.cutting-progress {
  margin-top: var(--space-lg);
}

.progress-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-base);
}

.progress-details {
  display: flex;
  justify-content: space-between;
  margin-top: var(--space-md);
  color: var(--color-text-secondary);
  font-size: var(--font-size-base);
}

.progress-error {
  margin-top: var(--space-base);
}

.retry-button {
  margin-top: var(--space-md);
}

.segments-section {
  margin-top: var(--space-lg);
}

.segments-section .card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.segments-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: var(--space-base);
}

.segment-card {
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  overflow: hidden;
  transition: all 0.3s;
}

.segment-card:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-md);
}

.segment-thumbnail {
  position: relative;
  aspect-ratio: 16/9;
  background: #000;
}

.segment-thumbnail img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.segment-duration {
  position: absolute;
  bottom: var(--space-sm);
  right: var(--space-sm);
  background: rgba(0, 0, 0, 0.7);
  color: #fff;
  padding: 2px 6px;
  border-radius: var(--radius-sm);
  font-size: var(--font-size-sm);
}

.segment-reason {
  position: absolute;
  top: var(--space-sm);
  left: var(--space-sm);
}

.segment-select-btn {
  position: absolute;
  top: var(--space-sm);
  right: var(--space-sm);
}

.segment-delete-btn {
  position: absolute;
  top: var(--space-sm);
  right: 40px;
}

.segment-selected {
  border-color: var(--color-primary);
  border-width: 2px;
  box-shadow: 0 0 8px rgba(64, 158, 255, 0.3);
}

.segment-info {
  padding: var(--space-sm) var(--space-md);
  font-size: var(--font-size-sm);
  color: var(--color-text-regular);
}

.batch-actions {
  margin-top: var(--space-base);
  display: flex;
  gap: var(--space-md);
}

.preview-dialog-content {
  display: flex;
  flex-direction: column;
  gap: var(--space-base);
}

.preview-video-container {
  height: 400px;
  background: #000;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.preview-video {
  max-width: 100%;
  max-height: 100%;
  width: auto;
  height: auto;
  object-fit: contain;
}

.preview-info {
  margin-top: var(--space-md);
}

.pending-section {
  margin-top: var(--space-lg);
}

.pending-section .card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.pending-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
  max-height: 300px;
  overflow-y: auto;
}

.pending-item {
  display: flex;
  align-items: center;
  gap: var(--space-md);
  padding: var(--space-sm);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
}

.pending-thumbnail {
  width: 80px;
  height: 45px;
  border-radius: var(--radius-sm);
  overflow: hidden;
  flex-shrink: 0;
}

.pending-thumbnail img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.pending-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
}

.pending-name {
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-medium);
}

.pending-duration {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

.pending-actions {
  margin-top: var(--space-base);
  display: flex;
  gap: var(--space-md);
}

/* 操作按钮强制并排 */
.action-buttons-row {
  display: flex;
  gap: var(--space-md);
  flex-wrap: nowrap;
}

.action-buttons-row :deep(.el-form-item__content) {
  display: flex;
  gap: var(--space-md);
  flex-wrap: nowrap;
  width: 100%;
}

.action-buttons-row :deep(.el-button) {
  flex: 1;
  min-width: 0;
}

/* 音频弹窗 */
.audio-dialog-content {
  display: flex;
  flex-direction: column;
  gap: var(--space-base);
}

.audio-player-container {
  padding: var(--space-lg);
  background: var(--bg-muted);
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
}

.audio-player {
  width: 100%;
}

/* 转场效果设置 */
.transition-settings {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
}

.transition-row {
  display: flex;
  gap: var(--space-md);
}

.transition-select {
  flex: 1;
  width: 50%;
  min-width: 0;
}

.transition-random {
  display: flex;
  gap: var(--space-base);
  align-items: center;
}

.transition-duration {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}

.duration-label {
  color: var(--color-text-regular);
  font-size: var(--font-size-base);
}

/* 历史记录区域 - 始终置顶显示 */
.history-section {
  margin-top: var(--space-lg);
  margin-bottom: var(--space-lg);
}

.history-section .card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.history-section .card-header span {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}

.history-empty {
  padding: var(--space-lg);
}

.history-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: var(--space-base);
  max-height: 300px;
  overflow-y: auto;
}

.history-card {
  display: flex;
  align-items: center;
  gap: var(--space-base);
  padding: var(--space-base);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all 0.3s;
  position: relative;
}

.history-card:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-md);
}

.history-icon {
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-muted);
  border-radius: var(--radius-md);
  color: var(--color-primary);
}

.history-info {
  flex: 1;
  min-width: 0;
}

.history-name {
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}

.status-tag {
  flex-shrink: 0;
}

.history-meta {
  display: flex;
  gap: var(--space-md);
  margin-top: var(--space-xs);
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

.history-time {
  margin-top: var(--space-xs);
  font-size: var(--font-size-sm);
  color: var(--color-text-placeholder);
}

.history-delete {
  position: absolute;
  top: var(--space-sm);
  right: var(--space-sm);
}

/* 响应式 */
@media (max-width: 992px) {
  .video-section {
    flex-direction: column;
  }

  .segments-grid {
    grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  }

  .history-grid {
    grid-template-columns: 1fr;
  }
}

/* ==================== 媒体剪辑对话框样式 ==================== */
.media-clip-dialog {
  :deep(.el-dialog) {
    border-radius: var(--radius-lg);
    overflow: hidden;
  }

  :deep(.el-dialog__header) {
    padding: var(--space-lg) var(--space-xl);
    border-bottom: 1px solid var(--color-border-strong);
  }

  :deep(.el-dialog__title) {
    font-size: var(--font-size-xl);
    font-weight: var(--font-weight-semibold);
  }

  :deep(.el-dialog__body) {
    padding: 0;
    overflow-y: auto;
    max-height: 70vh;
  }
}

.media-clip-container {
  padding: var(--space-xl);
}

.media-clip-content {
  display: flex;
  flex-direction: column;
  gap: var(--space-base);
}

.media-preview-player {
  background: #000;
  border-radius: var(--radius-md);
  overflow: hidden;

  .video-player {
    width: 100%;
    max-height: 500px;
    object-fit: contain;
  }

  .audio-player {
    width: 100%;
    padding: var(--space-lg);
  }
}

.dark-theme {
  .media-clip-dialog {
    :deep(.el-dialog) {
      background: var(--bg-card-solid);
      border: 1px solid var(--color-border-strong);
    }

    :deep(.el-dialog__header) {
      border-bottom-color: var(--color-border-strong);
    }

    :deep(.el-dialog__title) {
      color: var(--color-text-primary);
    }

    :deep(.el-dialog__body) {
      background: var(--bg-card-solid);
    }
  }

  .media-preview-player {
    background: #000;
  }
}

/* 视频操作栏 */
.video-actions-bar {
  padding: var(--space-md) var(--space-base);
  background: var(--bg-muted);
  border-top: 1px solid var(--color-border-strong);
  display: flex;
  justify-content: flex-end;
}

/* 预览操作栏 */
.preview-actions-bar {
  padding: var(--space-md) 0;
  display: flex;
  justify-content: center;
}

/* ==================== 暗色主题覆盖 ==================== */
/* 选中片段阴影在暗色下使用品牌色 */
:global(body.dark-theme) .smart-cut-view .segment-selected {
  box-shadow: 0 0 8px rgba(0, 217, 255, 0.3);
}
</style>
