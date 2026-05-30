<template>
  <el-card class="emotion-tag-manager" shadow="hover" v-loading="isLoading">
    <template #header>
      <div class="card-header">
        <el-icon><Emoji /></el-icon>
        <span>情绪标签管理</span>
      </div>
    </template>

    <div class="manager-content">
      <div class="action-bar">
        <el-button type="primary" class="create-emotion-btn" @click="showCreateDialog = true">
          <el-icon><Plus /></el-icon>
          新建情绪标签
        </el-button>
      </div>

      <el-table :data="emotions" stripe style="width: 100%">
        <el-table-column prop="name" label="名称" width="120" />
        <el-table-column label="向量参数">
          <template #default="{ row }">
            <div class="vec-display">
              <span v-for="(val, idx) in getVecValues(row)" :key="idx" class="vec-item">
                v{{ idx + 1 }}: {{ val }}
              </span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="speed" label="语速" width="80" />
        <el-table-column label="操作" width="150">
          <template #default="{ row }">
            <el-button type="primary" size="small" @click="handleEdit(row)">
              编辑
            </el-button>
            <el-button type="danger" size="small" @click="handleDelete(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="showCreateDialog" title="新建情绪标签" width="520px">
      <el-form :model="newEmotionForm" label-width="70px" size="default">
        <el-form-item label="名称">
          <el-input v-model="newEmotionForm.name" placeholder="输入情绪标签名称" />
        </el-form-item>
        <el-form-item label="向量参数">
          <div class="vec-grid">
            <div v-for="i in 8" :key="i" class="vec-field">
              <span class="vec-label">{{ getVecLabel(i) }}</span>
              <el-input-number
                v-model="newEmotionForm[`vec${i}`]"
                :min="0"
                :max="1"
                :step="0.1"
                :precision="2"
                :controls="false"
              />
            </div>
          </div>
        </el-form-item>
        <el-form-item label="语速">
          <el-input-number
            v-model="newEmotionForm.speed"
            :min="0.8"
            :max="1.2"
            :step="0.05"
            :precision="2"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="handleCreate">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showEditDialog" title="编辑情绪标签" width="520px">
      <el-form :model="editEmotionForm" label-width="70px" size="default">
        <el-form-item label="名称">
          <el-input v-model="editEmotionForm.name" placeholder="输入情绪标签名称" />
        </el-form-item>
        <el-form-item label="向量参数">
          <div class="vec-grid">
            <div v-for="i in 8" :key="i" class="vec-field">
              <span class="vec-label">{{ getVecLabel(i) }}</span>
              <el-input-number
                v-model="editEmotionForm[`vec${i}`]"
                :min="0"
                :max="1"
                :step="0.1"
                :precision="2"
                :controls="false"
              />
            </div>
          </div>
        </el-form-item>
        <el-form-item label="语速">
          <el-input-number
            v-model="editEmotionForm.speed"
            :min="0.8"
            :max="1.2"
            :step="0.05"
            :precision="2"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showEditDialog = false">取消</el-button>
        <el-button type="primary" @click="handleUpdate">确定</el-button>
      </template>
    </el-dialog>

    <el-alert v-if="error" :title="error" type="error" show-icon @close="clearError" />
  </el-card>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Sunny } from '@element-plus/icons-vue'
import { useTagStore } from '@/stores/tagStore'

const tagStore = useTagStore()

const emotions = ref([])
const isLoading = ref(false)
const error = ref(null)

const showCreateDialog = ref(false)
const showEditDialog = ref(false)

const newEmotionForm = ref({
  name: '',
  vec1: 0, vec2: 0, vec3: 0, vec4: 0, vec5: 0, vec6: 0, vec7: 0, vec8: 0,
  speed: 1.0
})

const editEmotionForm = ref({
  id: null,
  name: '',
  vec1: 0, vec2: 0, vec3: 0, vec4: 0, vec5: 0, vec6: 0, vec7: 0, vec8: 0,
  speed: 1.0
})

const getVecValues = (row) => {
  return [row.vec1, row.vec2, row.vec3, row.vec4, row.vec5, row.vec6, row.vec7, row.vec8]
    .map(v => v || 0)
}

const getVecLabel = (index) => {
  const labels = ['高兴', '生气', '悲伤', '恐惧', '厌恶', '忧郁', '惊讶', '平静']
  return labels[index - 1] || `v${index}`
}

const loadEmotions = async () => {
  isLoading.value = true
  try {
    emotions.value = await tagStore.fetchEmotionTags()
  } catch (e) {
    error.value = e.message || '加载情绪标签失败'
  } finally {
    isLoading.value = false
  }
}

const handleCreate = async () => {
  if (!newEmotionForm.value.name.trim()) {
    ElMessage.warning('请输入情绪标签名称')
    return
  }

  isLoading.value = true
  try {
    // 1. 创建情绪标签
    await tagStore.createEmotionTag({
      name: newEmotionForm.value.name,
      vec1: newEmotionForm.value.vec1,
      vec2: newEmotionForm.value.vec2,
      vec3: newEmotionForm.value.vec3,
      vec4: newEmotionForm.value.vec4,
      vec5: newEmotionForm.value.vec5,
      vec6: newEmotionForm.value.vec6,
      vec7: newEmotionForm.value.vec7,
      vec8: newEmotionForm.value.vec8,
      speed: newEmotionForm.value.speed
    })

    // 2. 同步到 YAML
    const result = await tagStore.syncEmotionsToYaml()
    if (result.synced) {
      ElMessage.success('情绪标签创建成功并已同步')
    } else {
      ElMessage.success('情绪标签创建成功')
    }

    showCreateDialog.value = false
    resetNewForm()
    await loadEmotions()
  } catch (e) {
    error.value = e.message || '创建失败'
  } finally {
    isLoading.value = false
  }
}

const handleEdit = (row) => {
  editEmotionForm.value = {
    id: row.id,
    name: row.name,
    vec1: row.vec1 || 0,
    vec2: row.vec2 || 0,
    vec3: row.vec3 || 0,
    vec4: row.vec4 || 0,
    vec5: row.vec5 || 0,
    vec6: row.vec6 || 0,
    vec7: row.vec7 || 0,
    vec8: row.vec8 || 0,
    speed: row.speed || 1.0
  }
  showEditDialog.value = true
}

const handleUpdate = async () => {
  if (!editEmotionForm.value.name.trim()) {
    ElMessage.warning('请输入情绪标签名称')
    return
  }

  isLoading.value = true
  try {
    // 1. 更新情绪标签
    await tagStore.updateEmotionTag(editEmotionForm.value.id, {
      name: editEmotionForm.value.name,
      vec1: editEmotionForm.value.vec1,
      vec2: editEmotionForm.value.vec2,
      vec3: editEmotionForm.value.vec3,
      vec4: editEmotionForm.value.vec4,
      vec5: editEmotionForm.value.vec5,
      vec6: editEmotionForm.value.vec6,
      vec7: editEmotionForm.value.vec7,
      vec8: editEmotionForm.value.vec8,
      speed: editEmotionForm.value.speed
    })

    // 2. 同步到 YAML
    const result = await tagStore.syncEmotionsToYaml()
    if (result.synced) {
      ElMessage.success('情绪标签更新成功并已同步')
    } else {
      ElMessage.success('情绪标签更新成功')
    }

    showEditDialog.value = false
    await loadEmotions()
  } catch (e) {
    error.value = e.message || '更新失败'
  } finally {
    isLoading.value = false
  }
}

const handleDelete = async (row) => {
  try {
    await ElMessageBox.confirm(`确定要删除情绪标签"${row.name}"吗？`, '确认删除', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning'
    })
    
    isLoading.value = true
    await tagStore.deleteEmotionTag(row.id)
    ElMessage.success('情绪标签删除成功')
    await loadEmotions()
  } catch (e) {
    if (e !== 'cancel') {
      error.value = e.message || '删除失败'
    }
  } finally {
    isLoading.value = false
  }
}

const resetNewForm = () => {
  newEmotionForm.value = {
    name: '',
    vec1: 0, vec2: 0, vec3: 0, vec4: 0, vec5: 0, vec6: 0, vec7: 0, vec8: 0,
    speed: 1.0
  }
}

const clearError = () => {
  error.value = null
}

onMounted(() => {
  loadEmotions()
})
</script>

<style scoped>
.emotion-tag-manager {
  margin-bottom: 24px;
}

.card-header {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 16px;
  font-weight: 600;
}

.card-header .el-icon {
  font-size: 20px;
  color: #409EFF;
}

.manager-content {
  min-height: 200px;
}

.action-bar {
  display: flex;
  gap: 16px;
  margin-bottom: 16px;
}

.vec-display {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.vec-item {
  font-size: 12px;
  color: #606266;
  background: #f5f7fa;
  padding: 2px 6px;
  border-radius: 4px;
}

/* 对话框内向量编辑：两列四行网格 */
.vec-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  row-gap: 8px;
  column-gap: 16px;
  width: 100%;
}

.vec-field {
  display: flex;
  align-items: center;
  gap: 6px;
}

.vec-label {
  font-size: 13px;
  color: #909399;
  min-width: 20px;
  text-align: center;
  line-height: 24px;
  font-weight: 900;
  font-family: 'Consolas', 'Monaco', monospace;
}

/* 关键：强制 el-input-number 填满网格单元 */
.vec-field :deep(.el-input-number) {
  width: 100% !important;
}

.vec-field :deep(.el-input-number .el-input__wrapper) {
  padding-left: 6px;
  padding-right: 6px;
}

.vec-field :deep(.el-input-number .el-input__inner) {
  text-align: center;
  font-size: 13px;
}

/* 修复向量参数与语速重叠：让 form-item 高度自适应 */
:deep(.el-form-item__content) {
  flex-wrap: wrap;
}

:deep(.el-table) {
  font-size: 14px;
}

:deep(.el-table th) {
  background-color: #f5f7fa;
}
</style>