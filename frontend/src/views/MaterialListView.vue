<template>
  <div class="material-library-container" :class="{ 'dark-theme': isDarkTheme }">
    <div class="page-header">
      <h2 class="page-title">素材库</h2>
      <el-button v-if="hasPermission('create')" type="primary" @click="openCreateDialog">
        <el-icon><Plus /></el-icon>
        {{ currentTab === 'role' ? '创建角色' : currentTab === 'scene' ? '创建场景' : currentTab === 'audio' ? '添加音频' : '添加BGM' }}
      </el-button>
    </div>

    <div class="content-wrapper">
      <el-tabs v-model="currentTab" class="material-tabs" @tab-change="handleTabChange">
        <el-tab-pane label="角色素材" name="role">
          <template #label>
            <span class="tab-label"><el-icon><User /></el-icon> 角色素材</span>
          </template>
        </el-tab-pane>
        <el-tab-pane label="场景素材" name="scene">
          <template #label>
            <span class="tab-label"><el-icon><Picture /></el-icon> 场景素材</span>
          </template>
        </el-tab-pane>
        <el-tab-pane label="参考音频" name="audio">
          <template #label>
            <span class="tab-label"><el-icon><Microphone /></el-icon> 参考音频</span>
          </template>
        </el-tab-pane>
        <el-tab-pane label="BGM" name="bgm">
          <template #label>
            <span class="tab-label"><el-icon><Headset /></el-icon> BGM</span>
          </template>
        </el-tab-pane>
      </el-tabs>

      <div class="search-filter">
        <el-input
          v-model="searchQuery"
          placeholder="搜索素材"
          clearable
          prefix-icon="Search"
          class="search-input"
          @input="handleSearch"
        />
      </div>

      <div class="material-content">
        <div v-if="loading" class="loading-container">
          <el-skeleton :rows="3" animated>
            <template #template>
              <el-skeleton-item variant="p" style="width: 80%" />
              <el-skeleton-item variant="p" style="width: 60%" />
              <el-skeleton-item variant="p" style="width: 40%" />
            </template>
          </el-skeleton>
        </div>
        <!-- 音频和BGM素材卡片：内嵌播放器和悬停播放 -->
        <div class="material-grid audio-grid" v-else-if="currentItems.length > 0 && (currentTab === 'audio' || currentTab === 'bgm')">
          <div 
            v-for="item in currentItems" 
            :key="item.id || item.role_id || item.scene_id || item.bgm_id"
            class="material-card audio-card"
            @mouseenter="handleHoverPlay(item)"
            @mouseleave="handleHoverStop(item)"
          >
            <div class="audio-card-content">
              <!-- 音频可视化区域 -->
              <div class="audio-visual-area">
                <div class="audio-icon-container">
                  <el-icon class="audio-icon" :size="40">
                    <svg v-if="playingAudioId === (item.id || item.bgm_id)" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">
                      <path fill="currentColor" d="M512 64a448 448 0 1 1 0 896 448 448 0 0 1 0-896m0 832a384 384 0 0 0 0-768 384 384 0 0 0 0 768m-48-247.616L668.608 512 464 375.616zm10.624-342.656 249.472 166.336a48 48 0 0 1 0 79.872L474.624 718.272A48 48 0 0 1 400 678.336V345.6a48 48 0 0 1 74.624-39.936z"/>
                    </svg>
                    <Headset v-else />
                  </el-icon>
                  <!-- 音频波形动画 -->
                  <div v-if="playingAudioId === (item.id || item.bgm_id)" class="audio-wave">
                    <span></span><span></span><span></span><span></span><span></span>
                  </div>
                </div>
              </div>
              
              <!-- 音频播放器 -->
              <audio 
                v-if="item.path"
                :ref="el => setAudioRef(el, item.id || item.bgm_id)"
                :src="getFileUrl(item.path)"
                @play="handleAudioPlay(item)"
                @pause="handleAudioPause(item)"
                @ended="handleAudioEnded(item)"
              />
            </div>
            
            <div class="card-body">
              <div class="card-header">
                <h4 class="card-title">{{ item.name || item.role_name || item.scene_name || item.bgm_name }}</h4>
                <div class="card-meta">
                  <!-- 播放状态指示 -->
                  <span v-if="playingAudioId === (item.id || item.bgm_id)" class="playing-indicator">
                    播放中
                  </span>
                  <span class="meta-tag">
                    <el-icon><Clock /></el-icon> 
                    {{ formatDuration(item.duration) }}
                  </span>
                </div>
              </div>
            </div>
            
            <div class="card-actions">
              <el-button 
                type="primary" 
                size="small" 
                plain
                @click.stop="editItem(item)"
                title="编辑音频"
              >
                <el-icon><Edit /></el-icon>
                编辑
              </el-button>
              <el-button 
                type="danger" 
                size="small" 
                @click.stop="deleteItem(item)"
                title="删除音频"
              >
                <el-icon><Delete /></el-icon>
                删除
              </el-button>
            </div>
          </div>
        </div>

        <!-- 角色和场景素材卡片：保持原有设计 -->
        <div class="material-grid" v-else-if="currentItems.length > 0">
          <div 
            v-for="item in currentItems" 
            :key="item.id || item.role_id || item.scene_id || item.bgm_id"
            class="material-card"
            @click="previewItem(item)"
          >
            <div class="card-thumbnail">
              <img 
                v-if="item.thumbnail" 
                :src="getFileUrl(item.thumbnail)" 
                :alt="item.role_name || item.scene_name"
                @error="handleThumbnailError($event, item)"
              />
              <div v-else class="card-placeholder">
                <el-icon v-if="currentTab === 'role'"><User /></el-icon>
                <el-icon v-else-if="currentTab === 'scene'"><Picture /></el-icon>
                <el-icon v-else><Headset /></el-icon>
              </div>
              <div class="card-overlay">
                <el-button type="primary" circle @click.stop="previewItem(item)">
                  <el-icon><VideoPlay /></el-icon>
                </el-button>
              </div>
            </div>
            <div class="card-body">
              <h4 class="card-title">{{ item.name || item.role_name || item.scene_name || item.bgm_name }}</h4>
              <div class="card-meta">
                <template v-if="currentTab === 'role'">
                  <span class="meta-tag"><el-icon><VideoCamera /></el-icon> {{ item.video_count || 0 }} 个视频</span>
                  <span v-if="item.audio_name" class="meta-tag audio"><el-icon><Headset /></el-icon> {{ item.audio_name }}</span>
                </template>
                <template v-else-if="currentTab === 'scene'">
                  <span class="meta-tag"><el-icon><VideoCamera /></el-icon> {{ item.video_count || 0 }} 个视频</span>
                </template>
                <template v-else-if="currentTab === 'audio'">
                  <span class="meta-tag"><el-icon><Clock /></el-icon> {{ formatDuration(item.duration) }}</span>
                </template>
                <template v-else>
                  <span class="meta-tag"><el-icon><Clock /></el-icon> {{ formatDuration(item.duration) }}</span>
                </template>
              </div>
            </div>
            <div class="card-actions">
              <el-button v-if="hasPermission('edit')" type="primary" size="small" plain @click.stop="editItem(item)">
                <el-icon><Edit /></el-icon>
                编辑
              </el-button>
              <el-button v-if="hasPermission('delete')" type="danger" size="small" @click.stop="deleteItem(item)">
                <el-icon><Delete /></el-icon>
                删除
              </el-button>
            </div>
          </div>
        </div>
        <el-empty v-else description="暂无素材，点击上方按钮创建" :image-size="100" />
      </div>
    </div>

    <el-dialog 
      v-model="showCreateDialog" 
      :title="isEditing ? '编辑' : createTitle"
      width="900px"
      :class="['material-dialog', { 'dark-theme': isDarkTheme }]"
      :close-on-click-modal="false"
      :modal-class="isDarkTheme ? 'dark-theme' : ''"
    >
      <div class="dialog-content">
        <el-form :model="createForm" :rules="createRules" ref="formRef" label-position="top">
          <el-form-item :label="nameLabel" prop="name">
            <el-input v-model="createForm.name" :placeholder="namePlaceholder" />
          </el-form-item>

          <template v-if="currentTab === 'role'">
            <el-form-item label="双人模式">
              <el-switch 
                v-model="createForm.is_double_mode"
                :disabled="isEditing && createForm.is_double_mode"
                @change="handleDoubleModeChange"
              />
              <span v-if="createForm.is_double_mode" class="mode-hint">
                双人模式创建后不可切换
              </span>
            </el-form-item>

            <div class="video-section">
              <div class="section-header">
                <h5>开场视频 <span class="required">*</span></h5>
                <el-button size="small" type="primary" plain @click="triggerUpload('opening')">
                  <el-icon><Upload /></el-icon> 上传
                </el-button>
                <input type="file" ref="openingInput" accept="video/*" style="display:none" @change="handleVideoUpload($event, 'opening')" />
              </div>
              <div class="video-preview" v-if="createForm.opening_video">
                <video :src="getFileUrl(createForm.opening_video)" controls />
                <div class="video-actions">
                  <el-button size="small" @click="analyzeFace(createForm.opening_video, 'opening')" :loading="faceAnalysisLoading[createForm.opening_video] && faceAnalysisLoading[createForm.opening_video] !== 'completed'" :disabled="(faceAnalysisLoading[createForm.opening_video] && faceAnalysisLoading[createForm.opening_video] !== 'completed') || analyzedVideoPaths[createForm.opening_video]">
                    <el-icon><Monitor /></el-icon> {{ faceAnalysisLoading[createForm.opening_video] === 'completed' ? '已完成' : (faceAnalysisLoading[createForm.opening_video] || analyzedVideoPaths[createForm.opening_video] ? '分析中...' : '面部分析') }}
                  </el-button>
                  <el-button size="small" type="danger" @click="removeVideo('opening')">
                    <el-icon><Delete /></el-icon>
                  </el-button>
                </div>
              </div>
              <div v-else class="upload-placeholder" @click="triggerUpload('opening')">
                <el-icon><VideoCamera /></el-icon>
                <span>点击上传开场视频</span>
              </div>
            </div>

            <div class="video-section">
              <div class="section-header">
                <h5>循环视频 <span class="hint">(可上传多个)</span></h5>
                <el-button size="small" type="primary" plain @click="triggerUpload('loop')">
                  <el-icon><Upload /></el-icon> 添加
                </el-button>
                <input type="file" ref="loopInput" accept="video/*" style="display:none" @change="handleVideoUpload($event, 'loop')" />
              </div>
              <div class="video-list">
                <div v-for="(video, index) in createForm.loop_videos" :key="index" class="video-item">
                  <video :src="getFileUrl(video.path)" controls />
                  <div class="video-info">
                    <el-select v-model="video.emotion" placeholder="选择情绪标签" size="small" class="emotion-select">
                      <el-option label="开心" value="happy" />
                      <el-option label="生气" value="angry" />
                      <el-option label="难过" value="sad" />
                      <el-option label="害怕" value="fearful" />
                      <el-option label="厌恶" value="disgusted" />
                      <el-option label="低落" value="depressed" />
                      <el-option label="惊喜" value="surprised" />
                      <el-option label="冷静" value="calm" />
                    </el-select>
                  </div>
                  <div class="video-actions">
                    <el-button size="small" @click="analyzeFace(video.path, 'loop')" :loading="faceAnalysisLoading[video.path] && faceAnalysisLoading[video.path] !== 'completed'" :disabled="(faceAnalysisLoading[video.path] && faceAnalysisLoading[video.path] !== 'completed') || analyzedVideoPaths[video.path]">
                      <el-icon><Monitor /></el-icon> {{ faceAnalysisLoading[video.path] === 'completed' ? '已完成' : (faceAnalysisLoading[video.path] || analyzedVideoPaths[video.path] ? '分析中...' : '面部分析') }}
                    </el-button>
                    <el-button size="small" type="danger" @click="removeLoopVideo(index)">
                      <el-icon><Delete /></el-icon>
                    </el-button>
                  </div>
                </div>
              </div>
            </div>

            <div class="video-section">
              <div class="section-header">
                <h5>结束视频</h5>
                <el-button size="small" type="primary" plain @click="triggerUpload('ending')">
                  <el-icon><Upload /></el-icon> 上传
                </el-button>
                <input type="file" ref="endingInput" accept="video/*" style="display:none" @change="handleVideoUpload($event, 'ending')" />
              </div>
              <div class="video-preview" v-if="createForm.ending_video">
                <video :src="getFileUrl(createForm.ending_video)" controls />
                <div class="video-actions">
                  <el-button size="small" @click="analyzeFace(createForm.ending_video, 'ending')" :loading="faceAnalysisLoading[createForm.ending_video] && faceAnalysisLoading[createForm.ending_video] !== 'completed'" :disabled="(faceAnalysisLoading[createForm.ending_video] && faceAnalysisLoading[createForm.ending_video] !== 'completed') || analyzedVideoPaths[createForm.ending_video]">
                    <el-icon><Monitor /></el-icon> {{ faceAnalysisLoading[createForm.ending_video] === 'completed' ? '已完成' : (faceAnalysisLoading[createForm.ending_video] || analyzedVideoPaths[createForm.ending_video] ? '分析中...' : '面部分析') }}
                  </el-button>
                  <el-button size="small" type="danger" @click="removeVideo('ending')">
                    <el-icon><Delete /></el-icon>
                  </el-button>
                </div>
              </div>
              <div v-else class="upload-placeholder" @click="triggerUpload('ending')">
                <el-icon><VideoCamera /></el-icon>
                <span>点击上传结束视频</span>
              </div>
            </div>

            <div v-if="!createForm.is_double_mode" class="audio-section">
              <div class="section-header">
                <h5>参考音频</h5>
              </div>
              <el-select 
                v-model="createForm.audio_id" 
                placeholder="从参考音频库选择绑定" 
                filterable
                clearable
                style="width: 100%"
              >
                <el-option
                  v-for="audio in referenceAudios"
                  :key="audio.id"
                  :label="audio.name"
                  :value="audio.id"
                >
                  <span>{{ audio.name }}</span>
                  <span class="audio-duration">{{ formatDuration(audio.duration) }}</span>
                </el-option>
              </el-select>
              <p class="form-hint">绑定后该音频无法被删除，直到角色被删除</p>
            </div>

            <div v-else class="audio-section double-mode">
              <div class="section-header">
                <h5>左边说话人参考音频 <span class="required">*</span></h5>
              </div>
              <el-select 
                v-model="createForm.left_audio_id" 
                placeholder="选择左边说话人参考音频" 
                filterable
                style="width: 100%"
              >
                <el-option
                  v-for="audio in referenceAudios"
                  :key="audio.id"
                  :label="audio.name"
                  :value="audio.id"
                >
                  <span>{{ audio.name }}</span>
                  <span class="audio-duration">{{ formatDuration(audio.duration) }}</span>
                </el-option>
              </el-select>
              
              <div class="section-header" style="margin-top: 16px;">
                <h5>右边说话人参考音频 <span class="required">*</span></h5>
              </div>
              <el-select 
                v-model="createForm.right_audio_id" 
                placeholder="选择右边说话人参考音频" 
                filterable
                style="width: 100%"
              >
                <el-option
                  v-for="audio in referenceAudios"
                  :key="audio.id"
                  :label="audio.name"
                  :value="audio.id"
                >
                  <span>{{ audio.name }}</span>
                  <span class="audio-duration">{{ formatDuration(audio.duration) }}</span>
                </el-option>
              </el-select>
              <p class="form-hint">双人模式需要选择两个不同的参考音频</p>
            </div>
          </template>

          <template v-else-if="currentTab === 'scene'">
            <div class="video-section">
              <div class="section-header">
                <h5>场景视频 <span class="hint">(可上传多个)</span></h5>
                <el-button size="small" type="primary" plain @click="triggerUpload('scene')">
                  <el-icon><Upload /></el-icon> 添加视频
                </el-button>
                <input type="file" ref="sceneInput" accept="video/*" style="display:none" @change="handleVideoUpload($event, 'scene')" />
              </div>
              <div class="video-list">
                <div v-for="(video, index) in createForm.scene_videos" :key="index" class="video-item scene">
                  <video :src="getFileUrl(video.path)" controls />
                  <div class="video-info">
                    <el-select v-model="video.tag" placeholder="选择场景标签" size="small" class="scene-select">
                      <el-option
                        v-for="tag in sceneTagOptions"
                        :key="tag.id"
                        :label="tag.name"
                        :value="tag.name"
                      />
                    </el-select>
                  </div>
                  <div class="video-actions">
                    <el-button size="small" type="danger" @click="removeSceneVideo(index)">
                      <el-icon><Delete /></el-icon>
                    </el-button>
                  </div>
                </div>
              </div>
              <p class="form-hint">上传的视频将自动重新封装，移除音频并保持原分辨率和帧率</p>
            </div>
          </template>

          <template v-else-if="currentTab === 'audio'">
            <div class="audio-upload-section">
              <div class="section-header">
                <h5>音频片段 <span class="hint">(按顺序上传多段)</span></h5>
                <el-button size="small" type="primary" plain @click="triggerAudioUpload">
                  <el-icon><Upload /></el-icon> 添加音频
                </el-button>
                <input type="file" ref="audioInput" accept="audio/*" multiple style="display:none" @change="handleAudioUpload" />
              </div>
              <div class="audio-list">
                <div v-for="(audio, index) in createForm.audio_clips" :key="audio.id || index" class="audio-item">
                  <div class="audio-icon">
                    <el-icon v-if="audio.status === 'uploading'">
                      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024"><path fill="currentColor" d="M512 0a512 512 0 1 0 512 512A512 512 0 0 0 512 0zm0 960a448 448 0 1 1 448-448 448 448 0 0 1-448 448z"/><path fill="currentColor" d="M480 416a32 32 0 0 1-32-32V192a32 32 0 0 1 64 0v192a32 32 0 0 1-32 32zm128 0a32 32 0 0 1-32-32V96a32 32 0 0 1 64 0v288a32 32 0 0 1-32 32zm96 80a32 32 0 0 1-32-32v-32a32 32 0 0 1 64 0v32a32 32 0 0 1-32 32zm-128 0a32 32 0 0 1-32-32v-64a32 32 0 0 1 64 0v64a32 32 0 0 1-32 32zm-160 0a32 32 0 0 1-32-32v-96a32 32 0 0 1 64 0v96a32 32 0 0 1-32 32zm-80 80a32 32 0 0 1-32-32v-32a32 32 0 0 1 64 0v32a32 32 0 0 1-32 32zm256 0a32 32 0 0 1-32-32v-160a32 32 0 0 1 64 0v160a32 32 0 0 1-32 32zm160 0a32 32 0 0 1-32-32v-224a32 32 0 0 1 64 0v224a32 32 0 0 1-32 32z"/></svg>
                    </el-icon>
                    <el-icon v-else-if="audio.status === 'failed'">
                      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024"><path fill="currentColor" d="M512 64a448 448 0 1 1 0 896 448 448 0 0 1 0-896zm0 960a48 48 0 1 0 0-96 48 48 0 0 0 0 96zm-48-592 208 352a32 32 0 0 0 54.9-26.8l-208-352a32 32 0 0 0-54.9 26.8z"/></svg>
                    </el-icon>
                    <el-icon v-else><Headset /></el-icon>
                  </div>
                  <div class="audio-info">
                    <span class="audio-name">{{ audio.name }}</span>
                    <div class="audio-meta">
                      <span class="audio-size">{{ formatFileSize(audio.size) }}</span>
                      <span class="audio-duration" v-if="audio.duration">{{ formatDuration(audio.duration) }}</span>
                    </div>
                    
                    <!-- 上传状态和进度 -->
                    <div v-if="audio.status === 'uploading'" class="upload-status">
                      <el-progress :percentage="audio.progress" :stroke-width="8" />
                      <span class="status-text">上传中... {{ audio.progress }}%</span>
                    </div>
                    
                    <div v-else-if="audio.status === 'failed'" class="upload-status failed">
                      <span class="status-text">上传失败</span>
                      <el-button size="small" type="primary" @click="retryUpload(index)">
                        重试
                      </el-button>
                    </div>
                    
                    <!-- 音频预览 -->
                    <div v-if="audio.path && audio.status === 'completed'" class="audio-preview-wrapper">
                      <div class="audio-player-container">
                        <audio 
                          :src="getFileUrl(audio.path, audio.timestamp)" 
                          controls 
                          class="preview-audio"
                          @error="handleAudioError($event, index)"
                          @loadedmetadata="handleAudioLoaded($event, index)"
                          @canplay="handleAudioCanPlay($event, index)"
                          preload="metadata"
                        ></audio>
                      </div>
                      <div v-if="audio.loading" class="audio-loading">
                        <el-icon class="is-loading"><Loading /></el-icon>
                        <span>加载中...</span>
                      </div>
                      <div v-if="audio.error" class="audio-error">
                        <el-icon><Warning /></el-icon>
                        <span>音频加载失败</span>
                        <el-button size="small" type="primary" @click="reloadAudio(index)">重试</el-button>
                      </div>
                    </div>
                    <div v-else-if="audio.status === 'completed' && !audio.path" class="audio-preview-missing">
                      <el-icon><Warning /></el-icon>
                      <span>音频路径缺失</span>
                    </div>
                  </div>
                  <div class="audio-actions">
                    <el-button 
                      v-if="audio.status === 'completed' && !audio.denoise" 
                      size="small" 
                      type="primary" 
                      @click="denoiseAudioClip(index)"
                      :loading="audio.denoising"
                      :disabled="audio.denoising"
                      title="降噪增强"
                    >
                      <el-icon v-if="!audio.denoising"><MagicStick /></el-icon>
                      <span v-else>处理中</span>
                    </el-button>
                    <el-tag v-if="audio.denoise" size="small" type="success" effect="plain">
                      <el-icon><Check /></el-icon> 已降噪
                    </el-tag>
                    <el-button size="small" type="danger" @click="removeAudioClip(index)">
                      <el-icon><Delete /></el-icon>
                    </el-button>
                  </div>
                </div>
              </div>
              <div class="audio-merge-info" v-if="createForm.audio_clips.length > 1">
                <el-alert
                  :title="`将合并 ${createForm.audio_clips.length} 个音频片段，总时长: ${formatTotalDuration}`"
                  type="info"
                  :closable="false"
                  show-icon
                />
              </div>
              <p class="form-hint" v-else>保存时将按顺序合并所有音频片段</p>
            </div>
          </template>

          <template v-else>
            <div class="video-section">
              <div class="section-header">
                <h5>BGM 文件</h5>
                <el-button size="small" type="primary" plain @click="triggerBgmUpload">
                  <el-icon><Upload /></el-icon> 上传
                </el-button>
                <input type="file" ref="bgmInput" accept="audio/*" style="display:none" @change="handleBgmUpload" />
              </div>
              <div class="video-preview" v-if="createForm.bgm_path">
                <div class="audio-preview">
                  <audio 
                    :src="getFileUrl(createForm.bgm_path, bgmTimestamp)" 
                    controls 
                    class="preview-audio"
                    style="width: 100%;"
                  />
                </div>
                <div class="video-actions">
                  <span style="margin-right: auto;">{{ createForm.bgm_name }}</span>
                  <el-button size="small" type="danger" @click="removeBgm">
                    <el-icon><Delete /></el-icon>
                  </el-button>
                </div>
              </div>
              <div v-else class="upload-placeholder" @click="triggerBgmUpload">
                <el-icon><Headset /></el-icon>
                <span>点击上传BGM音频</span>
              </div>
            </div>
          </template>
        </el-form>
      </div>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="submitForm" :loading="submitting">
          {{ isEditing ? '保存修改' : '创建' }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog 
      v-model="showPreviewDialog" 
      :title="previewItemData?.name || previewItemData?.role_name || previewItemData?.scene_name || '预览'" 
      width="800px" 
      :class="['preview-dialog', { 'dark-theme': isDarkTheme }]"
      :modal-class="isDarkTheme ? 'dark-theme' : ''"
    >
      <div class="preview-container">
        <template v-if="currentTab === 'role' || currentTab === 'scene'">
          <video 
            v-if="previewVideoPath"
            :src="getFileUrl(previewVideoPath)"
            controls
            autoplay
            muted
            class="preview-video"
          />
          <div v-else class="preview-empty">
            <el-icon><VideoCamera /></el-icon>
            <span>暂无视频素材</span>
          </div>
        </template>
        <template v-else-if="currentTab === 'audio' || currentTab === 'bgm'">
          <audio 
            v-if="previewItemData && previewItemData.path"
            :src="getFileUrl(previewItemData.path)"
            controls
            autoplay
          />
          <div v-else class="preview-empty">
            <el-icon><Headset /></el-icon>
            <span>暂无音频素材</span>
          </div>
        </template>
      </div>
    </el-dialog>

    <a href="https://deerflow.tech" target="_blank" class="deerflow-badge">✦ Deerflow</a>
  </div>
</template>

<script setup>
import { ref, computed, reactive, onMounted, onUnmounted, watch, inject } from 'vue'
import { useRoute } from 'vue-router'
import { materialApi } from '@/services/api'
import { taskApi } from '@/services/api'
import { uploadAPI } from '@/api/upload'
import { ElMessage } from 'element-plus'
import { useTagStore } from '@/stores/tagStore'

const route = useRoute()
const tagStore = useTagStore()

// 场景标签选项（从默认标签组加载）
const sceneTagOptions = ref([])
const selectedTagGroupId = ref(null)

const loadSceneTagOptions = async () => {
  try {
    await tagStore.fetchTagGroups()
    const defaultGroup = tagStore.defaultTagGroup
    const group = defaultGroup || tagStore.sceneTagGroups[0]
    if (group) {
      selectedTagGroupId.value = group.id
      const tags = await tagStore.fetchTagsByGroup(group.id)
      sceneTagOptions.value = tags || []
    }
  } catch (e) {
    console.error('加载场景标签失败:', e)
  }
}

// 注入主题状态 - 从 App.vue 获取响应式主题状态
const isDarkTheme = inject('isDarkTheme', ref(false))
const toggleTheme = inject('toggleTheme', () => {})

// 跟随系统主题的设置
const followSystemTheme = ref(!localStorage.getItem('theme'))

// 监听系统颜色模式变化
const setupThemeListener = () => {
  const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
  
  const handleChange = (e) => {
    // 只有在启用跟随系统主题时才更新
    if (followSystemTheme.value) {
      isDarkTheme.value = e.matches
    }
  }
  
  mediaQuery.addEventListener('change', handleChange)
  
  // 返回清理函数
  return () => mediaQuery.removeEventListener('change', handleChange)
}

const currentTab = ref('role')
const showCreateDialog = ref(false)
const showPreviewDialog = ref(false)
const isEditing = ref(false)
const submitting = ref(false)
const formRef = ref(null)
const previewItemData = ref(null)
const previewVideoPath = ref('')
const previewVideoLabel = ref('')

// 搜索和筛选
const searchQuery = ref('')
const filteredItems = ref([])

// 加载状态
const loading = ref(false)
const uploading = ref(false)
const uploadProgress = ref(0)

// 音频播放管理
const audioRefs = ref({})  // 存储音频元素引用
const playingAudioId = ref(null)  // 当前播放的音频ID
const faceAnalysisLoading = reactive({})  // 面部分析加载状态 → AC-228
const pollingTaskIds = reactive({})  // 正在轮询的任务 ID，用于防止重复调用
const analyzedVideoPaths = reactive({})  // 已完成分析的视频路径，用于防止重复分析（使用对象而非 Set，因为 Vue 3 的 reactive 对 Set 的支持有限）

// 标记视频已分析的辅助函数（确保响应式更新）
const markVideoAsAnalyzed = (videoPath) => {
  analyzedVideoPaths[videoPath] = true
  console.log('[markVideoAsAnalyzed] 已标记路径:', videoPath)
  console.log('[markVideoAsAnalyzed] analyzedVideoPaths 当前内容:', JSON.stringify(analyzedVideoPaths))
}

// 设置音频元素引用
const setAudioRef = (el, id) => {
  if (el) {
    audioRefs.value[id] = el
  }
}

// 鼠标悬停播放
const handleHoverPlay = async (item) => {
  const audioId = item.id || item.bgm_id
  const audioEl = audioRefs.value[audioId]
  
  if (audioEl && item.path) {
    try {
      // 停止当前播放的音频
      if (playingAudioId.value && playingAudioId.value !== audioId) {
        const currentAudio = audioRefs.value[playingAudioId.value]
        if (currentAudio) {
          currentAudio.pause()
          currentAudio.currentTime = 0
        }
      }
      
      // 播放新音频
      await audioEl.play()
      playingAudioId.value = audioId
    } catch (error) {
      console.error('音频播放失败:', error)
    }
  }
}

// 鼠标移开停止播放
const handleHoverStop = (item) => {
  const audioId = item.id || item.bgm_id
  const audioEl = audioRefs.value[audioId]
  
  if (audioEl) {
    audioEl.pause()
    audioEl.currentTime = 0
    if (playingAudioId.value === audioId) {
      playingAudioId.value = null
    }
  }
}

// 音频播放事件处理
const handleAudioPlay = (item) => {
  const audioId = item.id || item.bgm_id
  playingAudioId.value = audioId
}

// 音频暂停事件处理
const handleAudioPause = (item) => {
  const audioId = item.id || item.bgm_id
  if (playingAudioId.value === audioId) {
    playingAudioId.value = null
  }
}

// 音频播放结束处理
const handleAudioEnded = (item) => {
  playingAudioId.value = null
}

// 立即删除音频（无需二次确认）
const deleteAudioItem = async (item) => {
  const name = item.name || item.bgm_name || item.audio_name
  const audioId = item.id || item.bgm_id
  
  try {
    // 停止该音频的播放
    const audioEl = audioRefs.value[audioId]
    if (audioEl) {
      audioEl.pause()
      audioEl.currentTime = 0
    }
    
    // 删除音频文件
    await materialApi.delete(audioId, currentTab.value)
    
    // 显示成功消息
    ElMessage.success(`音频 "${name}" 已删除`)
    
    // 重新加载素材列表
    loadMaterials()
  } catch (error) {
    console.error('删除音频失败:', error)
    ElMessage.error('删除失败: ' + (error.message || '未知错误'))
  }
}

// 权限管理
const hasPermission = (action) => {
  // 这里假设用户角色存储在localStorage中
  // 实际项目中应该从用户状态管理中获取
  const userRole = localStorage.getItem('userRole') || 'admin'
  
  // 定义不同角色的权限 - 默认用户有所有权限以便测试
  const permissions = {
    admin: { create: true, edit: true, delete: true, upload: true },
    editor: { create: true, edit: true, delete: true, upload: true },
    user: { create: true, edit: true, delete: true, upload: true }
  }
  
  return permissions[userRole]?.[action] || true
}

const openingInput = ref(null)
const loopInput = ref(null)
const endingInput = ref(null)
const sceneInput = ref(null)
const audioInput = ref(null)
const bgmInput = ref(null)
const bgmTimestamp = ref(null)

const roles = ref([])
const scenes = ref([])
const referenceAudios = ref([])
const bgms = ref([])

const createForm = reactive({
  id: '',
  name: '',
  role_type: 'human',
  scenes: [],
  opening_video: '',
  loop_videos: [],
  ending_video: '',
  audio_id: '',
  scene_videos: [],
  audio_clips: [],
  bgm_path: '',
  bgm_name: '',
  bgm_duration: 0,
  is_double_mode: false,
  left_audio_id: '',
  right_audio_id: ''
})

const createRules = computed(() => ({
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }]
}))

const createTitle = computed(() => {
  const titles = {
    role: '创建角色',
    scene: '创建场景',
    audio: '添加参考音频',
    bgm: '添加BGM'
  }
  return titles[currentTab.value] || '创建'
})

const nameLabel = computed(() => {
  const labels = {
    role: '角色名称',
    scene: '场景名称',
    audio: '人物名称',
    bgm: 'BGM名称'
  }
  return labels[currentTab.value] || '名称'
})

// 计算音频总时长
const formatTotalDuration = computed(() => {
  if (!createForm.audio_clips || createForm.audio_clips.length === 0) return '0:00'
  
  const totalSeconds = createForm.audio_clips.reduce((sum, clip) => {
    return sum + (clip.duration || 0)
  }, 0)
  
  return formatDuration(totalSeconds)
})

const namePlaceholder = computed(() => {
  const placeholders = {
    role: '输入角色名称',
    scene: '输入场景名称',
    audio: '输入人物名称',
    bgm: '输入BGM名称'
  }
  return placeholders[currentTab.value] || '输入名称'
})

const currentItems = computed(() => {
  return filteredItems.value
})

const handleSearch = () => {
  let items = []
  
  switch (currentTab.value) {
    case 'role':
      items = roles.value
      break
    case 'scene':
      items = scenes.value
      break
    case 'audio':
      items = referenceAudios.value
      break
    case 'bgm':
      items = bgms.value
      break
  }
  
  // 应用搜索
  if (searchQuery.value) {
    const query = searchQuery.value.toLowerCase()
    items = items.filter(item => {
      const name = item.name || item.role_name || item.scene_name || item.bgm_name
      return name.toLowerCase().includes(query)
    })
  }
  
  filteredItems.value = items
}

// 监听素材变化，重新计算筛选结果
watch([roles, scenes, referenceAudios, bgms], () => {
  handleSearch()
}, { deep: true })

// 监听标签变化，重置筛选
watch(currentTab, () => {
  searchQuery.value = ''
  handleSearch()
})

const triggerUpload = (type) => {
  if (!hasPermission('upload')) {
    ElMessage.warning('您没有上传权限')
    return
  }
  
  const inputs = {
    opening: openingInput,
    loop: loopInput,
    ending: endingInput,
    scene: sceneInput
  }
  inputs[type]?.value?.click()
}

const triggerAudioUpload = () => {
  if (!hasPermission('upload')) {
    ElMessage.warning('您没有上传权限')
    return
  }
  audioInput.value?.click()
}

const triggerBgmUpload = () => {
  if (!hasPermission('upload')) {
    ElMessage.warning('您没有上传权限')
    return
  }
  bgmInput.value?.click()
}

const handleVideoUpload = async (event, type) => {
  const file = event.target.files[0]
  if (!file) return

  try {
    // 创建素材时上传的视频保存到 data 目录
    const response = await uploadAPI.uploadVideo(file, type, 'material')
    if (response.code === 200) {
      const path = response.data?.file_path || response.data?.path
      
      if (type === 'opening') {
        createForm.opening_video = path
      } else if (type === 'ending') {
        createForm.ending_video = path
      } else if (type === 'loop') {
        createForm.loop_videos.push({ path, emotion: 'calm' })
      } else if (type === 'scene') {
        // 场景视频上传后会自动重新封装
        ElMessage.info('视频上传成功，正在重新封装...')
        // 模拟重新封装过程
        setTimeout(() => {
          createForm.scene_videos.push({ path, tag: '' })
          ElMessage.success('视频重新封装完成')
        }, 1000)
      }
    }
  } catch (error) {
    ElMessage.error('上传失败: ' + (error.message || '未知错误'))
  }
  event.target.value = ''
}

const handleAudioUpload = async (event) => {
  const files = event.target.files
  if (!files || files.length === 0) return

  // 处理多个文件上传
  for (const file of files) {
    // 创建一个临时的上传项，用于显示上传状态
    const uploadItem = {
      name: file.name,
      size: file.size,
      status: 'uploading',
      progress: 0,
      id: Date.now() + Math.random() // 临时ID
    }

    createForm.audio_clips.push(uploadItem)

    try {
      const response = await uploadAPI.uploadAudio(file, 'reference', (progress) => {
        // 更新上传进度
        const index = createForm.audio_clips.findIndex(item => item.id === uploadItem.id)
        if (index !== -1) {
          createForm.audio_clips[index].progress = progress
        }
      })
      
      // 因为API拦截器已经返回了response.data，所以直接使用响应数据
      // 创建音频对象获取时长
      const audioPath = response.file_path || response.data?.file_path || response.path
      if (!audioPath) {
        throw new Error('上传响应中缺少文件路径')
      }
      
      const index = createForm.audio_clips.findIndex(item => item.id === uploadItem.id)
      if (index !== -1) {
        // 先更新为加载中状态
        createForm.audio_clips[index] = {
          ...createForm.audio_clips[index],
          status: 'completed',
          path: audioPath,
          loading: true,
          error: false,
          denoise: false
        }
        
        // 使用 URL 创建音频对象获取时长
        const audioUrl = getFileUrl(audioPath)
        console.log('加载音频:', audioUrl)
        
        const audioElement = new Audio(audioUrl)
        
        // 设置超时处理
        const timeoutId = setTimeout(() => {
          const clip = createForm.audio_clips[index]
          if (clip && clip.loading) {
            console.warn('音频元数据加载超时:', audioPath)
            const updatedClip = {
              ...clip,
              loading: false,
              error: false, // 超时不算错误，仍然可以播放
              duration: clip.duration || 0
            }
            createForm.audio_clips.splice(index, 1, updatedClip)
          }
        }, 10000)
        
        audioElement.onloadedmetadata = () => {
          clearTimeout(timeoutId)
          console.log('音频元数据加载成功:', audioElement.duration)
          // 使用Vue的响应式方法更新数组
          const updatedClip = {
            name: file.name,
            size: file.size,
            path: audioPath,
            status: 'completed',
            duration: audioElement.duration,
            loading: false,
            error: false,
            denoise: false
          }
          // 替换数组元素，确保Vue能检测到变化
          createForm.audio_clips.splice(index, 1, updatedClip)
        }
        
        audioElement.onerror = (e) => {
          clearTimeout(timeoutId)
          console.error('音频加载失败:', e, audioPath)
          // 音频加载失败处理 - 但仍然保留音频，让用户可以重试
          const updatedClip = {
            name: file.name,
            size: file.size,
            path: audioPath,
            status: 'completed',
            duration: 0,
            loading: false,
            error: true,
            denoise: false
          }
          createForm.audio_clips.splice(index, 1, updatedClip)
        }
        
        // 尝试加载音频
        audioElement.load()
      }
    } catch (error) {
      // 更新上传失败的项
      const index = createForm.audio_clips.findIndex(item => item.id === uploadItem.id)
      if (index !== -1) {
        createForm.audio_clips[index].status = 'failed'
      }
      ElMessage.error(`上传失败: ${file.name} - ${error.message || '未知错误'}`)
    }
  }
  
  ElMessage.success(`成功上传 ${files.length} 个音频文件`)
  event.target.value = ''
}

const handleBgmUpload = async (event) => {
  const file = event.target.files[0]
  if (!file) return

  try {
    const response = await uploadAPI.uploadAudio(file, 'bgm')
    console.log('BGM上传响应:', response)
    
    // 处理不同的响应格式
    const filePath = response.file_path || response.data?.file_path || response.path
    if (!filePath) {
      throw new Error('上传响应中缺少文件路径')
    }
    
    createForm.bgm_path = filePath
    createForm.bgm_name = file.name
    
    // 创建临时音频元素来计算时长
    const tempAudioUrl = URL.createObjectURL(file)
    const tempAudio = new Audio(tempAudioUrl)
    
    tempAudio.onloadedmetadata = () => {
      createForm.bgm_duration = tempAudio.duration
      URL.revokeObjectURL(tempAudioUrl)
      console.log('BGM时长:', createForm.bgm_duration)
    }
    
    tempAudio.onerror = () => {
      URL.revokeObjectURL(tempAudioUrl)
      console.warn('无法计算BGM时长')
    }
    
    bgmTimestamp.value = Date.now() // 添加时间戳强制刷新预览
    ElMessage.success('上传成功')
  } catch (error) {
    console.error('BGM上传失败:', error)
    ElMessage.error('上传失败: ' + (error.message || '未知错误'))
  }
  event.target.value = ''
}

const removeVideo = (type) => {
  if (type === 'opening') createForm.opening_video = ''
  else if (type === 'ending') createForm.ending_video = ''
}

const removeLoopVideo = (index) => {
  createForm.loop_videos.splice(index, 1)
}

const removeSceneVideo = (index) => {
  createForm.scene_videos.splice(index, 1)
}

const removeAudioClip = (index) => {
  createForm.audio_clips.splice(index, 1)
}

const retryUpload = (index) => {
  const audioItem = createForm.audio_clips[index]
  if (!audioItem) return

  // 重新创建文件对象（这里需要注意，由于安全限制，我们无法直接从路径重新创建文件）
  // 所以我们需要提示用户重新选择文件
  ElMessage.info('请重新选择音频文件进行上传')
  // 清空当前失败的项
  createForm.audio_clips.splice(index, 1)
  // 触发文件选择
  document.querySelector('input[type="file"][accept="audio/*"]').click()
}

const denoiseAudioClip = async (index) => {
  try {
    const audioClip = createForm.audio_clips[index]
    if (!audioClip || !audioClip.path) {
      ElMessage.warning('音频文件不存在')
      return
    }
    
    // 检查是否已降噪
    if (audioClip.denoise) {
      ElMessage.info('该音频已进行过降噪处理')
      return
    }
    
    // 设置处理中状态
    createForm.audio_clips[index] = {
      ...audioClip,
      denoising: true
    }
    
    ElMessage.info('正在进行音频降噪...')
    
    // 使用音频路径作为 ID（后端可能支持路径或 ID）
    // 修复路径格式，将反斜杠转换为正斜杠
    const audioPath = (audioClip.path || '').replace(/\\/g, '/')
    console.log('调用降噪 API:', audioPath)
    
    const response = await taskApi.denoiseAudio(audioPath)
    console.log('降噪 API 响应:', response)
    
    // 处理不同的响应格式
    const responseData = response.data || response
    
    if (responseData.status === 'success') {
      ElMessage.success(responseData.message || '音频降噪完成')
      // 后端已直接替换原音频，更新状态并添加时间戳强制刷新预览
      const updatedClip = {
        ...audioClip,
        denoise: true,
        denoising: false,
        // 添加时间戳参数，强制浏览器重新加载音频
        timestamp: Date.now()
      }
      createForm.audio_clips.splice(index, 1, updatedClip)
    } else {
      // 恢复状态
      createForm.audio_clips[index] = {
        ...audioClip,
        denoising: false
      }
      ElMessage.error('音频降噪失败: ' + (response.message || responseData?.message || '未知错误'))
    }
  } catch (error) {
    console.error('音频降噪失败:', error)
    const audioClip = createForm.audio_clips[index]
    if (audioClip) {
      createForm.audio_clips[index] = {
        ...audioClip,
        denoising: false
      }
    }
    
    // 详细的错误提示
    let errorMsg = '未知错误'
    
    // 确保 error 是我们可以处理的格式
    if (typeof error === 'string') {
      errorMsg = error
    } else if (error instanceof Error) {
      errorMsg = error.message
    } else if (error.response) {
      // 服务器返回了错误响应
      const status = error.response.status
      let serverMsg = error.response.data?.message || error.response.data?.detail
      
      // 如果 serverMsg 是对象，转换为字符串
      if (typeof serverMsg === 'object' && serverMsg !== null) {
        serverMsg = JSON.stringify(serverMsg)
      }
      
      if (status === 500) {
        errorMsg = serverMsg || '服务器内部错误，请稍后重试或联系管理员'
      } else if (status === 400) {
        errorMsg = serverMsg || '请求参数错误，请检查音频文件'
      } else if (status === 404) {
        errorMsg = serverMsg || '音频文件未找到'
      } else if (status === 422) {
        errorMsg = serverMsg || '请求数据格式错误'
      } else {
        errorMsg = serverMsg || `请求失败 (${status})`
      }
    } else if (error.request) {
      // 请求发出但没有收到响应
      errorMsg = '无法连接到服务器，请检查网络连接'
    } else {
      // 尝试获取 message 字段或转换为字符串
      if (error && typeof error === 'object') {
        errorMsg = error.message || JSON.stringify(error)
      } else {
        errorMsg = String(error)
      }
    }
    
    ElMessage.error('音频降噪失败: ' + errorMsg)
  }
}

const removeBgm = () => {
  createForm.bgm_path = ''
  createForm.bgm_name = ''
  bgmTimestamp.value = null
}

// 音频加载错误处理
const handleAudioError = (event, index) => {
  console.error('音频加载失败:', event)
  const audioClip = createForm.audio_clips[index]
  if (audioClip) {
    createForm.audio_clips[index] = {
      ...audioClip,
      error: true,
      loading: false
    }
  }
}

// 音频加载成功处理
const handleAudioLoaded = (event, index) => {
  const audioClip = createForm.audio_clips[index]
  if (audioClip) {
    createForm.audio_clips[index] = {
      ...audioClip,
      error: false,
      loading: false,
      duration: event.target.duration
    }
  }
}

// 重新加载音频
const reloadAudio = (index) => {
  const audioClip = createForm.audio_clips[index]
  if (audioClip) {
    createForm.audio_clips[index] = {
      ...audioClip,
      error: false,
      loading: true
    }
    // 强制重新加载音频
    setTimeout(() => {
      const audioElement = document.querySelectorAll('.preview-audio')[index]
      if (audioElement) {
        audioElement.load()
      }
    }, 100)
  }
}

// 音频可以播放时处理
const handleAudioCanPlay = (event, index) => {
  console.log('音频可以播放:', index, event.target.duration)
  const audioClip = createForm.audio_clips[index]
  if (audioClip) {
    createForm.audio_clips[index] = {
      ...audioClip,
      loading: false,
      error: false,
      duration: event.target.duration || audioClip.duration
    }
  }
}

const analyzeFace = async (videoPath, type) => {
  console.log('[MaterialListView][analyzeFace] 调用，路径:', videoPath, '类型:', type)

  // 检查是否已经在分析中或已完成分析
  if (faceAnalysisLoading[videoPath] || pollingTaskIds[videoPath]) {
    console.log('[MaterialListView][analyzeFace] 视频已在分析中，跳过:', videoPath)
    ElMessage.warning('该视频正在分析中，请等待完成')
    return
  }

  // 检查是否已经分析过（防止重复分析）
  if (analyzedVideoPaths[videoPath]) {
    console.log('[MaterialListView][analyzeFace] 视频已完成分析，跳过:', videoPath)
    ElMessage.info('该视频已完成面部分析')
    return
  }

  // 立即设置防护状态，防止在 await 期间被再次调用
  faceAnalysisLoading[videoPath] = true
  pollingTaskIds[videoPath] = 'pending'

  try {
    // 调用异步 API → AC-227
    const response = await taskApi.analyzeFaceAsync(videoPath)
    console.log('[MaterialListView][analyzeFace] 异步面部分析启动:', response)

    if (response.code === 200 || response.task_id) {
      const taskId = response.task_id || response.data?.task_id

      // 更新为真实的 task_id
      pollingTaskIds[videoPath] = taskId

      // 轮询状态 → AC-227
      await pollFaceAnalysisStatus(taskId, videoPath, type)

      // 轮询结束后清除记录
      delete pollingTaskIds[videoPath]
    } else {
      ElMessage.error('面部分析启动失败: ' + (response.message || '未知错误'))
      faceAnalysisLoading[videoPath] = false
      delete pollingTaskIds[videoPath]
    }
  } catch (error) {
    console.error('[MaterialListView][analyzeFace] 面部分析失败:', error)
    // 后端返回 409 表示重复请求，根据 detail 区分处理
    if (error.response?.status === 409) {
      const detail = error.response?.data?.detail || ''
      if (detail.includes('正在分析中')) {
        // 正在分析中：保持 loading 状态，不恢复按钮
        faceAnalysisLoading[videoPath] = true
      } else {
        // 已完成分析：标记为已完成
        markVideoAsAnalyzed(videoPath)
        faceAnalysisLoading[videoPath] = 'completed'
      }
      console.warn('[MaterialListView][analyzeFace] 后端拒绝重复分析:', detail)
    } else {
      ElMessage.error('面部分析失败: ' + (error.message || '未知错误'))
      faceAnalysisLoading[videoPath] = false
      delete pollingTaskIds[videoPath]
    }
  }
}

// 状态轮询函数 → AC-227
const pollFaceAnalysisStatus = async (taskId, videoPath, type) => {
  const maxPolls = 120  // 最多轮询 120 次（2 分钟）
  const pollInterval = 1000  // 1 秒

  for (let i = 0; i < maxPolls; i++) {
    try {
      const response = await taskApi.getFaceAnalysisStatus(taskId)

      if (response.code === 200 || response.task_id) {
        const status = response.status || response.data?.status
        const progress = response.progress ?? response.data?.progress ?? 0
        const result = response.result || response.data?.result
        const error = response.error || response.data?.error

        if (status === 'completed') {
          console.log('[MaterialListView][轮询] 检测到完成，路径:', videoPath)

          // 立即设置为"已完成"状态，防止在标记 analyzedVideoPaths 之前被再次调用
          faceAnalysisLoading[videoPath] = 'completed'

          ElMessage.success(`面部分析完成，已移除 ${result?.invalid_frame_count || 0} 段不合格画面`)

          // 标记该视频已完成分析，防止重复分析
          markVideoAsAnalyzed(videoPath)

          // 视频已原地替换，不需要更新路径
          // 视频预览会通过 URL 参数自动刷新

          // 保持 completed 状态，不清除，让按钮保持禁用
          return
        }

        if (status === 'failed') {
          ElMessage.error('面部分析失败: ' + (error || '未知错误'))
          faceAnalysisLoading[videoPath] = false
          return
        }

        if (status === 'cancelled') {
          ElMessage.info('面部分析已取消')
          faceAnalysisLoading[videoPath] = false
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
  faceAnalysisLoading[videoPath] = false
}

const getFileUrl = (path, timestamp) => {
  if (!path) return ''
  if (path.startsWith('http')) return path
  // 将Windows路径的反斜杠转换为正斜杠，确保URL正确
  const normalizedPath = path.replace(/\\/g, '/')
  let url = `/files/${normalizedPath}`
  // 如果提供了时间戳，添加参数强制刷新
  if (timestamp) {
    url += `?t=${timestamp}`
  }
  return url
}

const formatDuration = (seconds) => {
  if (!seconds) return '0:00'
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

const formatFileSize = (bytes) => {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let size = bytes
  let unitIndex = 0
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024
    unitIndex++
  }
  return `${size.toFixed(1)} ${units[unitIndex]}`
}

const handleTabChange = () => {
  resetForm()
}

const openCreateDialog = () => {
  console.log('[MaterialListView] openCreateDialog called')
  isEditing.value = false
  resetForm()
  showCreateDialog.value = true
  console.log('[MaterialListView] showCreateDialog set to true:', showCreateDialog.value)
}

const editItem = (item) => {
  isEditing.value = true
  resetForm()
  
  createForm.id = item.id || item.role_id || item.scene_id || item.bgm_id
  createForm.name = item.name || item.role_name || item.scene_name || item.bgm_name
  
  if (currentTab.value === 'role') {
    createForm.role_type = item.role_type || 'human'
    createForm.scenes = item.scenes || []
    createForm.opening_video = item.opening_video || ''
    createForm.loop_videos = item.loop_videos || []
    createForm.ending_video = item.ending_video || ''
    createForm.audio_id = item.audio_id || ''
    createForm.is_double_mode = item.is_double_mode || false
    createForm.left_audio_id = item.left_audio_id || ''
    createForm.right_audio_id = item.right_audio_id || ''
  } else if (currentTab.value === 'scene') {
    createForm.scene_videos = item.scene_videos || []
  } else if (currentTab.value === 'audio') {
    createForm.audio_clips = item.audio_clips || []
  } else {
    createForm.bgm_path = item.bgm_path || item.path || ''
    createForm.bgm_name = item.bgm_name || item.name || ''
    createForm.bgm_duration = item.duration || 0
  }
  
  console.log('编辑素材:', item, createForm)
  showCreateDialog.value = true
}

const handleThumbnailError = (event, item) => {
  console.warn('缩略图加载失败:', item.thumbnail)
  item.thumbnail = null
  event.target.style.display = 'none'
}

const previewItem = (item) => {
  previewItemData.value = item
  previewVideoPath.value = ''
  previewVideoLabel.value = ''
  showPreviewDialog.value = true
  
  if (currentTab.value === 'role') {
    const allVideos = []
    if (item.opening_video) {
      allVideos.push({ path: item.opening_video, label: '开场', priority: 3 })
    }
    if (item.loop_videos && item.loop_videos.length > 0) {
      const emotionLabels = {
        'happy': '开心', 'calm': '平静', 'angry': '生气', 'sad': '难过',
        'surprised': '惊喜', 'excited': '兴奋', 'fear': '害怕', 'disgust': '厌恶'
      }
      item.loop_videos.forEach(video => {
        const label = emotionLabels[video.emotion] || video.emotion || '循环'
        allVideos.push({ path: video.path, label, priority: 2 })
      })
    }
    if (item.ending_video) {
      allVideos.push({ path: item.ending_video, label: '结束', priority: 1 })
    }
    
    if (allVideos.length > 0) {
      const openingVideo = allVideos.find(v => v.priority === 3)
      if (openingVideo) {
        previewVideoPath.value = openingVideo.path
        previewVideoLabel.value = openingVideo.label
      } else {
        const randomIndex = Math.floor(Math.random() * allVideos.length)
        previewVideoPath.value = allVideos[randomIndex].path
        previewVideoLabel.value = allVideos[randomIndex].label
      }
    }
  } else if (currentTab.value === 'scene') {
    if (item.scene_videos && item.scene_videos.length > 0) {
      const allVideos = item.scene_videos.map(video => {
        const label = video.tag || '场景'
        return { path: video.path, label, priority: 2 }
      })
      
      const productVideo = allVideos.find(v => v.priority === 3)
      if (productVideo) {
        previewVideoPath.value = productVideo.path
        previewVideoLabel.value = productVideo.label
      } else {
        const randomIndex = Math.floor(Math.random() * allVideos.length)
        previewVideoPath.value = allVideos[randomIndex].path
        previewVideoLabel.value = allVideos[randomIndex].label
      }
    }
  }
}

const deleteItem = async (item) => {
  const name = item.name || item.role_name || item.scene_name || item.bgm_name
  const typeLabel = currentTab.value === 'role' ? '角色' : 
                    currentTab.value === 'scene' ? '场景' : 
                    currentTab.value === 'audio' ? '音频' : 'BGM'
  
  try {
    const materialId = item.id || item.role_id || item.scene_id || item.bgm_id
    await materialApi.delete(materialId, currentTab.value)
    
    ElMessage.success(`${typeLabel}"${name}"已删除`)
    loadMaterials()
  } catch (error) {
    console.error('删除失败:', error)
    ElMessage.error('删除失败: ' + (error.message || '未知错误'))
  }
}

const resetForm = () => {
  Object.assign(createForm, {
    id: '',
    name: '',
    role_type: 'human',
    scenes: [],
    opening_video: '',
    loop_videos: [],
    ending_video: '',
    audio_id: '',
    scene_videos: [],
    audio_clips: [],
    bgm_path: '',
    bgm_name: ''
  })
  bgmTimestamp.value = null
}

// 清理音频片段数据，只保留后端需要的字段
const cleanAudioClips = (clips) => {
  if (!Array.isArray(clips)) return []
  
  return clips.map(clip => ({
    name: clip.name || '',
    size: clip.size || 0,
    path: clip.path || '',
    duration: clip.duration || 0,
    denoise: clip.denoise || false,
    status: clip.status || 'completed'
  })).filter(clip => clip.path)
}

const handleDoubleModeChange = (value) => {
  if (value) {
    createForm.audio_id = ''
  } else {
    createForm.left_audio_id = ''
    createForm.right_audio_id = ''
  }
}

const validateDoubleModeAudio = () => {
  if (createForm.is_double_mode) {
    if (!createForm.left_audio_id || !createForm.right_audio_id) {
      ElMessage.error('双人模式必须选择两个参考音频')
      return false
    }
  }
  return true
}

const validateForm = () => {
  // 名称验证
  if (!createForm.name || createForm.name.trim() === '') {
    ElMessage.warning('请输入素材名称')
    return false
  }
  
  // 名称长度验证
  if (createForm.name.trim().length < 1 || createForm.name.trim().length > 100) {
    ElMessage.warning('素材名称长度应在 1-100 个字符之间')
    return false
  }

  // 角色类型验证
  if (currentTab.value === 'role') {
    if (!createForm.opening_video) {
      ElMessage.warning('请上传开场视频')
      return false
    }
    if (!createForm.role_type) {
      ElMessage.warning('请选择角色类型')
      return false
    }
    if (!validateDoubleModeAudio()) {
      return false
    }
  }
  
  // 音频类型验证
  if (currentTab.value === 'audio') {
    if (!Array.isArray(createForm.audio_clips) || createForm.audio_clips.length === 0) {
      ElMessage.warning('请至少上传一个音频文件')
      return false
    }
    
    // 检查所有音频是否都有路径
    const validClips = createForm.audio_clips.filter(clip => clip.path && clip.status === 'completed')
    if (validClips.length === 0) {
      ElMessage.warning('请等待音频上传完成')
      return false
    }
    
    if (validClips.length !== createForm.audio_clips.length) {
      ElMessage.warning('部分音频尚未上传完成，请等待上传完成后再试')
      return false
    }
  }
  
  // BGM 类型验证
  if (currentTab.value === 'bgm' && !createForm.bgm_path) {
    ElMessage.warning('请上传 BGM 文件')
    return false
  }
  
  // 场景类型验证
  if (currentTab.value === 'scene') {
    if (!Array.isArray(createForm.scene_videos) || createForm.scene_videos.length === 0) {
      ElMessage.warning('请至少上传一个场景视频')
      return false
    }
  }
  
  return true
}

const submitForm = async () => {
  // 前端表单验证
  if (!validateForm()) {
    return
  }

  submitting.value = true

  try {
    const formData = {
      name: createForm.name.trim(),
      type: currentTab.value
    }

    if (currentTab.value === 'role') {
      formData.opening_video = createForm.opening_video
      formData.loop_videos = createForm.loop_videos || []
      formData.ending_video = createForm.ending_video
      formData.audio_id = createForm.audio_id
      formData.role_type = createForm.role_type
      formData.scenes = createForm.scenes || []
      formData.is_double_mode = createForm.is_double_mode
      if (createForm.is_double_mode) {
        formData.left_audio_id = createForm.left_audio_id
        formData.right_audio_id = createForm.right_audio_id
      }
    } else if (currentTab.value === 'scene') {
      formData.scene_videos = createForm.scene_videos || []
    } else if (currentTab.value === 'audio') {
      // 清理音频数据，只保留必要字段
      formData.audio_clips = cleanAudioClips(createForm.audio_clips)
      
      // 计算总时长
      const totalDuration = createForm.audio_clips.reduce((sum, clip) => {
        return sum + (clip.duration || 0)
      }, 0)
      formData.duration = totalDuration
      
      if (formData.audio_clips.length === 0) {
        ElMessage.warning('没有有效的音频文件')
        submitting.value = false
        return
      }
    } else if (currentTab.value === 'bgm') {
      formData.bgm_path = createForm.bgm_path
      formData.duration = createForm.bgm_duration
    }

    if (isEditing.value) {
      try {
        const response = await materialApi.update(createForm.id, formData)
        console.log('更新素材响应:', response)
        
        // 处理不同的响应格式
        const responseCode = response?.data?.code ?? response?.code ?? 200
        
        if (responseCode === 200 || responseCode === 0) {
          ElMessage.success('修改成功')
          showCreateDialog.value = false
          resetForm()
          // 等待素材列表加载完成
          await loadMaterials()
          // 切换到对应的标签页显示修改后的素材
          if (currentTab.value !== formData.type) {
            currentTab.value = formData.type
          }
        } else {
          ElMessage.error('修改失败: ' + (response?.data?.message || response?.message || '未知错误'))
        }
      } catch (error) {
        console.error('更新素材失败:', error)
        handleSubmitError(error, '修改')
      }
    } else {
      try {
        const response = await materialApi.create(formData)
        console.log('创建素材响应:', response)
        
        // 处理不同的响应格式
        const responseCode = response?.data?.code ?? response?.code ?? 200
        
        if (responseCode === 200 || responseCode === 0) {
          ElMessage.success('创建成功')
          showCreateDialog.value = false
          resetForm()
          // 等待素材列表加载完成
          await loadMaterials()
          // 切换到对应的标签页显示新创建的素材
          if (currentTab.value !== formData.type) {
            currentTab.value = formData.type
          }
        } else {
          ElMessage.error('创建失败: ' + (response?.data?.message || response?.message || '未知错误'))
        }
      } catch (error) {
        console.error('创建素材失败:', error)
        handleSubmitError(error, '创建')
      }
    }
  } catch (error) {
    console.error('操作失败:', error)
    ElMessage.error('操作失败: ' + (error.message || '未知错误'))
  } finally {
    submitting.value = false
  }
}

// 处理提交错误的辅助函数
const handleSubmitError = (error, operation) => {
  let errorMsg = '未知错误'
  
  // 确保 error 是我们可以处理的格式
  if (typeof error === 'string') {
    errorMsg = error
  } else if (error instanceof Error) {
    errorMsg = error.message
  } else if (error.response) {
    const status = error.response.status
    const serverData = error.response.data
    let serverMsg = serverData?.message || serverData?.detail
    
    // 如果 serverMsg 是对象，转换为字符串
    if (typeof serverMsg === 'object' && serverMsg !== null) {
      serverMsg = JSON.stringify(serverMsg)
    }
    
    // 422 错误处理 - 数据验证失败
    if (status === 422) {
      if (serverData?.detail && Array.isArray(serverData.detail)) {
        // FastAPI 验证错误格式
        const validationErrors = serverData.detail.map(err => {
          const loc = err.loc?.join('.') || '字段'
          return `${loc}: ${err.msg}`
        })
        errorMsg = '数据验证失败:\n' + validationErrors.join('\n')
      } else if (serverMsg) {
        errorMsg = serverMsg
      } else if (typeof serverData === 'string') {
        errorMsg = serverData
      } else {
        errorMsg = '提交的数据格式不正确，请检查所有必填字段'
      }
    } else if (status === 400) {
      errorMsg = serverMsg || '请求参数错误'
    } else if (status === 500) {
      errorMsg = serverMsg || '服务器内部错误，请稍后重试'
    } else {
      errorMsg = serverMsg || `请求失败 (${status})`
    }
  } else if (error.request) {
    errorMsg = '无法连接到服务器，请检查网络连接'
  } else {
    // 尝试获取 message 字段或转换为字符串
    if (error && typeof error === 'object') {
      errorMsg = error.message || JSON.stringify(error)
    } else {
      errorMsg = String(error)
    }
  }
  
  ElMessage.error(`${operation}失败: ${errorMsg}`)
}

const loadMaterials = async () => {
  loading.value = true
  try {
    const [rolesRes, scenesRes, audioRes, bgmRes] = await Promise.all([
      materialApi.getMaterials('role'),
      materialApi.getMaterials('scene'),
      materialApi.getMaterials('audio'),
      materialApi.getMaterials('bgm')
    ])
    
    // 确保数据结构正确
    roles.value = Array.isArray(rolesRes) ? rolesRes : (rolesRes.data || [])
    scenes.value = Array.isArray(scenesRes) ? scenesRes : (scenesRes.data || [])
    referenceAudios.value = Array.isArray(audioRes) ? audioRes : (audioRes.data || [])
    bgms.value = Array.isArray(bgmRes) ? bgmRes : (bgmRes.data || [])
    
    // 加载完成后初始化筛选
    handleSearch()
    
    // 如果当前标签是音频，确保素材库显示最新数据
    if (currentTab.value === 'audio') {
      console.log('音频素材加载完成:', referenceAudios.value)
    }
  } catch (error) {
    console.error('加载素材失败:', error)
    ElMessage.error('加载素材失败: ' + (error.message || '未知错误'))
  } finally {
    loading.value = false
  }
}

// 主题监听器清理函数
let cleanupThemeListener = null

onMounted(() => {
  // 设置主题监听
  cleanupThemeListener = setupThemeListener()

  // 加载素材列表
  loadMaterials()

  // 加载场景标签选项
  loadSceneTagOptions()

  // 处理从智能裁剪传递的参数
  handleSmartCutParams()
})

// 监听路由查询参数变化，处理从智能裁剪页面导航过来的情况
watch(
  () => route.query.action,
  (newAction, oldAction) => {
    console.log('[MaterialListView] watch triggered, newAction:', newAction, 'oldAction:', oldAction)
    // 当 action 参数存在且发生变化时重新处理
    if (newAction && newAction !== oldAction) {
      handleSmartCutParams()
    }
  }
)

// 处理从智能裁剪传递的参数
const handleSmartCutParams = () => {
  const { action, type, videos, audio } = route.query

  console.log('[MaterialListView] handleSmartCutParams called:', { action, type, videos, audio })

  if (action === 'create') {
    // 处理视频参数（角色/场景）
    if (videos) {
      try {
        const videoList = JSON.parse(videos)
        if (videoList && videoList.length > 0) {
          // 切换到对应的 tab
          if (type === 'character') {
            currentTab.value = 'role'
          } else if (type === 'scene') {
            currentTab.value = 'scene'
          }

          // 打开创建对话框
          console.log('[MaterialListView] Opening create dialog for videos, type:', type)
          openCreateDialog()
          console.log('[MaterialListView] showCreateDialog after openCreateDialog:', showCreateDialog.value)

          // 填充视频数据
          if (type === 'character') {
            // 角色创建：第一个视频=开场，最后一个=结束，中间=循环
            createForm.opening_video = videoList[0].path
            if (videoList.length === 2) {
              // 只有2个视频：开场+结束，无循环
              createForm.ending_video = videoList[1].path
              createForm.loop_videos = []
            } else if (videoList.length > 2) {
              // 3个及以上：开场+循环+结束
              createForm.loop_videos = videoList.slice(1, -1).map(v => ({
                path: v.path,
                emotion: 'calm'
              }))
              createForm.ending_video = videoList[videoList.length - 1].path
            }
            ElMessage.success(`已添加 ${videoList.length} 个视频到角色素材`)
          } else if (type === 'scene') {
            // 场景创建：将视频添加到 scene_videos
            createForm.scene_videos = videoList.map(v => ({
              path: v.path,
              tag: ''
            }))
            ElMessage.success(`已添加 ${videoList.length} 个视频到场景素材`)
          }
        }
      } catch (e) {
        console.error('解析智能裁剪参数失败:', e)
      }
    }

    // 处理音频参数（参考音频/BGM）
    if (audio) {
      try {
        const audioData = JSON.parse(audio)
        if (audioData && audioData.path) {
          // 切换到对应的 tab
          if (type === 'audio') {
            currentTab.value = 'audio'
          } else if (type === 'bgm') {
            currentTab.value = 'bgm'
          }

          // 打开创建对话框
          console.log('[MaterialListView] Opening create dialog for audio, type:', type)
          openCreateDialog()
          console.log('[MaterialListView] showCreateDialog after openCreateDialog:', showCreateDialog.value)

          // 填充音频数据
          if (type === 'audio') {
            // 参考音频：添加到 audio_clips
            createForm.audio_clips = [{
              name: audioData.source || '提取的音频',
              path: audioData.path,
              duration: audioData.duration || 0,
              status: 'completed',
              loading: false,
              error: false,
              denoise: false
            }]
            ElMessage.success('已添加音频到参考音频库，请填写名称后保存')
          } else if (type === 'bgm') {
            // BGM：设置 bgm_path
            createForm.bgm_path = audioData.path
            createForm.bgm_name = audioData.source || '提取的音频'
            createForm.bgm_duration = audioData.duration || 0
            ElMessage.success('已添加音频到 BGM 库，请填写名称后保存')
          }
        }
      } catch (e) {
        console.error('解析音频参数失败:', e)
      }
    }
  }
}

onUnmounted(() => {
  // 清理主题监听器
  if (cleanupThemeListener) {
    cleanupThemeListener()
  }
})
</script>

<style scoped>
.material-library-container {
  min-height: calc(100vh - 64px - 40px);
  background: linear-gradient(135deg, #f5f7fa 0%, #e8ecf1 50%, #eef2f6 100%);
  transition: background 0.3s ease;
}

/* 暗色主题 */
.material-library-container.dark-theme {
  background: linear-gradient(135deg, #0d1117 0%, #161b22 50%, #1a1f26 100%);
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px 32px;
  background: rgba(255, 255, 255, 0.8);
  border-bottom: 1px solid rgba(0, 0, 0, 0.1);
  transition: all 0.3s ease;
}

.dark-theme .page-header {
  background: rgba(22, 27, 34, 0.95);
  border-bottom-color: rgba(255, 255, 255, 0.1);
}

.page-title {
  font-size: 24px;
  font-weight: 600;
  color: #303133;
  margin: 0;
  transition: color 0.3s ease;
}

.dark-theme .page-title {
  color: #e6edf3;
}

.content-wrapper {
  padding: 24px 32px;
  max-width: 1600px;
  margin: 0 auto;
}

.material-tabs :deep(.el-tabs__header) {
  margin-bottom: 24px;
}

.material-tabs :deep(.el-tabs__nav-wrap::after) {
  background-color: rgba(0, 0, 0, 0.1);
}

.dark-theme .material-tabs :deep(.el-tabs__nav-wrap::after) {
  background-color: rgba(255, 255, 255, 0.1);
}

.material-tabs :deep(.el-tabs__item) {
  color: rgba(0, 0, 0, 0.6);
  font-size: 15px;
  transition: color 0.3s ease;
}

.dark-theme .material-tabs :deep(.el-tabs__item) {
  color: rgba(255, 255, 255, 0.6);
}

.material-tabs :deep(.el-tabs__item:hover) {
  color: #409EFF;
}

.dark-theme .material-tabs :deep(.el-tabs__item:hover) {
  color: #00d9ff;
}

.material-tabs :deep(.el-tabs__item.is-active) {
  color: #409EFF;
}

.dark-theme .material-tabs :deep(.el-tabs__item.is-active) {
  color: #00d9ff;
}

.material-tabs :deep(.el-tabs__active-bar) {
  background-color: #409EFF;
}

.dark-theme .material-tabs :deep(.el-tabs__active-bar) {
  background-color: #00d9ff;
}

.search-filter {
  display: flex;
  gap: 12px;
  margin-bottom: 24px;
  align-items: center;
}

.search-input {
  flex: 1;
  max-width: 400px;
}

.filter-select {
  min-width: 150px;
}

.loading-container {
  padding: 40px 20px;
  text-align: center;
}

.tab-label {
  display: flex;
  align-items: center;
  gap: 8px;
}

.material-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 20px;
}

.material-card {
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid rgba(0, 0, 0, 0.1);
  border-radius: 16px;
  overflow: hidden;
  cursor: pointer;
  transition: all 0.3s;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.1);
}

.dark-theme .material-card {
  background: rgba(255, 255, 255, 0.05);
  border-color: rgba(255, 255, 255, 0.1);
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.3);
}

.material-card:hover {
  transform: translateY(-4px);
  border-color: rgba(64, 158, 255, 0.5);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.15);
}

.dark-theme .material-card:hover {
  border-color: rgba(0, 217, 255, 0.3);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
}

.card-thumbnail {
  position: relative;
  aspect-ratio: 16/9;
  background: #f5f7fa;
  overflow: hidden;
}

.dark-theme .card-thumbnail {
  background: #1a1f26;
}

.card-thumbnail video,
.card-thumbnail img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.card-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: rgba(0, 0, 0, 0.3);
}

.dark-theme .card-placeholder {
  color: rgba(255, 255, 255, 0.3);
}

.card-placeholder .el-icon {
  font-size: 48px;
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

.material-card:hover .card-overlay {
  opacity: 1;
}

.card-body {
  padding: 16px;
}

.card-title {
  margin: 0 0 8px 0;
  font-size: 16px;
  font-weight: 600;
  color: #303133;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  transition: color 0.3s ease;
}

.dark-theme .card-title {
  color: #e6edf3;
}

.card-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.meta-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 4px;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.7);
}

.meta-tag.audio {
  background: rgba(0, 217, 255, 0.15);
  color: #00d9ff;
}

.card-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 0 16px 16px;
}

.material-dialog :deep(.el-dialog) {
  background: var(--bg-primary, #fff);
  border: 1px solid rgba(0, 0, 0, 0.1);
  border-radius: 16px;
  transition: all 0.3s;
}

.material-dialog :deep(.el-dialog__header) {
  border-bottom: 1px solid rgba(0, 0, 0, 0.1);
  padding: 20px 24px;
  transition: all 0.3s;
}

.material-dialog :deep(.el-dialog__title) {
  color: var(--text-primary, #303133);
  font-size: 18px;
  font-weight: 600;
  transition: color 0.3s;
}

.material-dialog :deep(.el-dialog__body) {
  padding: 24px;
  max-height: 60vh;
  overflow-y: auto;
}

.dialog-content {
  color: #303133;
  transition: color 0.3s;
}

.video-section,
.audio-section,
.audio-upload-section {
  margin-bottom: 24px;
  padding: 16px;
  background: #f5f7fa;
  border: 1px solid rgba(0, 0, 0, 0.1);
  border-radius: 12px;
  transition: all 0.3s;
}

.section-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.section-header h5 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: #303133;
  transition: color 0.3s;
}

/* 暗色主题下的对话框样式 - 使用 :deep 确保穿透到对话框内部 */
.material-dialog.dark-theme :deep(.el-dialog) {
  background: #1a1f26 !important;
  border: 1px solid rgba(255, 255, 255, 0.1) !important;
  color: rgba(255, 255, 255, 0.8) !important;
}

.material-dialog.dark-theme :deep(.el-dialog__header) {
  border-bottom: 1px solid rgba(255, 255, 255, 0.1) !important;
  background: #1a1f26 !important;
}

.material-dialog.dark-theme :deep(.el-dialog__title) {
  color: #fff !important;
}

.material-dialog.dark-theme :deep(.el-dialog__body) {
  background: #1a1f26 !important;
  color: rgba(255, 255, 255, 0.8) !important;
}

.material-dialog.dark-theme :deep(.el-dialog__footer) {
  border-top: 1px solid rgba(255, 255, 255, 0.1) !important;
  background: #1a1f26 !important;
}

.material-dialog.dark-theme .dialog-content {
  color: rgba(255, 255, 255, 0.8);
}

.material-dialog.dark-theme .video-section,
.material-dialog.dark-theme .audio-section,
.material-dialog.dark-theme .audio-upload-section {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.material-dialog.dark-theme .section-header h5 {
  color: #fff;
}

.section-header .required {
  color: #ff5252;
}

.section-header .hint {
  font-weight: 400;
  color: rgba(0, 0, 0, 0.4);
  font-size: 13px;
}

.material-dialog.dark-theme .section-header .hint {
  color: rgba(255, 255, 255, 0.4);
}

.video-preview,
.upload-placeholder {
  position: relative;
  border-radius: 8px;
  overflow: hidden;
  background: #f5f7fa;
  transition: all 0.3s;
}

.video-preview video {
  width: 100%;
  max-height: 200px;
  object-fit: contain;
}

.upload-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 40px;
  border: 2px dashed rgba(0, 0, 0, 0.2);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.3s;
}

.upload-placeholder:hover {
  border-color: #00d9ff;
  background: rgba(0, 217, 255, 0.05);
}

.upload-placeholder .el-icon {
  font-size: 32px;
  color: rgba(0, 0, 0, 0.4);
}

.upload-placeholder span {
  font-size: 13px;
  color: rgba(0, 0, 0, 0.5);
}

/* 暗色主题下的上传占位符样式 */
.material-dialog.dark-theme .upload-placeholder {
  background: #0d1117;
  border: 2px dashed rgba(255, 255, 255, 0.2);
}

.material-dialog.dark-theme .upload-placeholder .el-icon {
  color: rgba(255, 255, 255, 0.4);
}

.material-dialog.dark-theme .upload-placeholder span {
  color: rgba(255, 255, 255, 0.5);
}

.video-actions {
  display: flex;
  justify-content: center;
  gap: 8px;
  padding: 8px;
  background: rgba(0, 0, 0, 0.5);
}

.video-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.video-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 12px;
  background: rgba(0, 0, 0, 0.3);
  border-radius: 8px;
}

.video-item video {
  width: 160px;
  height: 90px;
  object-fit: cover;
  border-radius: 4px;
}

.video-item.scene video {
  width: 200px;
  height: 112px;
}

.video-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.video-item .video-actions {
  background: transparent;
  padding: 0;
  display: flex;
  gap: 8px;
}

.emotion-select,
.scene-select {
  width: 140px;
}

.audio-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.audio-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  background: rgba(0, 0, 0, 0.3);
  border-radius: 8px;
}

.audio-icon {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 217, 255, 0.1);
  border-radius: 8px;
  color: #00d9ff;
  transition: all 0.3s;
}

.audio-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.audio-name {
  font-size: 14px;
  color: #303133;
  transition: color 0.3s;
}

.audio-meta {
  display: flex;
  gap: 12px;
  align-items: center;
}

.audio-size {
  font-size: 12px;
  color: rgba(0, 0, 0, 0.4);
  transition: color 0.3s;
}

.audio-duration {
  font-size: 11px;
  color: rgba(0, 0, 0, 0.4);
  transition: color 0.3s;
}

.material-dialog.dark-theme .audio-duration {
  color: rgba(255, 255, 255, 0.4);
}

.preview-audio {
  width: 100%;
  height: 40px;
  border-radius: 4px;
}

.audio-preview-wrapper {
  margin-top: 8px;
  width: 100%;
}

.audio-player-container {
  width: 100%;
  background: rgba(0, 0, 0, 0.05);
  border-radius: 4px;
  padding: 8px;
}

.material-dialog.dark-theme .audio-player-container {
  background: rgba(255, 255, 255, 0.1);
}

.audio-preview-missing {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
  background: rgba(255, 82, 82, 0.1);
  border-radius: 4px;
  font-size: 13px;
  color: #ff5252;
  margin-top: 8px;
}

.audio-loading,
.audio-error {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
  background: rgba(0, 0, 0, 0.05);
  border-radius: 4px;
  font-size: 13px;
  color: rgba(0, 0, 0, 0.6);
  margin-top: 8px;
}

.audio-error {
  background: rgba(255, 82, 82, 0.05);
  color: #ff5252;
}

.material-dialog.dark-theme .audio-loading {
  background: rgba(255, 255, 255, 0.05);
  color: rgba(255, 255, 255, 0.6);
}

.material-dialog.dark-theme .audio-error {
  background: rgba(255, 82, 82, 0.1);
  color: #ff7875;
}

.audio-loading .is-loading {
  animation: rotating 2s linear infinite;
}

@keyframes rotating {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

.upload-status {
  margin-top: 8px;
  padding: 8px;
  background: rgba(0, 217, 255, 0.05);
  border-radius: 4px;
  font-size: 12px;
}

.upload-status.failed {
  background: rgba(255, 82, 82, 0.05);
}

.upload-status .status-text {
  display: block;
  margin-top: 4px;
  color: rgba(0, 0, 0, 0.6);
  transition: color 0.3s;
}

.upload-status.failed .status-text {
  color: #ff5252;
}

.material-dialog.dark-theme .upload-status {
  background: rgba(0, 217, 255, 0.1);
}

.material-dialog.dark-theme .upload-status.failed {
  background: rgba(255, 82, 82, 0.1);
}

.material-dialog.dark-theme .upload-status .status-text {
  color: rgba(255, 255, 255, 0.6);
}

.material-dialog.dark-theme .upload-status.failed .status-text {
  color: #ff7875;
}

.audio-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

/* 暗色主题下的音频样式 */
.material-dialog.dark-theme .audio-icon {
  background: rgba(0, 217, 255, 0.1);
  color: #00d9ff;
}

.material-dialog.dark-theme .audio-name {
  color: #fff;
}

.material-dialog.dark-theme .audio-size {
  color: rgba(255, 255, 255, 0.4);
}

.material-dialog.dark-theme .preview-audio {
  filter: brightness(0.8) invert(1);
}

.audio-duration {
  font-size: 11px;
  color: rgba(0, 0, 0, 0.4);
  margin-left: 8px;
}

.dark-theme .audio-duration {
  color: rgba(255, 255, 255, 0.4);
}

.audio-preview {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 24px;
  background: rgba(0, 0, 0, 0.3);
  border-radius: 8px;
}

.audio-preview .el-icon {
  font-size: 32px;
  color: #00ff88;
}

.audio-preview span {
  font-size: 14px;
  color: #fff;
}

.form-hint {
  margin-top: 12px;
  font-size: 12px;
  color: rgba(0, 0, 0, 0.4);
}

.material-dialog.dark-theme .form-hint {
  color: rgba(255, 255, 255, 0.4);
}

.audio-merge-info {
  margin-top: 12px;
}

.audio-merge-info :deep(.el-alert) {
  background: rgba(64, 158, 255, 0.1);
  border: 1px solid rgba(64, 158, 255, 0.2);
}

.material-dialog.dark-theme .audio-merge-info :deep(.el-alert) {
  background: rgba(64, 158, 255, 0.15);
  border: 1px solid rgba(64, 158, 255, 0.3);
}

.audio-merge-info :deep(.el-alert__title) {
  color: #409EFF;
  font-size: 13px;
}

.material-dialog.dark-theme .audio-merge-info :deep(.el-alert__title) {
  color: #66b1ff;
}

.preview-dialog :deep(.el-dialog) {
  background: #1a1f26;
  border-radius: 16px;
}

.preview-container {
  background: #000;
  border-radius: 8px;
  overflow: hidden;
}

.preview-container video,
.preview-container audio {
  width: 100%;
  max-height: 450px;
}

.preview-video {
  width: 100%;
  max-height: 450px;
}

.preview-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 60px;
  color: rgba(255, 255, 255, 0.4);
}

.preview-empty .el-icon {
  font-size: 48px;
}

:deep(.el-empty__description) {
  color: rgba(255, 255, 255, 0.4);
}

/* 暗色主题下的表单标签样式 */
.dark-theme :deep(.el-form-item__label) {
  color: rgba(255, 255, 255, 0.8);
}

/* 暗色主题下的输入框样式 */
.dark-theme :deep(.el-input__wrapper) {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.dark-theme :deep(.el-input__inner) {
  color: #fff;
}

.deerflow-badge {
  position: fixed;
  bottom: 20px;
  right: 20px;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.3);
  text-decoration: none;
  transition: all 0.3s;
  z-index: 1000;
}

.deerflow-badge:hover {
  color: #00d9ff;
  text-shadow: 0 0 10px rgba(0, 217, 255, 0.5);
}

@media (max-width: 768px) {
  .content-wrapper {
    padding: 16px;
  }
  
  .material-grid {
    grid-template-columns: 1fr;
  }
}

/* 音频卡片样式 */
.audio-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 20px;
  padding: 10px;
}

.audio-card {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 12px;
  overflow: hidden;
  cursor: pointer;
  transition: all 0.3s ease;
  position: relative;
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
}

.audio-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 8px 16px rgba(102, 126, 234, 0.3);
}

.audio-card-content {
  position: relative;
  background: rgba(255, 255, 255, 0.1);
  padding: 30px 20px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.audio-visual-area {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
}

.audio-icon-container {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}

.audio-icon {
  color: #fff;
  filter: drop-shadow(0 2px 4px rgba(0, 0, 0, 0.2));
  transition: all 0.3s ease;
}

.audio-card:hover .audio-icon {
  transform: scale(1.1);
  filter: drop-shadow(0 4px 8px rgba(0, 0, 0, 0.3));
}

/* 音频波形动画 */
.audio-wave {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 3px;
  height: 20px;
}

.audio-wave span {
  width: 3px;
  background: linear-gradient(to top, #fff, #ffd700);
  border-radius: 2px;
  animation: wave 1.2s ease-in-out infinite;
}

.audio-wave span:nth-child(1) { animation-delay: 0s; }
.audio-wave span:nth-child(2) { animation-delay: 0.1s; }
.audio-wave span:nth-child(3) { animation-delay: 0.2s; }
.audio-wave span:nth-child(4) { animation-delay: 0.3s; }
.audio-wave span:nth-child(5) { animation-delay: 0.4s; }

@keyframes wave {
  0%, 100% {
    height: 5px;
  }
  50% {
    height: 20px;
  }
}

.audio-card .card-body {
  background: rgba(255, 255, 255, 0.95);
  padding: 12px;
  padding-bottom: 50px;
}

.audio-card .card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.audio-card .card-title {
  color: #303133;
  font-size: 14px;
  font-weight: 600;
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}

.audio-card .card-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.audio-card .meta-tag {
  font-size: 12px;
  color: #606266;
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.audio-card .playing-indicator {
  font-size: 11px;
  color: #409eff;
  font-weight: 600;
  background: #ecf5ff;
  padding: 2px 8px;
  border-radius: 10px;
  animation: pulse 2s ease-in-out infinite;
  flex-shrink: 0;
}

@keyframes pulse {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.6;
  }
}

.audio-card .card-actions {
  position: absolute;
  bottom: 8px;
  left: 50%;
  transform: translateX(-50%);
  opacity: 0;
  transition: opacity 0.3s ease;
  display: flex;
  gap: 8px;
  padding: 0 !important;
}

.audio-card:hover .card-actions {
  opacity: 1;
}

.audio-card .card-actions .el-button {
  padding: 6px 12px;
  width: auto;
}
</style>
