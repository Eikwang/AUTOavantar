<template>
  <div class="settings-container" :class="{ 'dark-theme': isDarkTheme }">
    <div class="settings-content">
      <div class="page-header">
        <h2 class="page-title">系统设置</h2>
      </div>

      <el-form :model="settingsStore.settings" label-position="top">
        <!-- 激活管理卡片 -->
        <el-card class="settings-card" shadow="hover">
          <template #header>
            <div class="card-header">
              <el-icon><Lock /></el-icon>
              <span>系统激活</span>
            </div>
          </template>

          <div class="activation-section">
            <div class="activation-status">
              <div class="status-row">
                <span class="status-label">激活状态：</span>
                <el-tag :type="activationStatus.isActivated ? 'success' : 'warning'" size="large">
                  {{ activationStatus.isActivated ? '已激活' : '未激活' }}
                </el-tag>
              </div>

              <div class="status-row" v-if="activationStatus.isActivated">
                <span class="status-label">激活类型：</span>
                <el-tag type="info" size="small">{{ formatLicenseType(activationStatus.licenseType) }}</el-tag>
              </div>

              <div class="status-row" v-if="activationStatus.isActivated">
                <span class="status-label">有效期至：</span>
                <span class="status-value">{{ formatExpiresAt(activationStatus.expiresAt) }}</span>
              </div>

              <div class="status-row" v-if="!activationStatus.isActivated">
                <span class="status-label">剩余配额：</span>
                <span class="status-value">{{ activationStatus.remainingQuota }} / {{ activationStatus.maxQuota }}</span>
              </div>

              <div class="status-row">
                <span class="status-label">机器码：</span>
                <div class="machine-code-wrapper">
                  <code class="machine-code">{{ activationStatus.machineCode }}</code>
                  <el-button text type="primary" size="small" @click="copyMachineCode">
                    <el-icon><CopyDocument /></el-icon>
                    复制
                  </el-button>
                </div>
              </div>
            </div>

            <!-- 联系信息和价格信息 -->
            <div class="activation-info" v-if="!activationStatus.isActivated">
              <el-divider content-position="left">激活说明</el-divider>
              <div class="info-section">
                <p class="info-text sales-info">
                  免费版每天可以生成10条视频，个人使用已经完全足够，若需解锁工作室版请联系作者
                </p>
                <div class="price-info">
                  <p class="price-title">价格信息：</p>
                  <ul class="price-list">
                    <li>一年 <span class="price">69元</span></li>
                    <li>三年 <span class="price">128元</span></li>
                    <li>终身 <span class="price original">1280元</span> <span class="discount">限时特惠仅需 <span class="special-price">398元</span></span></li>
                  </ul>
                </div>
                <div class="contact-info">
                  <p class="contact-title">联系方式：</p>
                  <p class="contact-detail">微信：<span class="highlight">me-orzing</span> (13145981227)</p>
                </div>
              </div>
            </div>

            <div class="activation-actions">
              <el-button
                v-if="!activationStatus.isActivated"
                type="primary"
                @click="showActivationDialog"
              >
                <el-icon><Key /></el-icon>
                输入激活码
              </el-button>
              <el-button
                v-else
                type="info"
                plain
                @click="refreshActivationStatus"
                :loading="activationLoading"
              >
                <el-icon><Refresh /></el-icon>
                刷新状态
              </el-button>
            </div>
          </div>
        </el-card>

        <el-card class="settings-card" shadow="hover">
          <template #header>
            <div class="card-header">
              <el-icon><Key /></el-icon>
              <span>API Key 配置</span>
            </div>
          </template>

          <div class="form-grid">
            <el-form-item label="DeepSeek API Key" class="full-width">
              <el-input 
                v-model="settingsStore.settings.deepseek_api_key" 
                type="password" 
                show-password
                placeholder="输入 DeepSeek API Key"
              />
            </el-form-item>

            <el-form-item label="阿里云 API Key" class="full-width">
              <el-input
                v-model="settingsStore.settings.aliyun_api_key"
                type="password"
                show-password
                placeholder="输入阿里云 API Key"
              />
            </el-form-item>
          </div>

          <div class="card-footer">
            <el-button type="primary" @click="saveApiKeys" :loading="saving">
              <el-icon><Check /></el-icon>
              保存 API Key
            </el-button>
          </div>
        </el-card>

        <el-card class="settings-card" shadow="hover">
          <template #header>
            <div class="card-header">
              <el-icon><Document /></el-icon>
              <span>模版配置</span>
            </div>
          </template>

          <div class="form-grid">
            <el-form-item label="单人提示词模版" class="full-width">
              <el-input
                v-model="settingsStore.settings.single_person_prompt_template"
                type="textarea"
                :rows="4"
                placeholder="根据主题{theme}生成单人讲解文案，包含开场、情绪标签、场景标签、结束"
              />
              <div class="form-hint">
                可用变量：{theme} - 主题内容
              </div>
            </el-form-item>

            <el-form-item label="双人提示词模版" class="full-width">
              <el-input
                v-model="settingsStore.settings.dual_person_prompt_template"
                type="textarea"
                :rows="4"
                placeholder="根据主题{theme}生成双人对话文案，包含开场、左边说话人、右边说话人、情绪标签、场景标签、结束"
              />
              <div class="form-hint">
                可用变量：{theme} - 主题内容
              </div>
            </el-form-item>

            <el-form-item label="封面生成提示词模版" class="full-width">
              <el-input
                v-model="settingsStore.settings.cover_prompt_template"
                type="textarea"
                :rows="3"
                placeholder="根据文案{summary}生成视频封面，风格简洁，突出主题"
              />
              <div class="form-hint">
                可用变量：{summary} - 文案摘要
              </div>
            </el-form-item>
          </div>

          <div class="card-footer">
            <el-button type="primary" @click="savePromptTemplates" :loading="saving">
              <el-icon><Check /></el-icon>
              保存提示词模版
            </el-button>
          </div>
        </el-card>

        <el-card class="settings-card" shadow="hover">
          <template #header>
            <div class="card-header">
              <el-icon><Setting /></el-icon>
              <span>默认参数配置</span>
            </div>
          </template>

          <div class="form-grid">
            <el-form-item label="HeyGEM 原始参数">
              <el-switch v-model="settingsStore.settings.heygem_original" />
              <span class="form-hint">开启后使用原始分辨率/帧率参数</span>
            </el-form-item>

            <el-form-item label="双人模式">
              <el-switch v-model="settingsStore.settings.dual_mode" />
              <span class="form-hint">开启后启用双人对话模式</span>
            </el-form-item>

            <el-form-item label="精准字幕" class="full-width">
              <el-switch
                v-model="settingsStore.settings.enable_precise_subtitle"
                @change="handlePreciseSubtitleChange"
              />
              <span class="form-hint">
                开启后使用 Qwen3-ForcedAligner 强制对齐技术生成精确字幕
              </span>
            </el-form-item>

            <el-form-item label="HeyGEM 推理批次" class="full-width">
              <el-slider
                v-model="settingsStore.settings.heygem_inference_steps"
                :min="4"
                :max="32"
                :step="1"
                show-stops
                :marks="{ 4: '4', 16: '16', 32: '32' }"
              />
              <div class="form-hint">推理批次影响生成质量与速度，默认 16</div>
            </el-form-item>

            <el-form-item label="IndexTTS 默认语速" class="full-width">
              <el-slider
                v-model="settingsStore.settings.tts_speed"
                :min="0.8"
                :max="1.2"
                :step="0.05"
                show-input
              />
              <div class="form-hint">语速范围 0.8-1.2，默认 1.0</div>
            </el-form-item>

            <el-form-item label="IndexTTS 默认情感权重" class="full-width">
              <el-slider
                v-model="settingsStore.settings.tts_emo_weight"
                :min="0"
                :max="1.2"
                :step="0.05"
                show-input
              />
              <div class="form-hint">情感权重范围 0-0.8，默认 0.4</div>
            </el-form-item>
          </div>

          <div class="card-footer">
            <el-button type="primary" @click="saveDefaultParams" :loading="saving">
              <el-icon><Check /></el-icon>
              保存默认参数
            </el-button>
          </div>
        </el-card>

        <!-- 服务状态卡片 -->
        <el-card class="settings-card" shadow="hover">
          <template #header>
            <div class="card-header">
              <el-icon><Monitor /></el-icon>
              <span>服务状态</span>
            </div>
          </template>

          <!-- 低显存模式开关 -->
          <div class="low-memory-mode-section">
            <div class="low-memory-mode-header">
              <span class="low-memory-mode-label">低显存模式</span>
              <el-switch
                v-model="lowMemoryMode"
                :loading="lowMemoryModeLoading"
                @change="handleLowMemoryModeChange"
              />
            </div>
            <p class="low-memory-mode-hint">
              开启后系统启动时不加载模型，任务执行时按需加载，任务完成后释放显存
            </p>
          </div>

          <!-- 超低显存模式开关（仅在低显存模式开启时显示） -->
          <div class="ultra-low-memory-section" v-if="lowMemoryMode">
            <div class="ultra-low-memory-header">
              <span class="ultra-low-memory-label">超低显存模式</span>
              <el-switch
                v-model="ultraLowMemory"
                :loading="ultraLowMemoryLoading"
                @change="handleUltraLowMemoryChange"
              />
            </div>
            <p class="ultra-low-memory-hint">
              开启后进一步降低显存占用（约5-5.5GB），适合显存≤6GB的显卡。首次推理会有额外延迟
            </p>
          </div>
        </el-card>

        <TagGroupManager />

        <EmotionTagManager />

        <!-- 激活对话框 -->
        <ActivationDialog
          v-model="activationDialogVisible"
          @activated="handleActivated"
        />

        <el-card class="settings-card" shadow="hover">
          <template #header>
            <div class="card-header">
              <el-icon><Delete /></el-icon>
              <span>系统维护</span>
            </div>
          </template>

          <div class="form-grid">
            <el-form-item label="清理缓存" class="full-width">
              <div class="cache-info">
                <p>清理系统运行过程中产生的临时文件，包括：</p>
                <ul>
                  <li>任务执行中间文件</li>
                  <li>音频/视频处理临时文件</li>
                  <li>日志文件</li>
                </ul>
              </div>
              <el-button 
                type="danger" 
                @click="showClearCacheConfirm"
                :loading="clearingCache"
              >
                <el-icon><Delete /></el-icon>
                清理缓存
              </el-button>
            </el-form-item>
          </div>
        </el-card>
      </el-form>
    </div>

  </div>
</template>

<script setup>
import { ref, computed, onMounted, inject } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Key, Document, Setting, Delete, Monitor, Lock, CopyDocument, Refresh
} from '@element-plus/icons-vue'
import { settingsApi, systemApi, licenseApi } from '@/services/api'
import { useSettingsStore } from '@/stores/settingsStore.js'
import TagGroupManager from '@/components/TagGroupManager.vue'
import EmotionTagManager from '@/components/EmotionTagManager.vue'
import ActivationDialog from '@/components/ActivationDialog.vue'

// 注入主题状态
const isDarkTheme = inject('isDarkTheme', ref(false))
const settingsStore = useSettingsStore()

const saving = ref(false)
const clearingCache = ref(false)

// 低显存模式
const lowMemoryMode = ref(false)
const lowMemoryModeLoading = ref(false)

// 超低显存模式
const ultraLowMemory = ref(false)
const ultraLowMemoryLoading = ref(false)

// 激活相关
const activationDialogVisible = ref(false)
const activationLoading = ref(false)
const activationStatus = ref({
  isActivated: false,
  machineCode: '',
  remainingQuota: 0,
  maxQuota: 0,
  licenseType: '',
  expiresAt: null
})

// 获取系统配置
const fetchSystemConfig = async () => {
  try {
    const response = await systemApi.getConfig()
    lowMemoryMode.value = response.low_memory_mode
    ultraLowMemory.value = response.ultra_low_memory || false
    // 从系统配置中获取精准字幕状态
    settingsStore.settings.enable_precise_subtitle = response.enable_precise_subtitle || false
  } catch (error) {
    console.error('获取系统配置失败:', error)
  }
}

// 更新低显存模式
const handleLowMemoryModeChange = async (value) => {
  lowMemoryModeLoading.value = true
  try {
    await systemApi.updateConfig({ low_memory_mode: value })
    ElMessage.success(`低显存模式已${value ? '开启' : '关闭'}`)
    // 如果关闭低显存模式，同时关闭超低显存模式
    if (!value && ultraLowMemory.value) {
      ultraLowMemory.value = false
      await systemApi.updateConfig({ ultra_low_memory: false })
    }
  } catch (error) {
    ElMessage.error(`更新失败: ${error.response?.data?.detail || error.message}`)
    // 恢复原值
    await fetchSystemConfig()
  } finally {
    lowMemoryModeLoading.value = false
  }
}

// 更新超低显存模式
const handleUltraLowMemoryChange = async (value) => {
  ultraLowMemoryLoading.value = true
  try {
    await systemApi.updateConfig({ ultra_low_memory: value })
    ElMessage.success(`超低显存模式已${value ? '开启' : '关闭'}`)
  } catch (error) {
    ElMessage.error(`更新失败: ${error.response?.data?.detail || error.message}`)
    // 恢复原值
    await fetchSystemConfig()
  } finally {
    ultraLowMemoryLoading.value = false
  }
}

// 使用computed获取settings，确保响应式更新
// 更新精准字幕
const handlePreciseSubtitleChange = async (value) => {
  try {
    await systemApi.updateConfig({ enable_precise_subtitle: value })
    ElMessage.success(`精准字幕已${value ? '开启' : '关闭'}`)
  } catch (error) {
    ElMessage.error(`更新失败：${error.response?.data?.detail || error.message}`)
    // 恢复原值
    await fetchSystemConfig()
  }
}

const settings = computed({
  get: () => settingsStore.settings,
  set: (value) => settingsStore.updateSettings(value)
})

const saveApiKeys = async () => {
  saving.value = true
  try {
    await settingsApi.updateApiKeys({
      deepseek_api_key: settingsStore.settings.deepseek_api_key,
      aliyun_api_key: settingsStore.settings.aliyun_api_key
    })
    ElMessage.success('API Key 配置已保存')
  } catch (error) {
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

const savePromptTemplates = async () => {
  saving.value = true
  try {
    await settingsApi.updatePromptTemplates({
      single_person_prompt_template: settingsStore.settings.single_person_prompt_template,
      dual_person_prompt_template: settingsStore.settings.dual_person_prompt_template,
      cover_prompt_template: settingsStore.settings.cover_prompt_template
    })
    ElMessage.success('提示词模版已保存')
  } catch (error) {
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

const saveDefaultParams = async () => {
  saving.value = true
  try {
    await settingsApi.updateDefaultParams({
      heygem_original: settingsStore.settings.heygem_original,
      heygem_inference_steps: settingsStore.settings.heygem_inference_steps,
      dual_mode: settingsStore.settings.dual_mode,
      tts_speed: settingsStore.settings.tts_speed,
      tts_emo_weight: settingsStore.settings.tts_emo_weight,
      enable_precise_subtitle: settingsStore.settings.enable_precise_subtitle
    })
    ElMessage.success('默认参数已保存')
  } catch (error) {
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

const showClearCacheConfirm = () => {
  ElMessageBox.confirm(
    '确定要清理所有缓存文件吗？此操作不可撤销。',
    '清理缓存确认',
    {
      confirmButtonText: '确定清理',
      cancelButtonText: '取消',
      type: 'warning'
    }
  ).then(() => {
    clearCache()
  }).catch(() => {
    // 用户取消
  })
}

const clearCache = async () => {
  clearingCache.value = true
  try {
    const result = await settingsApi.clearCache()
    if (result.code === 200) {
      const data = result.data
      ElMessage.success(
        `清理完成！删除 ${data.deleted_files} 个文件，释放 ${data.deleted_size_mb} MB 空间`
      )
    } else {
      ElMessage.error(result.message || '清理失败')
    }
  } catch (error) {
    ElMessage.error('清理缓存失败: ' + (error.message || '未知错误'))
  } finally {
    clearingCache.value = false
  }
}

// 激活相关方法
const fetchActivationStatus = async () => {
  activationLoading.value = true
  try {
    const response = await licenseApi.getStatus()
    activationStatus.value = {
      isActivated: response.is_activated,
      machineCode: response.machine_code,
      remainingQuota: response.remaining_quota,
      maxQuota: response.max_quota,
      licenseType: response.license_type || '',
      expiresAt: response.expires_at || null
    }
  } catch (error) {
    console.error('获取激活状态失败:', error)
    ElMessage.error('获取激活状态失败')
  } finally {
    activationLoading.value = false
  }
}

// 格式化激活类型显示
const formatLicenseType = (type) => {
  const typeMap = {
    'yearly': '一年期',
    'three_year': '三年期',
    'lifetime': '终身'
  }
  return typeMap[type] || type || '未知'
}

// 格式化过期时间显示
const formatExpiresAt = (expiresAt) => {
  if (!expiresAt) return '永久有效'
  try {
    const date = new Date(expiresAt)
    return date.toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric' })
  } catch {
    return expiresAt
  }
}

const showActivationDialog = () => {
  activationDialogVisible.value = true
}

const handleActivated = () => {
  fetchActivationStatus()
  ElMessage.success('系统已激活')
}

const refreshActivationStatus = () => {
  fetchActivationStatus()
}

const copyMachineCode = async () => {
  try {
    await navigator.clipboard.writeText(activationStatus.value.machineCode)
    ElMessage.success('机器码已复制到剪贴板')
  } catch (error) {
    ElMessage.error('复制失败')
  }
}

onMounted(() => {
  settingsStore.fetchSettings()
  fetchSystemConfig()
  fetchActivationStatus()
})
</script>

<style scoped>
.settings-container {
  min-height: calc(100vh - var(--header-height) - var(--footer-height));
  padding: var(--space-xl);
  background: var(--bg-page-gradient);
  transition: background var(--transition-normal);
}

.settings-content {
  max-width: 900px;
  margin: 0 auto;
}

.page-header {
  margin-bottom: var(--space-2xl);
}

.settings-card {
  margin-bottom: var(--space-xl);
  background: var(--bg-card);
  border: 1px solid var(--color-border);
  backdrop-filter: blur(10px);
  box-shadow: var(--shadow-md);
  transition: all var(--transition-normal);
}

.settings-card :deep(.el-card__header) {
  background: var(--color-primary-bg);
  border-bottom: 1px solid var(--color-border);
  padding: var(--space-base) var(--space-lg);
  transition: all var(--transition-normal);
}

.settings-card :deep(.el-card__body) {
  padding: var(--space-xl) var(--space-lg);
}

.card-header {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  transition: color var(--transition-normal);
}

.card-header .el-icon {
  font-size: var(--font-size-2xl);
  color: var(--color-primary);
  transition: color var(--transition-normal);
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--space-lg);
}

.form-grid .full-width {
  grid-column: 1 / -1;
}

.form-grid :deep(.el-form-item__label) {
  color: var(--color-text-regular);
  font-weight: var(--font-weight-medium);
  transition: color var(--transition-normal);
}

.form-grid :deep(.el-input__wrapper),
.form-grid :deep(.el-textarea__inner) {
  background: var(--bg-card);
  border: 1px solid var(--color-border);
  box-shadow: none;
  transition: all var(--transition-normal);
}

.form-grid :deep(.el-input__wrapper:hover),
.form-grid :deep(.el-textarea__inner:hover) {
  border-color: var(--color-primary-light);
}

.form-grid :deep(.el-input__wrapper.is-focus),
.form-grid :deep(.el-textarea__inner:focus) {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 2px var(--color-primary-bg);
}

.form-hint {
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
  margin-top: 6px;
  line-height: 1.4;
  transition: color var(--transition-normal);
}

.form-grid :deep(.el-slider__runway) {
  background: var(--color-border);
}

.form-grid :deep(.el-slider__bar) {
  background: linear-gradient(90deg, var(--color-primary), var(--color-success));
}

.form-grid :deep(.el-slider__button) {
  border-color: var(--color-primary);
  background: var(--color-primary);
}

.form-grid :deep(.el-switch) {
  --el-switch-off-color: var(--color-border);
  --el-switch-on-color: var(--color-primary);
}

.form-grid :deep(.el-input-number) {
  width: 140px;
}

.form-grid :deep(.el-input-number .el-input__wrapper) {
  width: 100%;
}

.card-footer {
  margin-top: var(--space-xl);
  padding-top: var(--space-lg);
  border-top: 1px solid var(--color-border);
  display: flex;
  justify-content: flex-end;
  transition: border-color var(--transition-normal);
}

.card-footer .el-button {
  background: linear-gradient(135deg, var(--color-primary), var(--color-success));
  border: none;
  font-weight: var(--font-weight-semibold);
}

.card-footer .el-button:hover {
  opacity: 0.9;
  transform: translateY(-1px);
}

.cache-info {
  margin-bottom: var(--space-base);
  padding: var(--space-md) var(--space-base);
  background: var(--bg-dark-muted);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border-light);
}


.cache-info p {
  margin: 0 0 var(--space-sm) 0;
  color: var(--color-text-regular);
  font-size: var(--font-size-base);
}


.cache-info ul {
  margin: 0;
  padding-left: var(--space-lg);
  color: var(--color-text-secondary);
  font-size: 13px;
}


.cache-info li {
  margin: var(--space-xs) 0;
}

/* 低显存模式开关样式 */
.low-memory-mode-section {
  margin-bottom: var(--space-sm);
}

.low-memory-mode-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-sm);
}

.low-memory-mode-label {
  font-weight: var(--font-weight-semibold);
  font-size: var(--font-size-md);
  color: var(--color-text-primary);
}

.low-memory-mode-hint {
  margin: 0;
  font-size: 13px;
  color: var(--color-text-secondary);
  line-height: 1.5;
}

/* 超低显存模式开关样式 */
.ultra-low-memory-section {
  margin-top: var(--space-lg);
  padding-top: var(--space-base);
  border-top: 1px dashed var(--color-border);
}

.ultra-low-memory-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-sm);
}

.ultra-low-memory-label {
  font-weight: var(--font-weight-semibold);
  font-size: var(--font-size-md);
  color: var(--color-text-primary);
}

.ultra-low-memory-hint {
  margin: 0;
  font-size: 13px;
  color: var(--color-text-secondary);
  line-height: 1.5;
}

/* 激活部分样式 */
.activation-section {
  padding: var(--space-sm) 0;
}

.activation-status {
  margin-bottom: var(--space-lg);
}

.status-row {
  display: flex;
  align-items: center;
  margin-bottom: var(--space-md);
}

.status-row:last-child {
  margin-bottom: 0;
}

.status-label {
  font-weight: var(--font-weight-medium);
  color: var(--color-text-regular);
  min-width: 80px;
}

.status-value {
  color: var(--color-text-primary);
  font-weight: var(--font-weight-semibold);
}

.machine-code-wrapper {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}

.machine-code {
  font-family: var(--font-mono);
  font-size: var(--font-size-base);
  letter-spacing: 1px;
  background: var(--bg-dark-muted);
  padding: 6px var(--space-md);
  border-radius: var(--radius-sm);
  color: var(--color-text-primary);
}

.dark-theme .machine-code {
  background: rgba(255, 255, 255, 0.08);
  color: var(--brand-color-start);
}

.activation-actions {
  margin-top: var(--space-base);
}

/* 激活信息样式 */
.activation-info {
  margin-top: var(--space-base);
}

.activation-info :deep(.el-divider__text) {
  color: var(--color-text-regular);
  font-size: var(--font-size-base);
}

.info-section {
  padding: var(--space-md) var(--space-base);
  background: var(--bg-dark-muted);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border-light);
}

.info-text {
  margin: 0 0 var(--space-base) 0;
  color: var(--color-text-regular);
  font-size: var(--font-size-base);
  line-height: var(--line-height-relaxed);
}

.sales-info {
  padding-bottom: var(--space-md);
  border-bottom: 1px dashed var(--color-border);
}

.price-info,
.contact-info {
  margin-bottom: var(--space-md);
}

.contact-info {
  margin-bottom: 0;
}

.price-title,
.contact-title {
  margin: 0 0 var(--space-sm) 0;
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  font-size: var(--font-size-base);
}

.price-list {
  margin: 0;
  padding-left: var(--space-lg);
  list-style: none;
}

.price-list li {
  margin: 6px 0;
  color: var(--color-text-regular);
  font-size: var(--font-size-base);
  position: relative;
}

.price-list li::before {
  content: '•';
  position: absolute;
  left: -12px;
  color: var(--color-primary);
}

.price {
  font-weight: var(--font-weight-semibold);
  color: var(--color-primary);
}

.price.original {
  color: var(--color-text-secondary);
  text-decoration: line-through;
}

.discount {
  color: var(--color-warning);
  font-size: 13px;
}

.special-price {
  font-weight: var(--font-weight-bold);
  color: var(--color-danger);
  font-size: var(--font-size-lg);
}

.contact-detail {
  margin: 0;
  color: var(--color-text-regular);
  font-size: var(--font-size-base);
}

.highlight {
  font-weight: var(--font-weight-semibold);
  color: var(--color-primary);
}

.deerflow-badge {
  position: fixed;
  bottom: 20px;
  right: 20px;
  color: rgba(0, 0, 0, 0.3);
  text-decoration: none;
  font-size: 12px;
  transition: all 0.3s;
}

.dark-theme .deerflow-badge {
  color: rgba(255, 255, 255, 0.3);
}

.deerflow-badge:hover {
  color: rgba(0, 0, 0, 0.6);
}

.dark-theme .deerflow-badge:hover {
  color: rgba(255, 255, 255, 0.6);
}

@media (max-width: 768px) {
  .settings-container {
    padding: 16px;
  }
  
  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
