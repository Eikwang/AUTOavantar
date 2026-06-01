import { defineStore } from 'pinia'
import { settingsApi } from '@/services/api'

export const useSettingsStore = defineStore('settings', {
  state: () => ({
    settings: {
      deepseek_api_key: '',
      aliyun_api_key: '',
      single_person_prompt_template: '根据主题{theme}生成单人讲解文案，包含开场、情绪标签、场景标签、结束',
      dual_person_prompt_template: '根据主题{theme}生成双人对话文案，包含开场、左边说话人、右边说话人、情绪标签、场景标签、结束',
      cover_prompt_template: '根据文案{summary}生成视频封面，风格简洁，突出主题',
      heygem_original: true,
      heygem_inference_steps: 16,
      dual_mode: false,
      tts_speed: 1.0,
      tts_emo_weight: 0.4,
      enable_pip: false  // 画外音默认开关
    },
    isLoading: false,
    error: null
  }),

  getters: {
    singlePromptTemplate: (state) => state.settings.single_person_prompt_template,
    dualPromptTemplate: (state) => state.settings.dual_person_prompt_template,
    coverPromptTemplate: (state) => state.settings.cover_prompt_template
  },

  actions: {
    async fetchSettings() {
      this.isLoading = true
      this.error = null
      
      try {
        const response = await settingsApi.getSettings()
        if (response.code === 200) {
          const data = response.data || {}
          Object.keys(this.settings).forEach(key => {
            if (data[key] !== undefined) {
              this.settings[key] = data[key]
            }
          })
        }
      } catch (error) {
        this.error = error.message
        console.error('获取设置失败:', error)
      } finally {
        this.isLoading = false
      }
    },
    
    updateSettings(newSettings) {
      Object.keys(newSettings).forEach(key => {
        if (this.settings.hasOwnProperty(key)) {
          this.settings[key] = newSettings[key]
        }
      })
    },
    
    getPromptTemplate(mode) {
      return mode === 'dual' 
        ? this.settings.dual_person_prompt_template 
        : this.settings.single_person_prompt_template
    },
    
    clearError() {
      this.error = null
    }
  }
})
