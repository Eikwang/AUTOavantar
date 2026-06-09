"""
检查点数据模型
用于任务断点续传功能
"""

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any
from datetime import datetime
import json


@dataclass
class TagGroupCheckpoint:
    """标签组检查点"""
    tone: str
    audio_completed: bool = False
    video_completed: bool = False
    audio_paths: Dict[str, Optional[str]] = field(default_factory=dict)
    video_path: Optional[str] = None
    error_message: Optional[str] = None
    intermediate_files: List[str] = field(default_factory=list)


@dataclass
class CheckpointData:
    """
    任务检查点数据
    
    按标签组保存进度，支持从失败标签组恢复
    """
    task_id: str
    current_stage: str = "pending"
    current_tone_index: int = 0
    tag_groups: List[TagGroupCheckpoint] = field(default_factory=list)
    completed_segments: List[str] = field(default_factory=list)
    failed_tone: Optional[str] = None
    error_message: Optional[str] = None
    audio_paths: Dict[str, Optional[str]] = field(default_factory=dict)
    video_paths: Dict[str, Optional[str]] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    segments_data: List[Dict] = field(default_factory=list)
    
    source_video_path: Optional[str] = None
    prompt_audio_path: Optional[str] = None
    left_prompt_audio_path: Optional[str] = None
    right_prompt_audio_path: Optional[str] = None
    bgm_path: Optional[str] = None
    opening_video: Optional[str] = None
    loop_videos: Optional[List[str]] = field(default_factory=list)
    scene_videos: Optional[List[str]] = field(default_factory=list)
    ending_video: Optional[str] = None
    
    double_mode_files: List[str] = field(default_factory=list)
    subtitle_path: Optional[str] = None
    pip_speaker_videos: Optional[Dict[str, Any]] = None
    scene_pip_left_video: Optional[str] = None
    scene_pip_right_video: Optional[str] = None
    scene_pip_processed: Optional[List[str]] = None

    def to_json(self) -> str:
        """序列化为 JSON 字符串"""
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)
    
    @classmethod
    def from_json(cls, json_str: str) -> 'CheckpointData':
        """从 JSON 字符串反序列化"""
        data = json.loads(json_str)
        tag_groups = [
            TagGroupCheckpoint(**tg) for tg in data.get('tag_groups', [])
        ]
        return cls(
            task_id=data.get('task_id', ''),
            current_stage=data.get('current_stage', 'pending'),
            current_tone_index=data.get('current_tone_index', 0),
            tag_groups=tag_groups,
            completed_segments=data.get('completed_segments', []),
            failed_tone=data.get('failed_tone'),
            error_message=data.get('error_message'),
            audio_paths=data.get('audio_paths', {}),
            video_paths=data.get('video_paths', {}),
            created_at=data.get('created_at', datetime.now().isoformat()),
            updated_at=data.get('updated_at', datetime.now().isoformat()),
            segments_data=data.get('segments_data', []),
            source_video_path=data.get('source_video_path'),
            prompt_audio_path=data.get('prompt_audio_path'),
            left_prompt_audio_path=data.get('left_prompt_audio_path'),
            right_prompt_audio_path=data.get('right_prompt_audio_path'),
            bgm_path=data.get('bgm_path'),
            opening_video=data.get('opening_video'),
            loop_videos=data.get('loop_videos', []),
            scene_videos=data.get('scene_videos', []),
            ending_video=data.get('ending_video'),
            double_mode_files=data.get('double_mode_files', []),
            subtitle_path=data.get('subtitle_path'),
            pip_speaker_videos=data.get('pip_speaker_videos'),
            scene_pip_left_video=data.get('scene_pip_left_video'),
            scene_pip_right_video=data.get('scene_pip_right_video'),
            scene_pip_processed=data.get('scene_pip_processed')
        )
    
    def update_stage(self, stage: str):
        """更新当前阶段"""
        self.current_stage = stage
        self.updated_at = datetime.now().isoformat()
    
    def mark_audio_completed(self, tone: str, audio_paths: Dict[str, Optional[str]]):
        """标记标签组音频完成"""
        for tg in self.tag_groups:
            if tg.tone == tone:
                tg.audio_completed = True
                tg.audio_paths = audio_paths
                self.updated_at = datetime.now().isoformat()
                break
    
    def mark_video_completed(self, tone: str, video_path: str):
        """标记标签组视频完成"""
        for tg in self.tag_groups:
            if tg.tone == tone:
                tg.video_completed = True
                tg.video_path = video_path
                self.updated_at = datetime.now().isoformat()
                break
    
    def mark_tone_failed(self, tone: str, error_message: str):
        """标记标签组失败"""
        self.failed_tone = tone
        self.error_message = error_message
        for tg in self.tag_groups:
            if tg.tone == tone:
                tg.error_message = error_message
                self.updated_at = datetime.now().isoformat()
                break
    
    def get_resume_point(self) -> Optional[TagGroupCheckpoint]:
        """获取恢复点（失败的标签组）"""
        if self.failed_tone:
            for tg in self.tag_groups:
                if tg.tone == self.failed_tone:
                    return tg
        return None
    
    def get_next_pending_tone(self) -> Optional[TagGroupCheckpoint]:
        """获取下一个待处理的标签组"""
        for tg in self.tag_groups:
            if not tg.audio_completed or not tg.video_completed:
                return tg
        return None
    
    def is_completed(self) -> bool:
        """检查是否全部完成"""
        return all(
            tg.audio_completed and tg.video_completed 
            for tg in self.tag_groups
        )
    
    def get_progress(self) -> float:
        """计算进度百分比"""
        if not self.tag_groups:
            return 0.0
        completed = sum(
            1 for tg in self.tag_groups 
            if tg.audio_completed and tg.video_completed
        )
        return completed / len(self.tag_groups) * 100


def serialize_segments(segments: List[Any]) -> List[Dict]:
    """
    将 ScriptSegment 列表序列化为可 JSON 化的字典列表
    
    Args:
        segments: ScriptSegment 对象列表
        
    Returns:
        可 JSON 序列化的字典列表
    """
    result = []
    for seg in segments:
        seg_dict = {
            'segment_id': seg.segment_id,
            'text': seg.text,
            'scene_type': seg.scene_type.value if hasattr(seg.scene_type, 'value') else str(seg.scene_type),
            'emotion': seg.emotion.value if hasattr(seg.emotion, 'value') else str(seg.emotion),
            'tone': seg.tone,
            'emotion_weight': seg.emotion_weight,
            'tone_weight': getattr(seg, 'tone_weight', 0.2),
            'audio_path': seg.audio_path,
            'video_path': getattr(seg, 'video_path', None),
            'output_path': seg.output_path,
            'duration': getattr(seg, 'duration', 0.0),
            'status': getattr(seg, 'status', 'pending'),
            'audio_duration': getattr(seg, 'audio_duration', 0.0),
            'speaker': getattr(seg, 'speaker', ''),
            'is_scene_label': getattr(seg, 'is_scene_label', False),
            'pending_speaker_video': getattr(seg, 'pending_speaker_video', None),
            'scene_video_path': getattr(seg, 'scene_video_path', None),
            'need_pip_overlay': getattr(seg, 'need_pip_overlay', False),
        }
        result.append(seg_dict)
    return result


def deserialize_segments(data: List[Dict]) -> List[Any]:
    """
    从字典列表反序列化为 ScriptSegment 对象列表
    
    Args:
        data: 字典列表
        
    Returns:
        ScriptSegment 对象列表
    """
    from core.models.task import ScriptSegment, SceneType, EmotionType
    
    result = []
    for item in data:
        scene_type_str = item.get('scene_type', '开场')
        emotion_str = item.get('emotion', '平静')
        
        try:
            scene_type = SceneType(scene_type_str)
        except ValueError:
            scene_type = SceneType.OPENING
        
        try:
            emotion = EmotionType(emotion_str)
        except ValueError:
            emotion = EmotionType.CALM
        
        segment = ScriptSegment(
            segment_id=item.get('segment_id', ''),
            text=item.get('text', ''),
            scene_type=scene_type,
            emotion=emotion,
            tone=item.get('tone'),
            emotion_weight=item.get('emotion_weight', 0.3),
            tone_weight=item.get('tone_weight', 0.2),
            audio_path=item.get('audio_path'),
            video_path=item.get('video_path'),
            output_path=item.get('output_path'),
            duration=item.get('duration', 0.0),
            status=item.get('status', 'pending'),
            audio_duration=item.get('audio_duration', 0.0),
            speaker=item.get('speaker', ''),
            is_scene_label=item.get('is_scene_label', False),
            pending_speaker_video=item.get('pending_speaker_video'),
            scene_video_path=item.get('scene_video_path'),
            need_pip_overlay=item.get('need_pip_overlay', False),
        )
        result.append(segment)
    return result
