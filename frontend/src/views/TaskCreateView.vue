<template>
  <div class="task-create-page">
    <el-page-header title="新建任务" @back="goBack" />
    
    <!-- 文件上传隐藏输入 -->
    <input 
      ref="fileInput" 
      type="file" 
      style="display: none" 
      @change="handleFileUpload"
      :accept="fileInputAccept"
    />
    
    <div class="main-content">
      <!-- 左侧主区域 -->
      <div class="left-section">
        <el-form ref="formRef" :model="taskForm" :rules="rules" label-position="top">
          <!-- 基本信息 -->
          <el-card class="form-card">
            <template #header>
              <div class="card-header">
                <span>基本信息</span>
              </div>
            </template>
            
            <el-form-item label="任务名称">
              <el-input 
                v-model="taskForm.name" 
                placeholder="输入任务名称（可选，未填写时系统自动生成）"
                maxlength="100"
                show-word-limit
              />
            </el-form-item>
          </el-card>

          <!-- 视频素材 -->
          <el-card class="form-card">
            <template #header>
              <div class="card-header">
                <span>视频素材</span>
              </div>
            </template>
            
            <!-- 开场视频 -->
            <el-form-item label="开场视频" prop="openingVideo" required>
              <div class="video-upload-section">
                <div v-if="taskForm.openingVideo" class="video-item">
                  <div class="video-info">
                    <el-icon><VideoCamera /></el-icon>
                    <span class="video-name" :title="taskForm.openingVideo.name">{{ taskForm.openingVideo.name }}</span>
                    <div class="video-preview">
                      <video :src="'/api/files/' + taskForm.openingVideo.path + (taskForm.openingVideo.timestamp ? '?t=' + taskForm.openingVideo.timestamp : '')" controls width="200" height="150" class="preview-video"></video>
                    </div>
                  </div>
                  <div class="video-actions">
                    <MediaClipper
                      :file-path="taskForm.openingVideo.path"
                      media-type="video"
                      :is-dark-theme="isDarkTheme"
                      @clipped="handleVideoClipped"
                    />
                    <el-button type="primary" link @click="analyzeFace('opening')" :loading="faceAnalysisLoading[taskForm.openingVideo?.path] && faceAnalysisLoading[taskForm.openingVideo?.path] !== 'completed'" :disabled="(faceAnalysisLoading[taskForm.openingVideo?.path] && faceAnalysisLoading[taskForm.openingVideo?.path] !== 'completed') || analyzedVideoPaths[taskForm.openingVideo?.path]">
                      <el-icon><Search /></el-icon> {{ faceAnalysisLoading[taskForm.openingVideo?.path] === 'completed' ? '已完成' : (faceAnalysisLoading[taskForm.openingVideo?.path] || analyzedVideoPaths[taskForm.openingVideo?.path] ? '分析中...' : '面部分析') }}
                    </el-button>
                    <el-button type="danger" link @click="removeVideo('opening')">
                      <el-icon><Delete /></el-icon> 移除
                    </el-button>
                  </div>
                </div>
                <div v-else class="upload-buttons">
                  <el-button type="primary" plain @click="uploadLocalVideo('opening')">
                    <el-icon><Upload /></el-icon> 上传本地视频
                  </el-button>
                </div>
              </div>
            </el-form-item>
            
            <!-- 循环视频 -->
            <el-form-item label="循环视频">
              <div class="video-upload-section">
                <div
                  v-for="(video, index) in taskForm.loopVideos"
                  :key="index"
                  class="video-item"
                >
                  <div class="video-info">
                    <el-icon><VideoCamera /></el-icon>
                    <span class="video-name" :title="video.name">{{ video.name }}</span>
                    <div class="video-preview">
                      <video :src="'/api/files/' + video.path + (video.timestamp ? '?t=' + video.timestamp : '')" controls width="640" height="360" class="preview-video"></video>
                    </div>
                  </div>
                  <div class="video-actions">
                    <MediaClipper
                      :file-path="video.path"
                      media-type="video"
                      :is-dark-theme="isDarkTheme"
                      @clipped="handleVideoClipped"
                    />
                    <el-select v-model="video.emotion" placeholder="选择情绪" size="small" class="emotion-select">
                      <el-option label="开心" value="happy" />
                      <el-option label="生气" value="angry" />
                      <el-option label="难过" value="sad" />
                      <el-option label="害怕" value="fear" />
                      <el-option label="厌恶" value="disgust" />
                      <el-option label="低落" value="depressed" />
                      <el-option label="惊喜" value="surprised" />
                      <el-option label="冷静" value="calm" />
                    </el-select>
                    <el-button type="primary" link @click="analyzeFace('loop', index)" :loading="faceAnalysisLoading[video?.path] && faceAnalysisLoading[video?.path] !== 'completed'" :disabled="(faceAnalysisLoading[video?.path] && faceAnalysisLoading[video?.path] !== 'completed') || analyzedVideoPaths[video?.path]">
                      <el-icon><Search /></el-icon> {{ faceAnalysisLoading[video?.path] === 'completed' ? '已完成' : (faceAnalysisLoading[video?.path] || analyzedVideoPaths[video?.path] ? '分析中...' : '面部分析') }}
                    </el-button>
                    <el-button type="danger" link @click="removeLoopVideo(index)">
                      <el-icon><Delete /></el-icon> 移除
                    </el-button>
                  </div>
                </div>
                <div v-if="taskForm.loopVideos.length < 5" class="upload-buttons">
                  <el-button type="primary" plain @click="uploadLocalVideo('loop')">
                    <el-icon><Upload /></el-icon> 上传本地视频
                  </el-button>
                </div>
              </div>
            </el-form-item>
            
            <!-- 结束视频 -->
            <el-form-item label="结束视频">
              <div class="video-upload-section">
                <div v-if="taskForm.endingVideo" class="video-item">
                  <div class="video-info">
                    <el-icon><VideoCamera /></el-icon>
                    <span class="video-name" :title="taskForm.endingVideo.name">{{ taskForm.endingVideo.name }}</span>
                    <div class="video-preview">
                      <video :src="'/api/files/' + taskForm.endingVideo.path + (taskForm.endingVideo.timestamp ? '?t=' + taskForm.endingVideo.timestamp : '')" controls width="200" height="150" class="preview-video"></video>
                    </div>
                  </div>
                  <div class="video-actions">
                    <MediaClipper
                      :file-path="taskForm.endingVideo.path"
                      media-type="video"
                      :is-dark-theme="isDarkTheme"
                      @clipped="handleVideoClipped"
                    />
                    <el-button type="primary" link @click="analyzeFace('ending')" :loading="faceAnalysisLoading[taskForm.endingVideo?.path] && faceAnalysisLoading[taskForm.endingVideo?.path] !== 'completed'" :disabled="(faceAnalysisLoading[taskForm.endingVideo?.path] && faceAnalysisLoading[taskForm.endingVideo?.path] !== 'completed') || analyzedVideoPaths[taskForm.endingVideo?.path]">
                      <el-icon><Search /></el-icon> {{ faceAnalysisLoading[taskForm.endingVideo?.path] === 'completed' ? '已完成' : (faceAnalysisLoading[taskForm.endingVideo?.path] || analyzedVideoPaths[taskForm.endingVideo?.path] ? '分析中...' : '面部分析') }}
                    </el-button>
                    <el-button type="danger" link @click="removeVideo('ending')">
                      <el-icon><Delete /></el-icon> 移除
                    </el-button>
                  </div>
                </div>
                <div v-else class="upload-buttons">
                  <el-button type="primary" plain @click="uploadLocalVideo('ending')">
                    <el-icon><Upload /></el-icon> 上传本地视频
                  </el-button>
                </div>
              </div>
            </el-form-item>
            
            <!-- 场景视频 -->
            <el-form-item label="场景视频">
              <div class="video-upload-section">
                <div class="tag-group-selector">
                  <span class="selector-label">标签组：</span>
                  <el-select
                    v-model="taskForm.sceneTagGroupId"
                    placeholder="选择标签组"
                    class="tag-group-select"
                    @change="handleTagGroupChange"
                  >
                    <el-option
                      v-for="group in sceneTagGroups"
                      :key="group.id"
                      :label="group.name"
                      :value="group.id"
                    />
                  </el-select>
                </div>
                <div
                  v-for="(video, index) in taskForm.sceneVideos"
                  :key="index"
                  class="video-item"
                >
                  <div class="video-info">
                    <el-icon><VideoCamera /></el-icon>
                    <span class="video-name" :title="video.name">{{ video.name }}</span>
                    <div class="video-preview">
                      <video :src="'/api/files/' + video.path + (video.timestamp ? '?t=' + video.timestamp : '')" controls width="640" height="360" class="preview-video"></video>
                    </div>
                  </div>
                  <div class="video-actions">
                    <MediaClipper
                      :file-path="video.path"
                      media-type="video"
                      :is-dark-theme="isDarkTheme"
                      @clipped="handleVideoClipped"
                    />
                    <el-select v-model="video.scene" placeholder="选择场景" size="small" class="scene-select">
                      <el-option
                        v-for="tag in sceneTagOptions"
                        :key="tag.id"
                        :label="tag.name"
                        :value="tag.name"
                      />
                    </el-select>
                    <el-button type="danger" link @click="removeSceneVideo(index)">
                      <el-icon><Delete /></el-icon> 移除
                    </el-button>
                  </div>
                </div>
                <div v-if="taskForm.sceneVideos.length < 5" class="upload-buttons">
                  <el-button type="primary" plain @click="uploadLocalVideo('scene')">
                    <el-icon><Upload /></el-icon> 上传本地视频
                  </el-button>
                </div>
              </div>
            </el-form-item>
            
            <!-- 视频参数 -->
            <div class="video-params">
              <el-row :gutter="20">
                <el-col :span="8">
                  <el-form-item label="原始参数">
                    <el-switch v-model="taskForm.videoParams.heygemOriginal" />
                  </el-form-item>
                </el-col>
                <el-col :span="8">
                  <el-form-item label="推理批次">
                    <el-input-number v-model="taskForm.videoParams.inferenceSteps" :min="4" :max="32" :step="4" />
                  </el-form-item>
                </el-col>
                <el-col :span="8">
                  <el-form-item label="双人模式">
                    <el-switch v-model="taskForm.videoParams.dualMode" @change="handleDualModeChange" />
                  </el-form-item>
                </el-col>
              </el-row>
            </div>
          </el-card>

          <!-- 音频素材 -->
          <el-card class="form-card">
            <template #header>
              <div class="card-header">
                <span>参考音频</span>
              </div>
            </template>
            
            <!-- 单人模式音频 -->
            <template v-if="!taskForm.videoParams.dualMode">
              <el-form-item label="参考音频" prop="audio" required>
                <div class="audio-upload-section" :key="audioRefreshKey">
                  <div v-if="taskForm.audio" class="audio-item">
                    <div class="audio-info">
                      <el-icon><Microphone /></el-icon>
                      <span :title="taskForm.audio.name">{{ taskForm.audio.name }}</span>
                      <div class="audio-preview">
                        <audio :src="'/api/files/' + taskForm.audio.path + (taskForm.audio.timestamp ? '?t=' + taskForm.audio.timestamp : '')" controls class="preview-audio"></audio>
                      </div>
                    </div>
                    <div class="audio-actions">
                      <el-button type="primary" link @click="denoiseAudio('single')">
                        <el-icon><MagicStick /></el-icon> 降噪增强
                      </el-button>
                      <el-button type="danger" link @click="removeAudio('audio')">
                        <el-icon><Delete /></el-icon> 移除
                      </el-button>
                    </div>
                  </div>
                  <div v-else class="upload-buttons">
                    <el-button type="primary" plain @click="uploadLocalAudio('single')">
                      <el-icon><Upload /></el-icon> 上传本地音频
                    </el-button>
                    <el-button type="primary" plain @click="extractAudio" :disabled="!taskForm.openingVideo">
                      <el-icon><Headset /></el-icon> 提取音频
                    </el-button>
                  </div>
                </div>
              </el-form-item>
            </template>
            
            <!-- 双人模式音频 -->
            <template v-else>
              <el-form-item label="左边说话人" prop="leftAudio" required>
                <div class="audio-upload-section" :key="`left-${audioRefreshKey}`">
                  <div v-if="taskForm.leftAudio" class="audio-item">
                    <div class="audio-info">
                      <el-icon><Microphone /></el-icon>
                      <span :title="taskForm.leftAudio.name">{{ taskForm.leftAudio.name }}</span>
                      <div class="audio-preview">
                        <audio :src="'/api/files/' + taskForm.leftAudio.path + (taskForm.leftAudio.timestamp ? '?t=' + taskForm.leftAudio.timestamp : '')" controls class="preview-audio"></audio>
                      </div>
                    </div>
                    <div class="audio-actions">
                      <el-button type="primary" link @click="denoiseAudio('left')">
                        <el-icon><MagicStick /></el-icon> 降噪增强
                      </el-button>
                      <el-button type="danger" link @click="removeAudio('left')">
                        <el-icon><Delete /></el-icon> 移除
                      </el-button>
                    </div>
                  </div>
                  <div v-else class="upload-buttons">
                    <el-button type="primary" plain @click="uploadLocalAudio('left')">
                      <el-icon><Upload /></el-icon> 上传本地音频
                    </el-button>
                  </div>
                </div>
              </el-form-item>
              
              <el-form-item label="右边说话人" prop="rightAudio" required>
                <div class="audio-upload-section" :key="`right-${audioRefreshKey}`">
                  <div v-if="taskForm.rightAudio" class="audio-item">
                    <div class="audio-info">
                      <el-icon><Microphone /></el-icon>
                      <span :title="taskForm.rightAudio.name">{{ taskForm.rightAudio.name }}</span>
                      <div class="audio-preview">
                        <audio :src="'/api/files/' + taskForm.rightAudio.path + (taskForm.rightAudio.timestamp ? '?t=' + taskForm.rightAudio.timestamp : '')" controls class="preview-audio"></audio>
                      </div>
                    </div>
                    <div class="audio-actions">
                      <el-button type="primary" link @click="denoiseAudio('right')">
                        <el-icon><MagicStick /></el-icon> 降噪增强
                      </el-button>
                      <el-button type="danger" link @click="removeAudio('right')">
                        <el-icon><Delete /></el-icon> 移除
                      </el-button>
                    </div>
                  </div>
                  <div v-else class="upload-buttons">
                    <el-button type="primary" plain @click="uploadLocalAudio('right')">
                      <el-icon><Upload /></el-icon> 上传本地音频
                    </el-button>
                  </div>
                </div>
              </el-form-item>
            </template>
            
            <!-- 音频参数 -->
            <div class="audio-params">
              <template v-if="!taskForm.videoParams.dualMode">
                <el-row :gutter="20">
                  <el-col :span="12">
                    <el-form-item label="语速">
                      <el-slider v-model="taskForm.audioParams.ttsSpeed" :min="0.8" :max="1.2" :step="0.02" />
                      <div class="slider-value">{{ taskForm.audioParams.ttsSpeed }}</div>
                    </el-form-item>
                  </el-col>
                  <el-col :span="12">
                    <el-form-item label="情感权重">
                      <el-slider v-model="taskForm.audioParams.ttsEmoWeight" :min="0.1" :max="1.2" :step="0.1" />
                      <div class="slider-value">{{ taskForm.audioParams.ttsEmoWeight }}</div>
                    </el-form-item>
                  </el-col>
                </el-row>
              </template>
              <template v-else>
                <!-- 左边说话人参数 -->
                <div class="speaker-params">
                  <h4>左边说话人</h4>
                  <el-row :gutter="20">
                    <el-col :span="12">
                      <el-form-item label="语速">
                        <el-slider v-model="taskForm.leftAudioParams.ttsSpeed" :min="0.8" :max="1.2" :step="0.02" />
                        <div class="slider-value">{{ taskForm.leftAudioParams.ttsSpeed }}</div>
                      </el-form-item>
                    </el-col>
                    <el-col :span="12">
                      <el-form-item label="情感权重">
                        <el-slider v-model="taskForm.leftAudioParams.ttsEmoWeight" :min="0.1" :max="1.2" :step="0.1" />
                        <div class="slider-value">{{ taskForm.leftAudioParams.ttsEmoWeight }}</div>
                      </el-form-item>
                    </el-col>
                  </el-row>
                </div>
                <!-- 右边说话人参数 -->
                <div class="speaker-params">
                  <h4>右边说话人</h4>
                  <el-row :gutter="20">
                    <el-col :span="12">
                      <el-form-item label="语速">
                        <el-slider v-model="taskForm.rightAudioParams.ttsSpeed" :min="0.8" :max="1.2" :step="0.02" />
                        <div class="slider-value">{{ taskForm.rightAudioParams.ttsSpeed }}</div>
                      </el-form-item>
                    </el-col>
                    <el-col :span="12">
                      <el-form-item label="情感权重">
                        <el-slider v-model="taskForm.rightAudioParams.ttsEmoWeight" :min="0.1" :max="1.2" :step="0.1" />
                        <div class="slider-value">{{ taskForm.rightAudioParams.ttsEmoWeight }}</div>
                      </el-form-item>
                    </el-col>
                  </el-row>
                </div>
              </template>
            </div>
          </el-card>

          <!-- 文案配置 -->
          <el-card class="form-card">
            <template #header>
              <div class="card-header">
                <span>文案配置</span>
              </div>
            </template>
            
            <!-- 统一的文案输入框 -->
            <el-form-item label="文案内容" prop="scriptContent" required>
              <el-input 
                v-model="taskForm.scriptContent"
                type="textarea"
                :rows="6"
                placeholder="输入文案主题，或点击生成文案"
              />
            </el-form-item>
            
            <!-- 生成按钮 -->
            <el-form-item>
              <el-button 
                type="primary" 
                :loading="taskStore.isGeneratingScript"
                @click="generateScript"
              >
                <el-icon><MagicStick /></el-icon>
                生成文案
              </el-button>
            </el-form-item>
            
            <!-- 标签显示 -->
            <div v-if="scriptTags.length > 0" class="script-tags">
              <span class="tag-label">识别标签：</span>
              <el-tag 
                v-for="tag in scriptTags" 
                :key="tag"
                size="small"
                class="tag-item"
              >
                {{ tag }}
              </el-tag>
            </div>
          </el-card>

          <!-- 后期设定 -->
          <el-card class="form-card">
            <template #header>
              <div class="card-header">
                <span>后期设定</span>
              </div>
            </template>
            
            <el-form-item label="后期处理">
              <el-checkbox-group v-model="taskForm.postProcessing">
                <el-checkbox label="subtitle">添加字幕</el-checkbox>
                <el-checkbox label="bgm">添加BGM</el-checkbox>
                <el-checkbox label="cover">生成封面</el-checkbox>
                <el-checkbox label="transition">转场效果</el-checkbox>
              </el-checkbox-group>
            </el-form-item>

            <!-- 转场效果设置 -->
            <el-form-item v-if="taskForm.postProcessing.includes('transition')" label="转场效果设置" class="transition-settings-wrapper">
              <div class="transition-settings-panel">
                <!-- 转场分类 -->
                <div class="setting-group">
                  <div class="group-title">
                    <el-icon><VideoPlay /></el-icon>
                    <span>转场分类</span>
                  </div>
                  <div class="group-content">
                    <div class="setting-item">
                      <label class="item-label">分类</label>
                      <el-select v-model="taskForm.transitionParams.type" placeholder="选择分类" class="type-select" @change="handleTransitionTypeChange">
                        <el-option v-for="category in transitionCategories" :key="category" :label="category" :value="category" />
                      </el-select>
                    </div>
                    <div class="setting-item">
                      <label class="item-label">效果</label>
                      <el-select v-model="taskForm.transitionParams.effect" placeholder="选择效果" class="effect-select" :disabled="taskForm.transitionParams.random">
                        <el-option v-for="effect in currentTransitionEffects" :key="effect.value" :label="effect.name" :value="effect.value" />
                      </el-select>
                    </div>
                  </div>
                </div>

                <!-- 随机效果 -->
                <div class="setting-group">
                  <div class="group-title">
                    <el-icon><MagicStick /></el-icon>
                    <span>随机效果</span>
                  </div>
                  <div class="group-content">
                    <div class="setting-item">
                      <el-checkbox v-model="taskForm.transitionParams.random" @change="handleTransitionRandomChange">
                        启用随机效果
                      </el-checkbox>
                    </div>
                    <div class="setting-item" v-if="taskForm.transitionParams.random">
                      <el-checkbox v-model="taskForm.transitionParams.randomAll">
                        每次转场都随机（不勾选则整个视频统一使用一个随机效果）
                      </el-checkbox>
                    </div>
                  </div>
                </div>

                <!-- 持续时间 -->
                <div class="setting-group">
                  <div class="group-title">
                    <el-icon><Clock /></el-icon>
                    <span>转场时长</span>
                  </div>
                  <div class="group-content">
                    <div class="setting-item">
                      <label class="item-label">时长</label>
                      <el-slider
                        v-model="taskForm.transitionParams.duration"
                        :min="0.5"
                        :max="5.0"
                        :step="0.1"
                        show-input
                        class="duration-slider"
                      />
                      <span class="slider-unit">秒</span>
                    </div>
                  </div>
                </div>
              </div>
            </el-form-item>
            
            <!-- 字幕设置 -->
            <el-form-item v-if="taskForm.postProcessing.includes('subtitle')" label="字幕设置" class="subtitle-settings-wrapper">
              <div class="subtitle-settings-panel">
                <!-- 左侧区域：样式设置 -->
                <div class="subtitle-style-section">
                  <!-- 文字样式组 -->
                  <div class="setting-group">
                    <div class="group-title">
                      <el-icon><Edit /></el-icon>
                      <span>文字样式</span>
                    </div>
                    <div class="group-content">
                      <div class="setting-item">
                        <label class="item-label">字体</label>
                        <el-select v-model="taskForm.subtitleParams.font" placeholder="选择字体" class="font-select">
                          <el-option label="微软雅黑" value="Microsoft YaHei" />
                          <el-option label="宋体" value="SimSun" />
                          <el-option label="黑体" value="SimHei" />
                          <el-option label="楷体" value="KaiTi" />
                          <el-option label="仿宋" value="FangSong" />
                        </el-select>
                      </div>
                      <div class="setting-item">
                        <label class="item-label">字号</label>
                        <el-input-number 
                          v-model="taskForm.subtitleParams.fontSize" 
                          :min="10" 
                          :max="48" 
                          :step="2"
                          class="number-input"
                        />
                      </div>
                      <div class="setting-item color-item">
                        <label class="item-label">颜色</label>
                        <el-color-picker v-model="taskForm.subtitleParams.color" show-alpha :predefine="predefineColors" />
                      </div>
                    </div>
                  </div>
                  
                  <!-- 描边样式组 -->
                  <div class="setting-group">
                    <div class="group-title">
                      <el-icon><CircleCheck /></el-icon>
                      <span>描边样式</span>
                    </div>
                    <div class="group-content">
                      <div class="setting-item color-item">
                        <label class="item-label">描边颜色</label>
                        <el-color-picker v-model="taskForm.subtitleParams.strokeColor" :predefine="predefineColors" />
                      </div>
                      <div class="setting-item">
                        <label class="item-label">描边宽度</label>
                        <el-input-number 
                          v-model="taskForm.subtitleParams.strokeWidth" 
                          :min="0" 
                          :max="4" 
                          :step="0.2"
                          class="number-input"
                        />
                      </div>
                      <div class="setting-item">
                        <label class="item-label">背景透明</label>
                        <el-input-number 
                          v-model="taskForm.subtitleParams.backgroundAlpha" 
                          :min="0" 
                          :max="1" 
                          :step="0.1"
                          class="number-input"
                        />
                      </div>
                    </div>
                  </div>
                </div>
                
                <!-- 右侧区域：位置设置（上）和预览（下） -->
                <div class="subtitle-right-section">
                  <!-- 字幕位置 - 横置 -->
                  <div class="position-card-horizontal">
                    <div class="position-title">
                      <el-icon><Location /></el-icon>
                      <span>字幕位置</span>
                    </div>
                    <div class="position-options-horizontal">
                      <div 
                        v-for="pos in positionOptions" 
                        :key="pos.value"
                        class="position-option-horizontal"
                        :class="{ active: taskForm.subtitleParams.position === pos.value }"
                        @click="taskForm.subtitleParams.position = pos.value"
                      >
                        <el-icon :size="18"><component :is="pos.icon" /></el-icon>
                        <span class="option-label">{{ pos.label }}</span>
                      </div>
                    </div>
                  </div>
                  
                  <!-- 字幕预览 -->
                  <div class="preview-card">
                    <div class="preview-title">
                      <el-icon><View /></el-icon>
                      <span>效果预览</span>
                    </div>
                    <div class="preview-container" :class="'position-' + taskForm.subtitleParams.position">
                      <div 
                        class="preview-subtitle"
                        :style="{
                          fontFamily: taskForm.subtitleParams.font,
                          fontSize: taskForm.subtitleParams.fontSize + 'px',
                          color: taskForm.subtitleParams.color,
                          WebkitTextStroke: taskForm.subtitleParams.strokeWidth + 'px ' + taskForm.subtitleParams.strokeColor,
                          backgroundColor: 'rgba(0, 0, 0, ' + taskForm.subtitleParams.backgroundAlpha + ')'
                        }"
                      >
                        字幕预览效果
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </el-form-item>
            
            <!-- BGM设置 -->
            <el-form-item v-if="taskForm.postProcessing.includes('bgm')" label="BGM设置">
              <div class="bgm-setting-container">
                <!-- 第一行：BGM选择器 -->
                <div class="bgm-row">
                  <div class="row-label">选择BGM</div>
                  <div class="row-content">
                    <el-select v-model="updateSelectedBgm" placeholder="选择背景音乐" style="width: 100%;">
                      <el-option 
                        v-for="bgm in bgmList" 
                        :key="bgm.id"
                        :label="bgm.name"
                        :value="bgm.id"
                      />
                    </el-select>
                  </div>
                </div>
                
                <!-- 第二行：上传本地音频或播放组件 -->
                <div class="bgm-row">
                  <div class="row-label"></div>
                  <div class="row-content">
                    <div class="bgm-second-row">
                      <!-- 未选择时显示上传按钮 -->
                      <div v-if="!hasSelectedBgm" class="upload-section">
                        <el-button type="primary" plain @click="uploadLocalBGM">
                          <el-icon><Upload /></el-icon> 上传本地音频
                        </el-button>
                      </div>
                      
                      <!-- 已选择时显示播放组件 -->
                      <div v-else class="play-section">
                        <div class="audio-item">
                          <div class="audio-info">
                            <el-icon><Microphone /></el-icon>
                            <span :title="taskForm.bgm?.name || bgmList.find(b => b.id === taskForm.bgmParams.bgmId)?.name">
                              {{ taskForm.bgm?.name || bgmList.find(b => b.id === taskForm.bgmParams.bgmId)?.name }}
                            </span>
                            <div class="audio-preview">
                              <audio 
                                :src="'/api/files/' + (taskForm.bgm?.path || bgmList.find(b => b.id === taskForm.bgmParams.bgmId)?.path)" 
                                controls 
                                class="preview-audio"
                              ></audio>
                            </div>
                          </div>
                          <div class="audio-actions">
                            <el-button type="danger" link @click="removeBgm">
                              <el-icon><Delete /></el-icon> 移除
                            </el-button>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
                
                <!-- 第三行：BGM强度 -->
                <div class="bgm-row">
                  <div class="row-label">BGM强度</div>
                  <div class="row-content">
                    <el-slider v-model="taskForm.bgmParams.intensity" :min="0.1" :max="1.0" :step="0.1" />
                    <div class="slider-value">{{ taskForm.bgmParams.intensity }}</div>
                  </div>
                </div>
              </div>
            </el-form-item>
          </el-card>

          <!-- 提交按钮 -->
          <div class="form-actions">
            <el-button @click="goBack">取消</el-button>
            <el-button 
              type="primary"
              @click="submitTask(false)"
            >
              <el-icon><Plus /></el-icon>
              添加任务
            </el-button>
            <el-button 
              type="primary" 
              size="large"
              :loading="taskStore.isCreating"
              @click="submitTask(true)"
            >
              <el-icon><VideoPlay /></el-icon>
              立刻运行
            </el-button>
          </div>
        </el-form>
      </div>
      
      <!-- 右侧素材库窗口 -->
      <div class="right-section">
        <div class="material-sidebar">
          <h3>素材库</h3>
          
          <!-- 角色素材 -->
          <div class="material-category">
            <h4>角色素材</h4>
            <div class="material-list">
              <div 
                v-for="role in roleList" 
                :key="role.id"
                class="material-item"
                @click="selectRole(role)"
              >
                <div class="material-thumbnail">
                  <img 
                    v-if="role.thumbnail" 
                    :src="getFileUrl(role.thumbnail)" 
                    :alt="role.name"
                    @error="handleThumbnailError($event, role)"
                  />
                  <el-icon v-else><User /></el-icon>
                </div>
                <div class="material-name">{{ role.name }}</div>
              </div>
            </div>
          </div>
          
          <!-- 场景素材 -->
          <div class="material-category">
            <h4>场景素材</h4>
            <div class="material-list">
              <div 
                v-for="scene in sceneList" 
                :key="scene.id"
                class="material-item"
                @click="selectScene(scene)"
              >
                <div class="material-thumbnail">
                  <img 
                    v-if="scene.thumbnail" 
                    :src="getFileUrl(scene.thumbnail)" 
                    :alt="scene.name"
                    @error="handleThumbnailError($event, scene)"
                  />
                  <el-icon v-else><Picture /></el-icon>
                </div>
                <div class="material-name">{{ scene.name }}</div>
              </div>
            </div>
          </div>
          
          <!-- 参考音频 -->
          <div class="material-category">
            <h4>参考音频</h4>
            <div class="material-list">
              <div 
                v-for="audio in audioList" 
                :key="audio.id"
                class="material-item"
                @click="selectReferenceAudio(audio)"
              >
                <div class="material-thumbnail">
                  <el-icon><Microphone /></el-icon>
                </div>
                <div class="material-name">{{ audio.name }}</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 视频选择器弹窗 -->
    <VideoSelectorDialog 
      v-model="showVideoSelectorDialog"
      :videoType="currentVideoType"
      @select="onVideoSelected"
    />
    
    <!-- 音频选择器弹窗 -->
    <AudioSelectorDialog 
      v-model="showAudioSelectorDialog"
      :audioType="currentAudioType"
      @select="onAudioSelected"
    />
    
    <!-- 面部分析弹窗 -->
    <el-dialog
      v-model="showFaceAnalysisDialog"
      title="面部分析结果"
      width="600px"
    >
      <div v-if="faceAnalysisResult" class="face-analysis-result">
        <div class="analysis-item">
          <span class="label">面部数量：</span>
          <span class="value">{{ faceAnalysisResult.faceCount }}</span>
        </div>
        <div class="analysis-item">
          <span class="label">主要表情：</span>
          <span class="value">{{ faceAnalysisResult.mainEmotion }}</span>
        </div>
        <div class="analysis-item">
          <span class="label">面部质量：</span>
          <span class="value">{{ faceAnalysisResult.quality }}</span>
        </div>
      </div>
      <div v-else class="face-analysis-loading">
        <el-icon class="is-loading"><Loading /></el-icon>
        <span>分析中...</span>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, nextTick, inject } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Plus,
  Delete,
  VideoCamera,
  Microphone,
  MagicStick,
  VideoPlay,
  Search,
  Headset,
  User,
  Picture,
  Loading,
  Upload,
  Edit,
  CircleCheck,
  Location,
  Top,
  SemiSelect,
  Bottom,
  Check,
  View,
  Clock
} from '@element-plus/icons-vue'
import { useTaskStore } from '@/stores/taskStore.js'
import { useMaterialStore } from '@/stores/materialStore.js'
import { useSettingsStore } from '@/stores/settingsStore.js'
import { useTagStore } from '@/stores/tagStore.js'
import { taskApi, mediaClipApi } from '@/services/api'
import websocketService from '@/services/websocket'
import VideoSelectorDialog from '@/components/VideoSelectorDialog.vue'
import AudioSelectorDialog from '@/components/AudioSelectorDialog.vue'
import MediaClipper from '@/components/MediaClipper.vue'

const router = useRouter()
const taskStore = useTaskStore()
const materialStore = useMaterialStore()
const settingsStore = useSettingsStore()
const tagStore = useTagStore()

// 表单引用
const formRef = ref(null)

// 注入主题状态
const isDarkTheme = inject('isDarkTheme', ref(false))

// 状态
const showVideoSelectorDialog = ref(false)
const showAudioSelectorDialog = ref(false)
const showFaceAnalysisDialog = ref(false)
const currentVideoType = ref('opening')
const currentAudioType = ref('single')
const faceAnalysisResult = ref(null)
const fileInput = ref(null)
const fileInputAccept = ref('')
const currentUploadType = ref('')

// 表单数据
const taskForm = reactive({
  name: '',
  description: '',
  roleId: null,
  sceneTagGroupId: null,
  // 视频素材
  openingVideo: null,
  loopVideos: [],
  endingVideo: null,
  sceneVideos: [],
  // 音频素材
  audio: null,
  leftAudio: null,
  rightAudio: null,
  // 文案
  scriptContent: '',
  // 视频参数
  videoParams: {
    heygemOriginal: true,
    inferenceSteps: 16,
    dualMode: false
  },
  // 音频参数
  audioParams: {
    ttsSpeed: 1.0,
    ttsEmoWeight: 0.4
  },
  leftAudioParams: {
    ttsSpeed: 1.0,
    ttsEmoWeight: 0.4
  },
  rightAudioParams: {
    ttsSpeed: 1.0,
    ttsEmoWeight: 0.4
  },
  // 后期处理
  postProcessing: ['subtitle'],
  subtitleParams: {
    font: 'Microsoft YaHei',
    color: '#ffffff',
    fontSize: 14,
    strokeColor: '#000000',
    strokeWidth: 0.2,
    position: 'bottom',
    backgroundAlpha: 0.0
  },
  bgmParams: {
    bgmId: null,
    intensity: 0.2
  },
  transitionParams: {
    type: '淡入淡出',
    effect: 'fade',
    random: false,
    randomAll: false,
    duration: 0.5
  },
  bgm: null
})

// 素材列表
const roleList = ref([])
const sceneList = ref([])
const audioList = ref([])
const bgmList = ref([])

// 强制重新渲染计数器
const audioRefreshKey = ref(0)

// 场景标签组
const sceneTagGroups = computed(() => tagStore.sceneTagGroups)

// 场景标签选项
const sceneTagOptions = ref([])

// 表单验证规则
const rules = {
  openingVideo: [
    { required: true, message: '请选择开场视频', trigger: 'change' }
  ],
  audio: [
    { required: true, message: '请选择参考音频', trigger: 'change', validator: () => !taskForm.videoParams.dualMode }
  ],
  leftAudio: [
    { required: true, message: '请选择左边说话人音频', trigger: 'change', validator: () => taskForm.videoParams.dualMode }
  ],
  rightAudio: [
    { required: true, message: '请选择右边说话人音频', trigger: 'change', validator: () => taskForm.videoParams.dualMode }
  ],
  scriptContent: [
    { required: true, message: '请输入文案内容', trigger: 'blur' }
  ]
}

// 文案标签
const scriptTags = computed(() => {
  if (!taskForm.scriptContent) return []
  try {
    const script = JSON.parse(taskForm.scriptContent)
    const tags = []
    if (script.emotions) tags.push(...script.emotions)
    if (script.scenes) tags.push(...script.scenes)
    return tags
  } catch {
    return []
  }
})

// 判断是否已选择BGM
const hasSelectedBgm = computed(() => {
  return taskForm.bgm !== null || taskForm.bgmParams.bgmId !== null
})

// 字幕位置选项
const positionOptions = [
  { value: 'top', label: '顶部', icon: 'Top' },
  { value: 'center', label: '居中', icon: 'SemiSelect' },
  { value: 'bottom', label: '底部', icon: 'Bottom' }
]

// 预定义颜色
const predefineColors = [
  '#ffffff',
  '#000000',
  '#ff0000',
  '#00ff00',
  '#0000ff',
  '#ffff00',
  '#ff00ff',
  '#00ffff',
  '#ff6600',
  '#9900ff'
]

// 转场效果分类
const transitionCategories = ref(['淡入淡出', '滑动擦除', '图形变换', '特效切片'])

// 转场效果映射表（分类 → 效果列表）
const transitionEffectsMap = {
  '淡入淡出': [
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
  return transitionEffectsMap[taskForm.transitionParams.type] || []
})

// 处理转场分类切换
const handleTransitionTypeChange = (category) => {
  // 切换分类时，自动选择该分类下的第一个效果
  const effects = transitionEffectsMap[category]
  if (effects && effects.length > 0) {
    taskForm.transitionParams.effect = effects[0].value
  }
}

// 处理随机效果切换
const handleTransitionRandomChange = (random) => {
  if (random) {
    // 启用随机效果时，清空具体效果选择
    taskForm.transitionParams.randomAll = false
  }
}

const getFileUrl = (path) => {
  if (!path) return ''
  if (path.startsWith('http')) return path
  const normalizedPath = path.replace(/\\/g, '/')
  return `/files/${normalizedPath}`
}

const handleThumbnailError = (event, item) => {
  console.warn('缩略图加载失败:', item.thumbnail)
  item.thumbnail = null
  event.target.style.display = 'none'
}

// 监听bgmId变化，更新taskForm.bgm
const updateSelectedBgm = computed({
  get: () => taskForm.bgmParams.bgmId,
  set: (value) => {
    taskForm.bgmParams.bgmId = value
    if (value) {
      const selected = bgmList.value.find(b => b.id === value)
      if (selected) {
        taskForm.bgm = selected
      }
    } else {
      taskForm.bgm = null
    }
  }
})

// 移除BGM
const removeBgm = () => {
  taskForm.bgm = null
  taskForm.bgmParams.bgmId = null
}

// 返回上一页
const goBack = () => {
  router.push('/')
}

// 显示视频选择器
const showVideoSelector = (type) => {
  currentVideoType.value = type
  showVideoSelectorDialog.value = true
}

// 视频选择回调
const onVideoSelected = (video) => {
  video.videoType = currentVideoType.value
  switch (currentVideoType.value) {
    case 'opening':
      taskForm.openingVideo = video
      break
    case 'loop':
      taskForm.loopVideos.push({ ...video, emotion: 'neutral' })
      break
    case 'ending':
      taskForm.endingVideo = video
      break
    case 'scene':
      taskForm.sceneVideos.push({ ...video, scene: 'other' })
      break
  }
  showVideoSelectorDialog.value = false
  ElMessage.success('视频已添加')
}

// 移除视频
const removeVideo = (type) => {
  taskForm[type + 'Video'] = null
}

// 移除循环视频
const removeLoopVideo = (index) => {
  taskForm.loopVideos.splice(index, 1)
}

// 移除场景视频
const removeSceneVideo = (index) => {
  taskForm.sceneVideos.splice(index, 1)
}

// 显示音频选择器
const showAudioSelector = (type) => {
  currentAudioType.value = type
  showAudioSelectorDialog.value = true
}

// 音频选择回调
const onAudioSelected = (audio) => {
  switch (currentAudioType.value) {
    case 'single':
      taskForm.audio = audio
      break
    case 'left':
      taskForm.leftAudio = audio
      break
    case 'right':
      taskForm.rightAudio = audio
      break
  }
  showAudioSelectorDialog.value = false
  ElMessage.success('音频已选择')
}

// 移除音频
const removeAudio = (type = 'audio') => {
  console.log('点击移除按钮，type:', type)
  console.log('移除前 taskForm.audio:', taskForm.audio)
  console.log('移除前 taskForm.leftAudio:', taskForm.leftAudio)
  console.log('移除前 taskForm.rightAudio:', taskForm.rightAudio)
  
  try {
    if (type === 'audio') {
      taskForm.audio = null
      console.log('已设置 taskForm.audio 为 null')
    } else if (type === 'left') {
      taskForm.leftAudio = null
      console.log('已设置 taskForm.leftAudio 为 null')
    } else if (type === 'right') {
      taskForm.rightAudio = null
      console.log('已设置 taskForm.rightAudio 为 null')
    }
    
    // 强制触发重新渲染
    audioRefreshKey.value++
    console.log('强制重新渲染，audioRefreshKey:', audioRefreshKey.value)
    
    ElMessage.success('音频已移除')
  } catch (error) {
    console.error('移除音频失败:', error)
    ElMessage.error('移除音频失败: ' + error.message)
  }
}

// 双人模式切换
const handleDualModeChange = (value) => {
  if (value) {
    // 切换到双人模式，清空单人音频
    taskForm.audio = null
  } else {
    // 切换到单人模式，清空双人音频
    taskForm.leftAudio = null
    taskForm.rightAudio = null
  }
}

// 视频剪辑处理函数
const handleVideoClipped = (data) => {
  // data: { filePath, startTime, endTime, duration }
  console.log('视频剪辑完成:', data)
  // 视频已原地替换，不需要更新路径，浏览器会通过缓存控制自动刷新
}

// 提取音频
const extractAudio = async () => {
  if (!taskForm.openingVideo) {
    ElMessage.warning('请先选择开场视频')
    return
  }
  
  try {
    const result = await taskStore.extractAudio(taskForm.openingVideo.path)
    taskForm.audio = {
      id: result.data.audio_path.split('/').pop().split('.')[0],
      name: taskForm.openingVideo.name.replace('.mp4', '.wav'),
      path: result.data.audio_path,
      duration: result.data.duration
    }
    ElMessage.success('音频提取成功')
  } catch (error) {
    ElMessage.error('音频提取失败: ' + error.message)
  }
}

// 音频降噪
const denoiseAudio = async (type) => {
  const audio = taskForm[type === 'single' ? 'audio' : type + 'Audio']
  if (!audio) {
    ElMessage.warning('请先选择音频')
    return
  }
  
  try {
    const result = await taskStore.denoiseAudio(audio.path || audio.id)
    // 处理后端返回的数据格式
    const denoiseResult = result.data || result
    if (denoiseResult) {
      // 创建新对象，避免引用问题
      taskForm[type === 'single' ? 'audio' : type + 'Audio'] = {
        ...audio,
        timestamp: new Date().getTime()
      }
    }
    ElMessage.success('音频降噪成功，已更新音频文件')
  } catch (error) {
    ElMessage.error('音频降噪失败: ' + error.message)
  }
}

// 面部分析加载状态
const faceAnalysisLoading = ref({})
// 正在轮询的任务 ID，用于防止重复调用
const pollingTaskIds = ref({})
// 已完成分析的视频路径，用于防止重复分析（使用 ref + 对象，确保响应式更新）
const analyzedVideoPaths = ref({})

// 标记视频已分析的辅助函数（确保响应式更新）
const markVideoAsAnalyzed = (videoPath) => {
  analyzedVideoPaths.value[videoPath] = true
  console.log('[markVideoAsAnalyzed] 已标记路径:', videoPath)
  console.log('[markVideoAsAnalyzed] analyzedVideoPaths 当前内容:', JSON.stringify(analyzedVideoPaths.value))
}

// 面部分析 - 使用异步接口避免超时重试
const analyzeFace = async (type, index = 0) => {
  console.log('[analyzeFace] 调用，类型:', type, '索引:', index)
  let video
  if (type === 'opening') {
    video = taskForm.openingVideo
  } else if (type === 'ending') {
    video = taskForm.endingVideo
  } else if (type === 'loop') {
    video = taskForm.loopVideos[index]
  }

  if (!video) {
    ElMessage.warning('请先选择视频')
    return
  }

  const videoPath = video.path

  // 原子防护：先检查再设置，在同一个同步执行块中完成
  // 检查是否已经在分析中或已完成分析
  if (faceAnalysisLoading.value[videoPath] || pollingTaskIds.value[videoPath]) {
    console.log('[analyzeFace] 视频已在分析中，跳过:', videoPath)
    ElMessage.warning('该视频正在分析中，请等待完成')
    return
  }

  // 检查是否已经分析过（防止重复分析）
  if (analyzedVideoPaths.value[videoPath]) {
    console.log('[analyzeFace] 视频已完成分析，跳过:', videoPath)
    ElMessage.info('该视频已完成面部分析')
    return
  }

  // 立即设置防护状态，防止在 await 期间被再次调用
  faceAnalysisLoading.value[videoPath] = true
  pollingTaskIds.value[videoPath] = 'pending'

  try {
    // 使用异步接口 → AC-227
    const response = await taskApi.analyzeFaceAsync(videoPath)
    console.log('[analyzeFace] 异步面部分析启动:', response)

    if (response.code === 200 || response.task_id) {
      const taskId = response.task_id || response.data?.task_id
      // 更新为真实的 task_id
      pollingTaskIds.value[videoPath] = taskId
      // 轮询状态
      await pollFaceAnalysisStatus(taskId, videoPath, type, index)
      // 轮询结束后清除记录
      delete pollingTaskIds.value[videoPath]
    } else {
      ElMessage.error('面部分析启动失败: ' + (response.message || '未知错误'))
      faceAnalysisLoading.value[videoPath] = false
      delete pollingTaskIds.value[videoPath]
    }
  } catch (error) {
    console.error('[analyzeFace] 面部分析失败:', error)
    // 后端返回 409 表示重复请求，根据 detail 区分处理
    if (error.response?.status === 409) {
      const detail = error.response?.data?.detail || ''
      if (detail.includes('正在分析中')) {
        // 正在分析中：保持 loading 状态，不恢复按钮
        faceAnalysisLoading.value[videoPath] = true
      } else {
        // 已完成分析：标记为已完成
        markVideoAsAnalyzed(videoPath)
        faceAnalysisLoading.value[videoPath] = 'completed'
      }
      console.warn('[analyzeFace] 后端拒绝重复分析:', detail)
    } else {
      ElMessage.error('面部分析失败: ' + (error.message || '未知错误'))
      faceAnalysisLoading.value[videoPath] = false
      delete pollingTaskIds.value[videoPath]
    }
  }
}

// 状态轮询函数 → AC-227
const pollFaceAnalysisStatus = async (taskId, videoPath, type, index) => {
  const maxPolls = 120  // 最多轮询 120 次（2 分钟）
  const pollInterval = 1000  // 1 秒

  for (let i = 0; i < maxPolls; i++) {
    try {
      const response = await taskApi.getFaceAnalysisStatus(taskId)
      console.log(`[轮询 ${i}] 响应:`, response)

      if (response.code === 200 || response.task_id) {
        const status = response.status || response.data?.status
        const progress = response.progress ?? response.data?.progress ?? 0
        const result = response.result || response.data?.result
        const error = response.error || response.data?.error
        console.log(`[轮询 ${i}] 状态: ${status}, 进度: ${progress}`)

        if (status === 'completed') {
          console.log('[轮询] 检测到完成，退出轮询')
          console.log('[轮询] 标记 analyzedVideoPaths，路径:', videoPath)

          // 立即设置为"已完成"状态，防止在标记 analyzedVideoPaths 之前被再次调用
          faceAnalysisLoading.value[videoPath] = 'completed'

          ElMessage.success(`面部分析完成，已移除 ${result?.invalid_frame_count || 0} 段不合格画面`)

          // 标记该视频已完成分析，防止重复分析
          markVideoAsAnalyzed(videoPath)

          // 视频已原地替换，只需要刷新时间戳让视频重新加载
          const timestamp = new Date().getTime()
          if (type === 'opening') {
            taskForm.openingVideo = {
              ...taskForm.openingVideo,
              timestamp: timestamp
            }
          } else if (type === 'ending') {
            taskForm.endingVideo = {
              ...taskForm.endingVideo,
              timestamp: timestamp
            }
          } else if (type === 'loop') {
            taskForm.loopVideos[index] = {
              ...taskForm.loopVideos[index],
              timestamp: timestamp
            }
          }

          // 保持 completed 状态，不清除，让按钮保持禁用
          console.log('[轮询] 已设置 completed 状态，路径:', videoPath)
          return
        }

        if (status === 'failed') {
          console.log('[轮询] 检测到失败，退出轮询')
          ElMessage.error('面部分析失败: ' + (error || '未知错误'))
          faceAnalysisLoading.value[videoPath] = false
          return
        }

        if (status === 'cancelled') {
          console.log('[轮询] 检测到取消，退出轮询')
          ElMessage.info('面部分析已取消')
          faceAnalysisLoading.value[videoPath] = false
          return
        }

        // 更新进度提示
        if (progress > 0 && i % 10 === 0) {
          ElMessage.info(`面部分析进行中... ${Math.round(progress * 100)}%`)
        }
      }
    } catch (pollError) {
      console.error('状态轮询错误:', pollError)
    }

    // 等待下一次轮询
    await new Promise(resolve => setTimeout(resolve, pollInterval))
  }

  ElMessage.warning('面部分析超时，请稍后查看结果')
  faceAnalysisLoading.value[videoPath] = false
}

// 生成文案
const generateScript = async () => {
  const content = taskForm.scriptContent.trim()
  if (!content) {
    ElMessage.warning('请输入文案主题')
    return
  }
  
  const mode = taskForm.videoParams.dualMode ? 'dual' : 'single'
  const prompt = settingsStore.getPromptTemplate(mode)
  
  try {
    const result = await taskStore.generateScript({
      topic: content,
      prompt: prompt,
      mode: mode
    })
    if (result && result.data && result.data.script) {
      taskForm.scriptContent = result.data.script
    } else {
      taskForm.scriptContent = JSON.stringify(result, null, 2)
    }
    ElMessage.success('文案生成成功')
  } catch (error) {
    ElMessage.error('文案生成失败: ' + error.message)
  }
}

const isValidScriptJson = (content) => {
  if (!content || !content.trim()) return false
  try {
    const parsed = JSON.parse(content)
    return parsed && typeof parsed === 'object'
  } catch {
    return false
  }
}

const autoGenerateScript = async (topic) => {
  const mode = taskForm.videoParams.dualMode ? 'dual' : 'single'
  const prompt = settingsStore.getPromptTemplate(mode)
  
  try {
    const result = await taskStore.generateScript({
      topic: topic,
      prompt: prompt,
      mode: mode
    })
    if (result && result.data && result.data.script) {
      taskForm.scriptContent = result.data.script
      return true
    } else {
      taskForm.scriptContent = JSON.stringify(result, null, 2)
      return true
    }
  } catch (error) {
    ElMessage.error('自动生成文案失败: ' + error.message)
    return false
  }
}

// 选择场景素材
const selectScene = (scene) => {
  console.log('选择场景素材:', scene)
  ElMessage.success(`已选择场景: ${scene.name}`)
  
  // 自动填充场景视频
  if (scene.scene_videos) {
    try {
      const sceneVideos = typeof scene.scene_videos === 'string' 
        ? JSON.parse(scene.scene_videos) 
        : scene.scene_videos
      
      console.log('场景视频数据:', sceneVideos)
      
      if (Array.isArray(sceneVideos) && sceneVideos.length > 0) {
        taskForm.sceneVideos = sceneVideos.map((video, index) => ({
          id: video.id || `scene-${scene.id}-${index}`,
          name: video.name || `${scene.name}_场景视频_${index + 1}`,
          path: video.path,
          scene: video.scene || video.tag || scene.scene_type || 'environment'
        }))
        ElMessage.success(`已自动填充 ${sceneVideos.length} 个场景视频`)
      }
    } catch (e) {
      console.error('解析场景视频失败:', e)
      ElMessage.error('解析场景视频失败')
    }
  } else {
    console.log('场景没有关联视频')
    ElMessage.info('该场景没有关联视频，请手动选择或上传')
  }
}

// 选择参考音频
const selectReferenceAudio = (audio) => {
  if (!taskForm.videoParams.dualMode) {
    taskForm.audio = audio
  } else {
    // 双人模式下，优先填充到左侧说话人
    taskForm.leftAudio = audio
  }
  ElMessage.success(`已选择参考音频: ${audio.name}`)
}

// 上传本地视频
const uploadLocalVideo = (type) => {
  console.log('设置上传类型:', type)
  currentUploadType.value = type
  fileInputAccept.value = '.mp4,.webm,.mov,.avi,.mkv,.wmv,.flv,.m4v,.3gp,.mpg,.mpeg'
  console.log('fileInput引用:', fileInput.value)
  if (fileInput.value) {
    // 重置fileInput，确保可以重新选择文件
    fileInput.value.value = ''
    // 使用nextTick确保accept属性更新到DOM后再点击
    nextTick(() => {
      console.log('点击fileInput')
      fileInput.value.click()
    })
  } else {
    console.error('fileInput 未找到')
    ElMessage.error('上传组件初始化失败，请刷新页面重试')
  }
}

// 上传本地音频
const uploadLocalAudio = (type) => {
  currentUploadType.value = type
  fileInputAccept.value = '.mp3,.wav,.m4a,.aac,.flac,.ogg,.wma,.aiff,.ape,.amr'
  if (fileInput.value) {
    fileInput.value.value = ''
    nextTick(() => {
      fileInput.value.click()
    })
  }
}

// 上传本地BGM
const uploadLocalBGM = () => {
  currentUploadType.value = 'bgm'
  fileInputAccept.value = 'audio/*'
  if (fileInput.value) {
    fileInput.value.value = ''
    nextTick(() => {
      fileInput.value.click()
    })
  }
}

// 从素材库选择
const selectFromMaterial = (type, materialType) => {
  currentUploadType.value = type
  // 这里可以打开素材库选择对话框
  // 暂时使用模拟数据
  ElMessage.info(`从素材库选择${materialType === 'role' ? '角色' : materialType === 'scene' ? '场景' : '音频'}素材`)
}

// 处理文件上传
const handleFileUpload = async (event) => {
  const file = event.target.files[0]
  if (!file) return
  
  // 保存当前的上传类型，防止在上传过程中发生变化
  const uploadType = currentUploadType.value
  console.log('开始上传，类型:', uploadType)
  
  try {
    // 创建FormData对象
    const formData = new FormData()
    formData.append('file', file)
    
    // 添加group_type参数
    let groupType = 'scene' // 默认值
    if (uploadType === 'opening') {
      groupType = 'opening'
    } else if (uploadType === 'loop') {
      groupType = 'loop'
    } else if (uploadType === 'ending') {
      groupType = 'ending'
    } else if (uploadType === 'scene') {
      groupType = 'scene'
    }
    formData.append('group_type', groupType)
    
    // 创建任务时上传的视频保存到 uploads 目录
    formData.append('purpose', 'task')
    
    // 根据文件类型选择上传端点
    const uploadEndpoint = file.type.startsWith('video/') ? '/api/upload/video' : '/api/upload/audio'
    
    // 上传文件到服务器
    const response = await fetch(uploadEndpoint, {
      method: 'POST',
      body: formData
    })
    
    if (!response.ok) {
      throw new Error(`文件上传失败: ${response.status} ${response.statusText}`)
    }
    
    const result = await response.json()
    
    // 检查响应格式
    if (!result || !result.data) {
      throw new Error('服务器返回格式错误')
    }
    
    // 使用服务器返回的文件路径
    const uploadedFile = {
      id: result.data.filename.split('.')[0],
      name: file.name,
      path: result.data.file_path,
      size: result.data.size
    }
    
    // 根据上传类型处理
    if (uploadType === 'opening') {
      taskForm.openingVideo = uploadedFile
    } else if (uploadType === 'loop') {
      taskForm.loopVideos.push({ ...uploadedFile, emotion: 'neutral' })
    } else if (uploadType === 'ending') {
      taskForm.endingVideo = uploadedFile
    } else if (uploadType === 'scene') {
      taskForm.sceneVideos.push({ ...uploadedFile, scene: 'other' })
    } else if (uploadType === 'single') {
      taskForm.audio = uploadedFile
    } else if (uploadType === 'left') {
      taskForm.leftAudio = uploadedFile
    } else if (uploadType === 'right') {
      taskForm.rightAudio = uploadedFile
    } else if (uploadType === 'bgm') {
      // 创建新的BGM素材并添加到列表
      const newBgm = {
        id: uploadedFile.id,
        name: uploadedFile.name,
        path: uploadedFile.path,
        duration: uploadedFile.duration || 0
      }
      bgmList.value.push(newBgm)
      // 自动选择刚上传的BGM
      taskForm.bgmParams.bgmId = newBgm.id
      taskForm.bgm = newBgm
    } else {
      throw new Error('未知的上传类型')
    }
    
    ElMessage.success('文件上传成功')
  } catch (error) {
    console.error('上传错误:', error)
    ElMessage.error('文件上传失败: ' + error.message)
  } finally {
    // 重置文件输入
    event.target.value = ''
  }
}

// 选择角色素材
const selectRole = (role) => {
  console.log('=== selectRole 被调用 ===')
  console.log('选择角色素材完整数据:', role)
  console.log('role.is_double_mode:', role.is_double_mode)
  console.log('role.left_audio_id:', role.left_audio_id)
  console.log('role.right_audio_id:', role.right_audio_id)
  console.log('role.audio_id:', role.audio_id)
  console.log('role.id:', role.id)
  console.log('role.role_id:', role.role_id)
  console.log('Object.keys(role):', Object.keys(role))
  
  ElMessage.success(`已选择角色: ${role.name}`)
  
  taskForm.roleId = role.id || role.role_id
  
  // 检测双人模式
  console.log('检测双人模式 - role.is_double_mode:', role.is_double_mode, '类型:', typeof role.is_double_mode)
  if (role.is_double_mode === true || role.is_double_mode === 'true') {
    console.log('准备开启双人模式')
    taskForm.videoParams.dualMode = true
    ElMessage.success('已自动开启双人模式')
  } else {
    console.log('未检测到双人模式，role.is_double_mode 的值为:', role.is_double_mode)
  }
  
  // 1. 自动填充开场视频
  if (role.opening_video) {
    try {
      // 直接使用字符串路径，不需要解析JSON
      if (typeof role.opening_video === 'string') {
        taskForm.openingVideo = {
          id: `opening-${role.id}`,
          name: `${role.name}_开场视频`,
          path: role.opening_video,
          roleId: role.id
        }
        ElMessage.success('已自动填充开场视频')
      } else if (role.opening_video && role.opening_video.path) {
        // 如果是对象格式
        taskForm.openingVideo = {
          id: role.opening_video.id || `opening-${role.id}`,
          name: role.opening_video.name || `${role.name}_开场视频`,
          path: role.opening_video.path,
          roleId: role.id
        }
        ElMessage.success('已自动填充开场视频')
      }
    } catch (e) {
      console.error('解析开场视频失败:', e)
    }
  } else {
    console.log('角色没有开场视频')
  }
  
  // 2. 自动填充循环视频
  if (role.loop_videos) {
    try {
      const loopVideos = typeof role.loop_videos === 'string' 
        ? JSON.parse(role.loop_videos) 
        : role.loop_videos
      
      console.log('循环视频数据:', loopVideos)
      
      if (Array.isArray(loopVideos) && loopVideos.length > 0) {
        taskForm.loopVideos = loopVideos.map((video, index) => ({
          id: video.id || `loop-${role.id}-${index}`,
          name: video.name || `${role.name}_循环视频_${index + 1}`,
          path: video.path,
          emotion: video.emotion || video.tag || 'calm'
        }))
        ElMessage.success(`已自动填充 ${loopVideos.length} 个循环视频`)
      }
    } catch (e) {
      console.error('解析循环视频失败:', e)
    }
  } else {
    console.log('角色没有循环视频')
  }
  
  // 3. 自动填充结束视频
  if (role.ending_video) {
    try {
      // 直接使用字符串路径，不需要解析JSON
      if (typeof role.ending_video === 'string') {
        taskForm.endingVideo = {
          id: `ending-${role.id}`,
          name: `${role.name}_结束视频`,
          path: role.ending_video,
          roleId: role.id
        }
        ElMessage.success('已自动填充结束视频')
      } else if (role.ending_video && role.ending_video.path) {
        // 如果是对象格式
        taskForm.endingVideo = {
          id: role.ending_video.id || `ending-${role.id}`,
          name: role.ending_video.name || `${role.name}_结束视频`,
          path: role.ending_video.path,
          roleId: role.id
        }
        ElMessage.success('已自动填充结束视频')
      }
    } catch (e) {
      console.error('解析结束视频失败:', e)
    }
  } else {
    console.log('角色没有结束视频')
  }
  
  // 4. 自动填充参考音频
  if (role.is_double_mode) {
    // 双人模式：填充左右两个音频
    if (role.left_audio_id && role.right_audio_id) {
      const leftAudio = audioList.value.find(a => a.id === role.left_audio_id)
      const rightAudio = audioList.value.find(a => a.id === role.right_audio_id)
      
      if (leftAudio) {
        taskForm.leftAudio = {
          id: leftAudio.id,
          name: leftAudio.name,
          path: leftAudio.path || leftAudio.audio_path
        }
        ElMessage.success(`已自动填充左边说话人音频: ${leftAudio.name}`)
      }
      
      if (rightAudio) {
        taskForm.rightAudio = {
          id: rightAudio.id,
          name: rightAudio.name,
          path: rightAudio.path || rightAudio.audio_path
        }
        ElMessage.success(`已自动填充右边说话人音频: ${rightAudio.name}`)
      }
      
      if (!leftAudio || !rightAudio) {
        ElMessage.warning('部分音频未找到，请手动选择')
      }
    } else {
      ElMessage.info('该双人角色未绑定音频，请手动选择或上传')
    }
  } else {
    // 单人模式：填充单个音频
    if (role.audio_id) {
      const associatedAudio = audioList.value.find(a => a.id === role.audio_id)
      if (associatedAudio) {
        taskForm.audio = {
          id: associatedAudio.id,
          name: associatedAudio.name,
          path: associatedAudio.path || associatedAudio.audio_path
        }
        ElMessage.success(`已自动填充角色关联的参考音频: ${associatedAudio.name}`)
      }
    } else {
      ElMessage.info('该角色没有关联参考音频，请手动选择或上传')
    }
  }
}

// 提交任务
const submitTask = async (runImmediately) => {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  
  const content = taskForm.scriptContent.trim()
  const isValidJson = isValidScriptJson(content)
  
  try {
    let taskName = taskForm.name
    if (!taskName) {
      taskName = `任务_${new Date().toISOString().slice(0, 10)}_${Date.now()}`
    }
    
    const taskData = {
      name: taskName,
      source_video_path: taskForm.openingVideo ? taskForm.openingVideo.path : '',
      script_text: isValidJson ? content : '',
      topic: !isValidJson ? content : '',
      prompt_audio_path: !taskForm.videoParams.dualMode ? (taskForm.audio ? taskForm.audio.path : '') : '',
      left_prompt_audio_path: taskForm.videoParams.dualMode ? (taskForm.leftAudio ? taskForm.leftAudio.path : '') : '',
      right_prompt_audio_path: taskForm.videoParams.dualMode ? (taskForm.rightAudio ? taskForm.rightAudio.path : '') : '',
      enable_double_mode: taskForm.videoParams.dualMode,
      bgm_path: taskForm.bgm ? taskForm.bgm.path : (taskForm.bgmParams.bgmId 
        ? (bgmList.value.find(b => b.id === taskForm.bgmParams.bgmId)?.path || '') 
        : ''),
      use_llm_generate: !isValidScriptJson(taskForm.scriptContent),
      enable_postprocess: taskForm.postProcessing.length > 0,
      enable_denoise: true,
      denoise_strength: 0.7,
      tts_speed: taskForm.videoParams.dualMode
        ? taskForm.leftAudioParams.ttsSpeed
        : taskForm.audioParams.ttsSpeed,
      tts_emo_weight: taskForm.videoParams.dualMode
        ? taskForm.leftAudioParams.ttsEmoWeight
        : taskForm.audioParams.ttsEmoWeight,
      left_tts_speed: taskForm.videoParams.dualMode ? taskForm.leftAudioParams.ttsSpeed : null,
      right_tts_speed: taskForm.videoParams.dualMode ? taskForm.rightAudioParams.ttsSpeed : null,
      left_tts_emo_weight: taskForm.videoParams.dualMode ? taskForm.leftAudioParams.ttsEmoWeight : null,
      right_tts_emo_weight: taskForm.videoParams.dualMode ? taskForm.rightAudioParams.ttsEmoWeight : null,
      enable_subtitle: taskForm.postProcessing.includes('subtitle'),
      subtitle_font: taskForm.subtitleParams.font,
      subtitle_size: taskForm.subtitleParams.fontSize,
      subtitle_color: taskForm.subtitleParams.color,
      subtitle_stroke_color: taskForm.subtitleParams.strokeColor,
      subtitle_stroke_width: taskForm.subtitleParams.strokeWidth,
      subtitle_position: taskForm.subtitleParams.position,
      subtitle_background_alpha: taskForm.subtitleParams.backgroundAlpha,
      enable_bgm: taskForm.postProcessing.includes('bgm'),
      bgm_volume: taskForm.bgmParams.intensity || 0.3,
      enable_cover: taskForm.postProcessing.includes('cover'),

      // 转场效果配置
      enable_transition: taskForm.postProcessing.includes('transition'),
      transition_type: taskForm.transitionParams.type,
      transition_effect: taskForm.transitionParams.effect,
      transition_random: taskForm.transitionParams.random,
      transition_random_all: taskForm.transitionParams.randomAll,
      transition_duration: taskForm.transitionParams.duration,

      // DEBUG: 打印转场配置
      _debug_postProcessing: taskForm.postProcessing,
      _debug_enable_transition: taskForm.postProcessing.includes('transition'),

      heygem_steps: taskForm.videoParams.inferenceSteps,
      role_id: taskForm.roleId,
      scene_tag_group_id: taskForm.sceneTagGroupId,
      
      // 带标签的视频素材（新接口格式）
      opening_video_with_tags: taskForm.openingVideo ? {
        file_path: taskForm.openingVideo.path,
        emotion_tags: [],
        scene_tags: ['开场']
      } : null,
      
      loop_videos_with_tags: taskForm.loopVideos.map(video => {
        let emotionTag = '冷静'
        if (video.emotion === 'happy') emotionTag = '开心'
        else if (video.emotion === 'angry') emotionTag = '生气'
        else if (video.emotion === 'sad') emotionTag = '难过'
        else if (video.emotion === 'fear') emotionTag = '害怕'
        else if (video.emotion === 'disgust') emotionTag = '厌恶'
        else if (video.emotion === 'depressed') emotionTag = '低落'
        else if (video.emotion === 'surprised') emotionTag = '惊喜'
        
        return {
          file_path: video.path,
          emotion_tags: [emotionTag],
          scene_tags: []
        }
      }),
      
      scene_videos_with_tags: taskForm.sceneVideos.map(video => {
        // video.scene 已是中文标签名（如"旁白视角"、"环境展示"），直接使用
        const sceneTag = video.scene || '环境展示'
        
        return {
          file_path: video.path,
          emotion_tags: [],
          scene_tags: [sceneTag]
        }
      }),
      
      ending_video_with_tags: taskForm.endingVideo ? {
        file_path: taskForm.endingVideo.path,
        emotion_tags: [],
        scene_tags: ['结束']
      } : null
    }
    
    const result = await taskStore.createTask(taskData)
    
    if (runImmediately) {
      try {
        await taskApi.control(result.task_id, 'start')
        ElMessage.success('任务创建并开始运行')
        // WebSocket 连接不阻塞页面跳转，异步执行
        websocketService.connect(result.task_id).catch(error => {
          console.error(`连接任务 ${result.task_id} WebSocket 失败:`, error)
        })
      } catch (startError) {
        ElMessage.warning('任务创建成功，但启动失败: ' + (startError.response?.data?.detail || startError.message || '未知错误'))
      }
    } else {
      ElMessage.success('任务已添加到待运行列表')
    }

    router.push('/')
  } catch (error) {
    ElMessage.error('任务创建失败: ' + (error.response?.data?.detail || error.message || '未知错误'))
  }
}

// 加载素材列表和设置
onMounted(async () => {
  try {
    await Promise.all([
      materialStore.loadMaterials(),
      settingsStore.fetchSettings(),
      tagStore.fetchTagGroups()
    ])
    roleList.value = materialStore.materials.roles || []
    sceneList.value = materialStore.materials.scenes || []
    audioList.value = materialStore.materials.audios || []
    bgmList.value = materialStore.materials.bgm || []
    
    // 从设置中应用默认参数到表单
    const settings = settingsStore.settings
    taskForm.videoParams.heygemOriginal = settings.heygem_original ?? true
    taskForm.videoParams.inferenceSteps = settings.heygem_inference_steps ?? 16
    taskForm.videoParams.dualMode = settings.dual_mode ?? false
    taskForm.audioParams.ttsSpeed = settings.tts_speed ?? 1.0
    taskForm.audioParams.ttsEmoWeight = settings.tts_emo_weight ?? 0.4
    taskForm.leftAudioParams.ttsSpeed = settings.tts_speed ?? 1.0
    taskForm.leftAudioParams.ttsEmoWeight = settings.tts_emo_weight ?? 0.4
    taskForm.rightAudioParams.ttsSpeed = settings.tts_speed ?? 1.0
    taskForm.rightAudioParams.ttsEmoWeight = settings.tts_emo_weight ?? 0.4
    
    // 设置默认标签组
    const defaultGroup = tagStore.defaultTagGroup
    if (defaultGroup) {
      taskForm.sceneTagGroupId = defaultGroup.id
      await handleTagGroupChange(defaultGroup.id)
    }
  } catch (error) {
    console.error('加载数据失败:', error)
  }
})

// 处理标签组切换
const handleTagGroupChange = async (groupId) => {
  if (!groupId) {
    sceneTagOptions.value = []
    return
  }
  
  try {
    const tags = await tagStore.fetchTagsByGroup(groupId)
    sceneTagOptions.value = tags || []
  } catch (error) {
    console.error('加载标签失败:', error)
    sceneTagOptions.value = []
  }
}
</script>

<style scoped lang="scss">
.task-create-page {
  padding: 20px;
  max-width: 1400px;
  margin: 0 auto;
}

.main-content {
  display: flex;
  gap: 20px;
  margin-top: 20px;
}

.left-section {
  flex: 4;
}

.right-section {
  flex: 1;
  min-width: 280px;
}

.form-section {
  margin-top: 20px;
}

.form-card {
  margin-bottom: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 500;
}

.video-upload-section,
.audio-upload-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.tag-group-selector {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.selector-label {
  font-size: 14px;
  color: #606266;
}

.tag-group-select {
  width: 200px;
}

.upload-buttons {
  display: flex;
  gap: 10px;
  margin-top: 5px;
}

.bgm-select-section {
  display: flex;
  gap: 10px;
  align-items: center;
}

.bgm-setting-container {
  width: 100%;
}

.bgm-row {
  display: flex;
  align-items: flex-start;
  margin-bottom: 20px;
  gap: 12px;
}

.bgm-row:last-child {
  margin-bottom: 0;
}

.row-label {
  min-width: 80px;
  padding-top: 8px;
  font-size: 14px;
  color: #606266;
  font-weight: 500;
}

.row-content {
  flex: 1;
  width: 100%;
}

.bgm-second-row {
  width: 100%;
  transition: all 0.3s ease;
}

.bgm-second-row .upload-section {
  display: flex;
  justify-content: flex-start;
  animation: fadeIn 0.3s ease;
}

.bgm-second-row .play-section {
  animation: fadeIn 0.3s ease;
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(-10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@media (max-width: 768px) {
  .bgm-row {
    flex-direction: column;
    gap: 8px;
  }
  
  .row-label {
    min-width: auto;
    padding-top: 0;
  }
  
  .bgm-second-row .audio-item {
    flex-direction: column;
    align-items: flex-start;
    gap: 10px;
  }
  
  .bgm-second-row .audio-actions {
    width: 100%;
    justify-content: flex-end;
  }
}

.video-item,
.audio-item {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  padding: 15px;
  background: #f5f7fa;
  border-radius: 8px;
  gap: 12px;
}

.video-info,
.audio-info {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  width: 100%;
}

.video-name {
  font-size: 14px;
  font-weight: 500;
  color: #303133;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.video-preview {
  margin-top: 10px;
  border-radius: 4px;
  overflow: hidden;
  width: 100%;
}

.preview-video {
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  display: block;
  max-width: 100%;
}

.video-actions .el-select {
  min-width: 100px;
}

.emotion-select,
.scene-select {
  width: 120px;
}

.audio-info span {
  max-width: 200px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.video-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 8px;
}

.emotion-select,
.scene-select {
  width: 120px;
}

.video-params,
.audio-params {
  margin-top: 20px;
  padding-top: 20px;
  border-top: 1px solid #e4e7ed;
}

.speaker-params {
  margin-top: 15px;
  padding: 15px;
  background: #f5f7fa;
  border-radius: 4px;
}

.speaker-params h4 {
  margin-top: 0;
  margin-bottom: 10px;
  font-size: 14px;
  font-weight: 500;
}

.slider-value {
  text-align: center;
  margin-top: 5px;
  font-size: 12px;
  color: #606266;
}

.script-tags {
  margin-top: 10px;
  padding: 10px;
  background: #f5f7fa;
  border-radius: 4px;
}

.tag-label {
  font-size: 12px;
  color: #606266;
  margin-right: 10px;
}

.tag-item {
  margin-right: 8px;
}

.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 15px;
  margin-top: 30px;
  padding-top: 20px;
  border-top: 1px solid #e4e7ed;
}

.material-sidebar {
  background: #f5f7fa;
  border-radius: 4px;
  padding: 20px;
  height: fit-content;
}

.material-sidebar h3 {
  margin-top: 0;
  margin-bottom: 20px;
  font-size: 16px;
  font-weight: 500;
}

.material-category {
  margin-bottom: 25px;
}

.material-category h4 {
  margin-top: 0;
  margin-bottom: 10px;
  font-size: 14px;
  font-weight: 500;
  color: #606266;
}

.material-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.material-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px;
  background: white;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.3s;
  
  &:hover {
    background: #ecf5ff;
  }
}

.material-thumbnail {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #e4e7ed;
  border-radius: 4px;
  color: #606266;
  overflow: hidden;
}

.material-thumbnail img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.material-name {
  font-size: 14px;
  flex: 1;
}

.face-analysis-result {
  .analysis-item {
    margin-bottom: 10px;
    display: flex;
    justify-content: space-between;
    
    .label {
      font-weight: 500;
    }
  }
}

.face-analysis-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  
  .el-icon.is-loading {
    margin-right: 10px;
  }
}

// ==================== 字幕设置面板样式 ====================
.subtitle-settings-wrapper {
  :deep(.el-form-item__content) {
    width: 100%;
  }
}

.subtitle-settings-panel {
  display: flex;
  gap: 24px;
  padding: 20px;
  background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}

// 左侧样式设置区域
.subtitle-style-section {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.setting-group {
  background: white;
  border-radius: 10px;
  padding: 16px;
  border: 1px solid #e2e8f0;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
  transition: box-shadow 0.2s ease;
  
  &:hover {
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  }
}

.group-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: #334155;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid #f1f5f9;
  
  .el-icon {
    color: #3b82f6;
    font-size: 16px;
  }
}

.group-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.setting-item {
  display: flex;
  align-items: center;
  gap: 12px;
  
  &.color-item {
    align-items: center;
  }
}

.item-label {
  min-width: 70px;
  font-size: 13px;
  color: #64748b;
  font-weight: 500;
  flex-shrink: 0;
}

.font-select {
  width: 140px;
}

.slider-with-value {
  flex: 1;
  min-width: 180px;
}

.compact-slider {
  :deep(.el-slider__runway.show-input) {
    margin-right: 10px;
  }
  
  :deep(.el-slider__input) {
    width: 60px;
  }
  
  :deep(.el-input-number) {
    width: 60px;
  }
}

// 右侧区域 - 上下布局
.subtitle-right-section {
  width: 280px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

// 横置位置选择卡片
.position-card-horizontal {
  background: white;
  border-radius: 10px;
  padding: 16px;
  border: 1px solid #e2e8f0;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
}

.position-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: #334155;
  margin-bottom: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid #f1f5f9;
  
  .el-icon {
    color: #3b82f6;
    font-size: 16px;
  }
}

.position-options-horizontal {
  display: flex;
  gap: 8px;
}

.position-option-horizontal {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 12px 8px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
  border: 2px solid transparent;
  background: #f8fafc;
  
  &:hover {
    background: #eff6ff;
    border-color: #bfdbfe;
    transform: translateY(-2px);
  }
  
  &.active {
    background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
    border-color: #1d4ed8;
    color: white;
    box-shadow: 0 4px 12px rgba(59, 130, 246, 0.3);
    
    .option-label {
      color: white;
    }
  }
  
  .option-label {
    font-size: 13px;
    font-weight: 500;
    color: #475569;
  }
}

// 预览卡片样式
.preview-card {
  background: white;
  border-radius: 10px;
  padding: 16px;
  border: 1px solid #e2e8f0;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
  flex: 1;
  display: flex;
  flex-direction: column;
}

.preview-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: #334155;
  margin-bottom: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid #f1f5f9;
  
  .el-icon {
    color: #3b82f6;
    font-size: 16px;
  }
}

.preview-container {
  background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
  border-radius: 8px;
  padding: 20px;
  flex: 1;
  min-height: 140px;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;
  
  &::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: 
      linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px),
      linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px);
    background-size: 20px 20px;
    pointer-events: none;
  }
  
  &.position-top {
    align-items: flex-start;
    padding-top: 30px;
  }
  
  &.position-center {
    align-items: center;
  }
  
  &.position-bottom {
    align-items: flex-end;
    padding-bottom: 30px;
  }
}

.preview-subtitle {
  padding: 8px 16px;
  border-radius: 4px;
  text-align: center;
  line-height: 1.4;
  transition: all 0.3s ease;
  position: relative;
  z-index: 1;
  white-space: nowrap;
}

// 数值输入框样式
.number-input {
  width: 120px;
}

// ==================== 转场效果设置面板样式 ====================
.transition-settings-wrapper {
  :deep(.el-form-item__content) {
    width: 100%;
  }
}

.transition-settings-panel {
  display: flex;
  flex-direction: column;
  gap: 20px;
  padding: 20px;
  background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}

.type-select {
  width: 140px;
}

.effect-select {
  width: 160px;
}

.duration-slider {
  flex: 1;
  min-width: 200px;
}

.slider-unit {
  font-size: 13px;
  color: #64748b;
  margin-left: 8px;
}

// 响应式设计
@media (max-width: 768px) {
  .transition-settings-panel {
    padding: 12px;
  }

  .type-select,
  .effect-select {
    width: 100%;
  }

  .duration-slider {
    min-width: 100%;
  }
}

// 暗色主题
.dark-theme .transition-settings-panel {
  background: linear-gradient(135deg, #1f1f1f 0%, #262626 100%);
  border-color: #424242;
}

// 响应式设计
@media (max-width: 992px) {
  .subtitle-settings-panel {
    flex-direction: column;
    gap: 16px;
  }
  
  .subtitle-right-section {
    width: 100%;
    flex-direction: row;
  }
  
  .position-card-horizontal {
    flex: 1;
  }
  
  .preview-card {
    flex: 1;
    margin-top: 0;
  }
  
  .preview-container {
    min-height: 100px;
  }
}

@media (max-width: 768px) {
  .subtitle-settings-panel {
    padding: 12px;
  }
  
  .subtitle-right-section {
    flex-direction: column;
  }
  
  .setting-group {
    padding: 12px;
  }
  
  .setting-item {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }
  
  .item-label {
    min-width: auto;
  }
  
  .font-select {
    width: 100%;
  }
  
  .number-input {
    width: 100%;
  }
  
  .position-options-horizontal {
    flex-wrap: wrap;
  }
  
  .position-option-horizontal {
    min-width: 80px;
  }
  
  .preview-container {
    min-height: 80px;
    padding: 16px;
  }
}

// 暗色主题样式
.dark-theme .task-create-page {
  background: #141414;
  color: #ffffff;
}

.dark-theme .form-card {
  background: #1f1f1f;
  border-color: #303030;
}

.dark-theme .form-card h2 {
  color: #ffffff;
}

.dark-theme .form-card h3 {
  color: #e0e0e0;
}

.dark-theme .form-section {
  border-color: #303030;
}

.dark-theme .subtitle-textarea-wrapper,
.dark-theme .topic-textarea-wrapper {
  background: #262626;
  border-color: #424242;
}

.dark-theme .subtitle-textarea-wrapper:focus-within,
.dark-theme .topic-textarea-wrapper:focus-within {
  border-color: #3b82f6;
}

.dark-theme .subtitle-textarea,
.dark-theme .topic-textarea {
  color: #ffffff;
}

.dark-theme .char-count {
  color: #9e9e9e;
}

.dark-theme .upload-area {
  background: #262626;
  border-color: #424242;
}

.dark-theme .upload-area:hover {
  border-color: #3b82f6;
  background: #2d2d2d;
}

.dark-theme .upload-hint {
  color: #9e9e9e;
}

.dark-theme .upload-hint-text {
  color: #bdbdbd;
}

.dark-theme .uploaded-file {
  background: #262626;
  border-color: #424242;
}

.dark-theme .file-info .name {
  color: #ffffff;
}

.dark-theme .file-info .path {
  color: #9e9e9e;
}

.dark-theme .video-params,
.dark-theme .audio-params {
  border-color: #303030;
}

.dark-theme .speaker-params {
  background: #262626;
}

.dark-theme .speaker-params h4 {
  color: #e0e0e0;
}

.dark-theme .slider-value {
  color: #bdbdbd;
}

.dark-theme .script-tags {
  background: #262626;
}

.dark-theme .tag-label {
  color: #bdbdbd;
}

.dark-theme .form-actions {
  border-color: #303030;
}

.dark-theme .material-sidebar {
  background: #1f1f1f;
  border-color: #303030;
}

.dark-theme .material-sidebar h3 {
  color: #ffffff;
}

.dark-theme .material-category h4 {
  color: #bdbdbd;
}

.dark-theme .material-item {
  background: #262626;
  border-color: #424242;
}

.dark-theme .material-item:hover {
  background: #2d2d2d;
  border-color: #3b82f6;
}

.dark-theme .material-thumbnail {
  background: #424242;
  color: #bdbdbd;
}

.dark-theme .material-name {
  color: #ffffff;
}

.dark-theme .subtitle-settings-panel {
  background: linear-gradient(135deg, #1f1f1f 0%, #262626 100%);
  border-color: #424242;
}

.dark-theme .setting-group {
  background: #262626;
  border-color: #424242;
}

.dark-theme .group-title {
  color: #e0e0e0;
  border-color: #303030;
}

.dark-theme .item-label {
  color: #bdbdbd;
}

.dark-theme .color-input-wrapper {
  background: #262626;
  border-color: #424242;
}

.dark-theme .color-display {
  border-color: #424242;
}

.dark-theme .position-card {
  background: #262626;
  border-color: #424242;
}

.dark-theme .position-card.selected {
  border-color: #3b82f6;
  background: #2d2d2d;
}

.dark-theme .position-card-title {
  color: #bdbdbd;
}

.dark-theme .position-card-inner {
  background: #1f1f1f;
  border-color: #424242;
}

.dark-theme .position-option {
  background: #262626;
  border-color: #424242;
}

.dark-theme .position-option.selected {
  background: #3b82f6;
  border-color: #3b82f6;
}

.dark-theme .position-option.selected .position-dot {
  background: #ffffff;
}

.dark-theme .position-dot {
  background: #bdbdbd;
}

.dark-theme .preview-card {
  background: #262626;
  border-color: #424242;
}

.dark-theme .preview-card-title {
  color: #bdbdbd;
}

.dark-theme .preview-container {
  background: linear-gradient(135deg, #1f1f1f 0%, #262626 100%);
  border-color: #424242;
}

.dark-theme .preview-subtitle {
  background: rgba(0, 0, 0, 0.75) !important;
  color: #ffffff !important;
}

.dark-theme :deep(.el-input__wrapper),
.dark-theme :deep(.el-textarea__inner),
.dark-theme :deep(.el-select__wrapper) {
  background: #262626;
  box-shadow: 0 0 0 1px #424242 inset;
}

.dark-theme :deep(.el-input__wrapper:hover),
.dark-theme :deep(.el-textarea__inner:hover),
.dark-theme :deep(.el-select__wrapper:hover) {
  box-shadow: 0 0 0 1px #616161 inset;
}

.dark-theme :deep(.el-input__wrapper.is-focus),
.dark-theme :deep(.el-textarea__inner:focus),
.dark-theme :deep(.el-select__wrapper.is-focus) {
  box-shadow: 0 0 0 1px #3b82f6 inset;
}

.dark-theme :deep(.el-input__inner),
.dark-theme :deep(.el-textarea__inner) {
  color: #ffffff;
}

.dark-theme :deep(.el-input__inner::placeholder),
.dark-theme :deep(.el-textarea__inner::placeholder) {
  color: #616161;
}

.dark-theme :deep(.el-select__placeholder) {
  color: #616161;
}

.dark-theme :deep(.el-select__selected-item) {
  color: #ffffff;
}

.dark-theme :deep(.el-radio-button__inner) {
  background: #262626;
  border-color: #424242;
  color: #bdbdbd;
}

.dark-theme :deep(.el-radio-button__inner:hover) {
  color: #ffffff;
}

.dark-theme :deep(.el-radio-button:first-child .el-radio-button__inner) {
  border-left-color: #424242;
}

.dark-theme :deep(.el-radio-button__orig-radio:checked + .el-radio-button__inner) {
  background: #3b82f6;
  border-color: #3b82f6;
  color: #ffffff;
}

.dark-theme :deep(.el-switch__core) {
  background: #424242;
}

.dark-theme :deep(.el-switch.is-checked .el-switch__core) {
  background: #3b82f6;
}

.dark-theme :deep(.el-slider__runway) {
  background: #424242;
}

.dark-theme :deep(.el-slider__bar) {
  background: #3b82f6;
}

.dark-theme :deep(.el-slider__button) {
  border-color: #3b82f6;
}

.dark-theme :deep(.el-color-picker__trigger) {
  border-color: #424242;
}

.dark-theme :deep(.el-color-picker__trigger:hover) {
  border-color: #616161;
}

</style>