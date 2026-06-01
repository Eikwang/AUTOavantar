# 项目说明
朋友们，项目代码是齐全的，只需要构建环境和补充模型文件即可。heygem代码是我向刘悦购买的，仅支持学习开发，禁止转卖！请不要去闲鱼转卖。

## 完整整合包正在上传网盘，待上传完成后再更新。

# AUTOavantar - 数字人视频生成系统

## 项目简介

AUTOavantar 是一个功能完整的数字人视频生成系统，集成了智能文案生成、语音合成、数字人生成等核心功能，提供一键式视频制作体验。

## 核心功能

### 1. 智能文案生成
- 支持 LLM 自动生成文案（DeepSeek / 阿里云）
- 支持自定义文案输入
- 文案自动分段解析
- 双人模式对话文案生成

### 2. 语音合成（TTS）
- 集成 IndexTTS 语音合成引擎
- 支持音色克隆（参考音频）
- 支持语速调节
- 单人/双人模式支持
- 音频降噪增强

### 3. 数字人生成
- 集成 HeyGem ONNX 数字人引擎
- 唇形同步
- 人脸增强
- 支持多种数字人模板

### 4. 视频合成
- 开场/结尾视频支持
- 循环视频素材
- 场景视频匹配
- BGM 背景音乐
- 视频分辨率和帧率统一
- 字幕生成与渲染

### 5. 素材库管理
- 视频素材管理
- 音频素材管理
- 标签分类系统
- 素材预览

### 6. 任务管理
- 任务创建与编辑
- 实时进度监控
- 任务历史记录
- 断点续传功能
- WebSocket 实时通知

## 技术架构

### 后端
- **框架**: FastAPI
- **数据库**: SQLite
- **任务调度**: 自定义任务队列
- **实时通信**: WebSocket

### 前端
- **框架**: Vue 3
- **UI 组件**: Element Plus
- **状态管理**: Pinia
- **路由**: Vue Router
- **构建工具**: Vite

### 核心服务
- **HeyGem 服务**: 数字人视频生成（端口 9889）
- **IndexTTS 服务**: 语音合成（端口 7860）
- **主 API 服务**: 业务逻辑（端口 9010）

## 快速开始

### 环境要求
- Python 3.10+
- Node.js 18+
- CUDA 11.8+（推荐）

### 一键启动

Windows 用户可以直接运行：
```bash
启动系统.bat
```

### 手动启动

#### 1. 启动 HeyGem 服务
```bash
cd Portrait
开始.bat
```

#### 2. 启动 IndexTTS 服务
```bash
cd voicel
运行_自动启动接口服务.bat
```

#### 3. 启动后端 API
```bash
cd backend
python -m uvicorn api.main:app --host 0.0.0.0 --port 9010 --reload
```

#### 4. 启动前端
```bash
cd frontend
npm install
npm run dev
```

## 项目结构

```
AUTOavantar/
├── backend/                 # 后端 API
│   ├── api/                # API 路由和服务
│   ├── config/             # 配置文件
│   └── tests/              # 测试文件
├── business/               # 业务逻辑
│   ├── audio/              # 音频处理
│   ├── llm/                # 文案生成
│   ├── video/              # 视频合成
│   ├── preprocess/         # 预处理
│   ├── postprocess/        # 后处理
│   └── workflow.py         # 工作流引擎
├── core/                   # 核心模块
│   ├── api_clients/        # API 客户端
│   ├── models/             # 数据模型
│   ├── scheduler/          # 任务调度
│   └── monitor/            # 资源监控
├── frontend/               # 前端应用
│   ├── src/
│   │   ├── views/          # 页面组件
│   │   ├── components/     # 通用组件
│   │   ├── stores/         # 状态管理
│   │   └── api/            # API 封装
│   └── package.json
├── Portrait/    # HeyGem 数字人服务
├── voicel/           # IndexTTS 语音合成服务
├── config/                 # 配置文件
├── main.py                 # 命令行入口
└── 启动系统.bat            # 一键启动脚本
```

## API 文档

后端 API 文档访问：http://localhost:9010/docs

### 主要接口

- `GET /api/health` - 健康检查
- `POST /api/tasks` - 创建任务
- `GET /api/tasks/{task_id}` - 获取任务详情
- `WS /api/ws/{task_id}` - WebSocket 实时通知
- `POST /api/upload` - 文件上传
- `GET /api/materials` - 获取素材列表

## 配置说明

### API 密钥配置
编辑 `config/api_keys.yaml` 配置 LLM API 密钥：

```yaml
llm:
  provider: deepseek  # deepseek 或 aliyun
  api_key: your_api_key_here
```

### 默认参数配置
编辑 `config/defaults.yaml` 设置默认参数：

```yaml
tts:
  speed: 1.0
  denoise: false
video:
  resolution: 1920x1080
  fps: 30
```

## 开发指南

### 后端开发
```bash
cd backend
python -m pytest tests/
```

### 前端开发
```bash
cd frontend
npm run test
npm run build
```

## 许可证

本项目仅供学习和研究使用。

## 联系方式

- 项目地址: https://github.com/Eikwang/AUTOavantar
