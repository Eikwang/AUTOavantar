"""
数据库服务层
提供异步数据库操作，支持任务、素材等数据管理（已移除用户认证功能）
"""

import aiosqlite
import json
import logging
import os
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
from contextlib import asynccontextmanager

logger = logging.getLogger("database_service")

DATABASE_DIR = "data"
DATABASE_PATH = os.path.join(DATABASE_DIR, "app.db")


class DatabaseService:
    """异步数据库服务"""

    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = db_path
        self._connection: Optional[aiosqlite.Connection] = None

        os.makedirs(os.path.dirname(db_path), exist_ok=True)

    async def initialize(self):
        """初始化数据库连接和表结构"""
        await self._init_database()
        logger.info(f"数据库初始化完成: {self.db_path}")

    async def close(self):
        """关闭数据库连接"""
        if self._connection:
            await self._connection.close()
            self._connection = None
            logger.info("数据库连接已关闭")

    async def _get_connection(self) -> aiosqlite.Connection:
        """获取数据库连接"""
        if self._connection is None:
            self._connection = await aiosqlite.connect(self.db_path)
            self._connection.row_factory = aiosqlite.Row
            await self._connection.execute("PRAGMA foreign_keys = ON")
        return self._connection

    @asynccontextmanager
    async def get_connection(self):
        """获取数据库连接的上下文管理器"""
        conn = await self._get_connection()
        try:
            yield conn
        except Exception as e:
            logger.error(f"数据库操作失败: {e}")
            raise

    async def _init_database(self):
        """初始化数据库表结构"""
        conn = await self._get_connection()
        cursor = await conn.cursor()

        await cursor.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id VARCHAR(50) UNIQUE NOT NULL,
                name VARCHAR(200) NOT NULL,
                status VARCHAR(50) NOT NULL,
                progress FLOAT DEFAULT 0.0,
                current_stage VARCHAR(100),
                source_video_path VARCHAR(500),
                script_text TEXT,
                topic VARCHAR(500),
                config TEXT,
                output_path VARCHAR(500),
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                prompt_audio_path VARCHAR(500),
                left_prompt_audio_path VARCHAR(500),
                right_prompt_audio_path VARCHAR(500),
                bgm_path VARCHAR(500),
                use_llm_generate BOOLEAN DEFAULT 0,
                enable_postprocess BOOLEAN DEFAULT 1,
                opening_video TEXT,
                loop_videos TEXT,
                scene_videos TEXT,
                ending_video TEXT,
                opening_video_with_tags TEXT,
                loop_videos_with_tags TEXT,
                scene_videos_with_tags TEXT,
                ending_video_with_tags TEXT,
                checkpoint_data TEXT
            )
        """)

        # 为现有表添加新列（如果不存在）
        try:
            await cursor.execute("ALTER TABLE tasks ADD COLUMN prompt_audio_path VARCHAR(500)")
        except Exception:
            pass
        try:
            await cursor.execute("ALTER TABLE tasks ADD COLUMN left_prompt_audio_path VARCHAR(500)")
        except Exception:
            pass
        try:
            await cursor.execute("ALTER TABLE tasks ADD COLUMN right_prompt_audio_path VARCHAR(500)")
        except Exception:
            pass
        try:
            await cursor.execute("ALTER TABLE tasks ADD COLUMN bgm_path VARCHAR(500)")
        except Exception:
            pass
        try:
            await cursor.execute("ALTER TABLE tasks ADD COLUMN use_llm_generate BOOLEAN DEFAULT 0")
        except Exception:
            pass
        try:
            await cursor.execute("ALTER TABLE tasks ADD COLUMN enable_postprocess BOOLEAN DEFAULT 1")
        except Exception:
            pass
        try:
            await cursor.execute("ALTER TABLE tasks ADD COLUMN opening_video TEXT")
        except Exception:
            pass
        try:
            await cursor.execute("ALTER TABLE tasks ADD COLUMN loop_videos TEXT")
        except Exception:
            pass
        try:
            await cursor.execute("ALTER TABLE tasks ADD COLUMN scene_videos TEXT")
        except Exception:
            pass
        try:
            await cursor.execute("ALTER TABLE tasks ADD COLUMN ending_video TEXT")
        except Exception:
            pass
        try:
            await cursor.execute("ALTER TABLE tasks ADD COLUMN opening_video_with_tags TEXT")
        except Exception:
            pass
        try:
            await cursor.execute("ALTER TABLE tasks ADD COLUMN loop_videos_with_tags TEXT")
        except Exception:
            pass
        try:
            await cursor.execute("ALTER TABLE tasks ADD COLUMN scene_videos_with_tags TEXT")
        except Exception:
            pass
        try:
            await cursor.execute("ALTER TABLE tasks ADD COLUMN ending_video_with_tags TEXT")
        except Exception:
            pass
        try:
            await cursor.execute("ALTER TABLE tasks ADD COLUMN checkpoint_data TEXT")
        except Exception:
            pass

        await cursor.execute("""
            CREATE TABLE IF NOT EXISTS task_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id VARCHAR(50) NOT NULL,
                stage VARCHAR(50),
                status VARCHAR(50),
                message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
            )
        """)

        await cursor.execute("""
            CREATE TABLE IF NOT EXISTS materials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                material_id VARCHAR(50) UNIQUE NOT NULL,
                material_type VARCHAR(50) NOT NULL,
                name VARCHAR(200) NOT NULL,
                file_path VARCHAR(500),
                description TEXT,
                metadata TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
        await cursor.execute("CREATE INDEX IF NOT EXISTS idx_history_task ON task_history(task_id)")

        # 文案生成历史记录表
        await cursor.execute("""
            CREATE TABLE IF NOT EXISTS script_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_input VARCHAR(500) NOT NULL,
                script_content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await cursor.execute("CREATE INDEX IF NOT EXISTS idx_script_history_created ON script_history(created_at DESC)")

        # 智能裁剪任务表
        await cursor.execute("""
            CREATE TABLE IF NOT EXISTS smart_cut_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id VARCHAR(64) UNIQUE NOT NULL,
                video_path VARCHAR(512) NOT NULL,
                video_name VARCHAR(256),
                video_duration FLOAT,
                video_fps FLOAT,
                video_width INTEGER,
                video_height INTEGER,
                total_frames INTEGER,
                status VARCHAR(32) DEFAULT 'pending',
                progress INTEGER DEFAULT 0,
                current_stage VARCHAR(64),
                config TEXT,
                segments_info TEXT,
                error_message TEXT,
                thumbnail TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await cursor.execute("CREATE INDEX IF NOT EXISTS idx_smart_cut_task_id ON smart_cut_tasks(task_id)")
        await cursor.execute("CREATE INDEX IF NOT EXISTS idx_smart_cut_status ON smart_cut_tasks(status)")

        # 迁移：为已有数据库添加 thumbnail 列
        try:
            await cursor.execute("ALTER TABLE smart_cut_tasks ADD COLUMN thumbnail TEXT")
        except Exception:
            pass  # 列已存在则忽略

        await self._init_tag_tables(conn)

        await conn.commit()
        logger.info("数据库表结构初始化完成")

    async def _init_tag_tables(self, conn: aiosqlite.Connection):
        """初始化标签组表"""
        cursor = await conn.cursor()

        await cursor.execute("""
            CREATE TABLE IF NOT EXISTS tag_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                type TEXT NOT NULL DEFAULT 'scene',
                is_default INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await cursor.execute("""
            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER,
                name TEXT NOT NULL,
                similar_tags TEXT,
                vec1 REAL DEFAULT 0,
                vec2 REAL DEFAULT 0,
                vec3 REAL DEFAULT 0,
                vec4 REAL DEFAULT 0,
                vec5 REAL DEFAULT 0,
                vec6 REAL DEFAULT 0,
                vec7 REAL DEFAULT 0,
                vec8 REAL DEFAULT 0,
                speed REAL DEFAULT 1.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (group_id) REFERENCES tag_groups(id) ON DELETE CASCADE
            )
        """)

        await cursor.execute("CREATE INDEX IF NOT EXISTS idx_tags_group ON tags(group_id)")
        # 情绪标签间 name 唯一 (group_id IS NULL)
        await cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tags_emotion_name ON tags(name) WHERE group_id IS NULL")
        # 同一标签组内 name 唯一 (group_id IS NOT NULL)
        await cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tags_group_name ON tags(group_id, name) WHERE group_id IS NOT NULL")

        await self._migrate_tags_unique_constraint(conn)

        await self._init_default_tag_group(conn)

        logger.info("标签组表初始化完成")

    async def _migrate_tags_unique_constraint(self, conn: aiosqlite.Connection):
        """迁移 tags 表的 UNIQUE 约束：从 name 全局唯一改为分组唯一"""
        cursor = await conn.cursor()

        # 检查 tags 表是否存在旧的 name UNIQUE 约束
        await cursor.execute("PRAGMA index_list(tags)")
        indexes = await cursor.fetchall()

        has_name_unique = False
        for idx in indexes:
            if idx['unique'] == 1:
                await cursor.execute(f"PRAGMA index_info('{idx['name']}')")
                cols = await cursor.fetchall()
                col_names = [c['name'] for c in cols]
                if col_names == ['name']:
                    has_name_unique = True
                    break

        if not has_name_unique:
            return  # 已经是新约束，无需迁移

        logger.info("迁移 tags 表 UNIQUE 约束: name 全局唯一 -> 分组唯一")

        # SQLite 不支持 ALTER TABLE 修改约束，需要重建表
        await cursor.execute("""
            CREATE TABLE IF NOT EXISTS tags_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER,
                name TEXT NOT NULL,
                similar_tags TEXT,
                vec1 REAL DEFAULT 0,
                vec2 REAL DEFAULT 0,
                vec3 REAL DEFAULT 0,
                vec4 REAL DEFAULT 0,
                vec5 REAL DEFAULT 0,
                vec6 REAL DEFAULT 0,
                vec7 REAL DEFAULT 0,
                vec8 REAL DEFAULT 0,
                speed REAL DEFAULT 1.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (group_id) REFERENCES tag_groups(id) ON DELETE CASCADE
            )
        """)

        await cursor.execute("""
            INSERT OR IGNORE INTO tags_new
            SELECT id, group_id, name, similar_tags, vec1, vec2, vec3, vec4, vec5, vec6, vec7, vec8, speed, created_at, updated_at
            FROM tags
        """)

        await cursor.execute("DROP TABLE tags")
        await cursor.execute("ALTER TABLE tags_new RENAME TO tags")
        await cursor.execute("CREATE INDEX IF NOT EXISTS idx_tags_group ON tags(group_id)")
        await cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tags_emotion_name ON tags(name) WHERE group_id IS NULL")
        await cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tags_group_name ON tags(group_id, name) WHERE group_id IS NOT NULL")

        await conn.commit()
        logger.info("tags 表 UNIQUE 约束迁移完成")

    async def _init_default_tag_group(self, conn: aiosqlite.Connection):
        """初始化默认产品介绍标签组"""
        cursor = await conn.cursor()

        await cursor.execute(
            "SELECT id FROM tag_groups WHERE name = '产品介绍'"
        )
        existing = await cursor.fetchone()

        if existing is None:
            await cursor.execute(
                "INSERT INTO tag_groups (name, type, is_default) VALUES ('产品介绍', 'scene', 1)"
            )

            await cursor.execute("SELECT last_insert_rowid()")
            result = await cursor.fetchone()
            group_id = result[0]

            default_tags = [
                ("环境展示", ["产品展示", "细节展示"]),
                ("产品展示", ["功能介绍", "使用效果"]),
                ("细节展示", ["产品展示", "功能介绍"]),
                ("功能介绍", ["细节展示", "使用效果"]),
                ("使用效果", ["产品展示", "功能介绍"]),
            ]

            for name, similar in default_tags:
                similar_json = json.dumps(similar, ensure_ascii=False)
                await cursor.execute(
                    "INSERT INTO tags (group_id, name, similar_tags) VALUES (?, ?, ?)",
                    (group_id, name, similar_json)
                )

            logger.info("默认产品介绍标签组初始化完成")

    async def task_create(
        self,
        task_id: str,
        name: str,
        status: str = "pending",
        source_video_path: str = "",
        script_text: str = "",
        topic: str = "",
        config: Optional[Dict[str, Any]] = None,
        output_path: str = "",
        current_stage: str = "",
        prompt_audio_path: str = "",
        left_prompt_audio_path: str = "",
        right_prompt_audio_path: str = "",
        bgm_path: str = "",
        use_llm_generate: bool = False,
        enable_postprocess: bool = True,
        opening_video: Optional[str] = None,
        loop_videos: Optional[List[str]] = None,
        scene_videos: Optional[List[str]] = None,
        ending_video: Optional[str] = None,
        opening_video_with_tags: Optional[Dict] = None,
        loop_videos_with_tags: Optional[List[Dict]] = None,
        scene_videos_with_tags: Optional[List[Dict]] = None,
        ending_video_with_tags: Optional[Dict] = None
    ) -> int:
        """创建任务"""
        async with self.get_connection() as conn:
            cursor = await conn.cursor()
            now = datetime.now().isoformat()

            await cursor.execute("""
                INSERT INTO tasks (
                    task_id, name, status, progress, current_stage,
                    source_video_path, script_text, topic, config,
                    output_path, error_message, created_at, updated_at,
                    prompt_audio_path, left_prompt_audio_path, right_prompt_audio_path,
                    bgm_path, use_llm_generate, enable_postprocess,
                    opening_video, loop_videos, scene_videos, ending_video,
                    opening_video_with_tags, loop_videos_with_tags,
                    scene_videos_with_tags, ending_video_with_tags,
                    checkpoint_data
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                task_id, name, status, 0.0, current_stage,
                source_video_path, script_text, topic,
                json.dumps(config) if config else None,
                output_path, None, now, now,
                prompt_audio_path, left_prompt_audio_path, right_prompt_audio_path,
                bgm_path, 1 if use_llm_generate else 0, 1 if enable_postprocess else 0,
                opening_video,
                json.dumps(loop_videos) if loop_videos else None,
                json.dumps(scene_videos) if scene_videos else None,
                ending_video,
                json.dumps(opening_video_with_tags) if opening_video_with_tags else None,
                json.dumps(loop_videos_with_tags) if loop_videos_with_tags else None,
                json.dumps(scene_videos_with_tags) if scene_videos_with_tags else None,
                json.dumps(ending_video_with_tags) if ending_video_with_tags else None,
                None
            ))

            await conn.commit()
            task_db_id = cursor.lastrowid

            await self.history_add(task_id, "创建任务", status, f"任务 {name} 已创建")

            logger.info(f"任务创建成功: {task_id}")
            return task_db_id

    async def task_get_by_id(self, task_id: str) -> Optional[Dict[str, Any]]:
        """根据task_id获取任务"""
        async with self.get_connection() as conn:
            cursor = await conn.cursor()
            await cursor.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
            row = await cursor.fetchone()

            if row:
                return dict(row)
            return None

    async def task_update(
        self,
        task_id: str,
        status: Optional[str] = None,
        progress: Optional[float] = None,
        current_stage: Optional[str] = None,
        output_path: Optional[str] = None,
        error_message: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        script_text: Optional[str] = None,
        topic: Optional[str] = None,
        checkpoint_data: Optional[str] = None
    ) -> bool:
        """更新任务信息"""
        async with self.get_connection() as conn:
            cursor = await conn.cursor()
            now = datetime.now().isoformat()

            updates = []
            values = []

            if status is not None:
                updates.append("status = ?")
                values.append(status)
            if progress is not None:
                updates.append("progress = ?")
                values.append(progress)
            if current_stage is not None:
                updates.append("current_stage = ?")
                values.append(current_stage)
            if output_path is not None:
                updates.append("output_path = ?")
                values.append(output_path)
            if error_message is not None:
                updates.append("error_message = ?")
                values.append(error_message)
            if config is not None:
                updates.append("config = ?")
                values.append(json.dumps(config))
            if script_text is not None:
                updates.append("script_text = ?")
                values.append(script_text)
            if topic is not None:
                updates.append("topic = ?")
                values.append(topic)
            if checkpoint_data is not None:
                updates.append("checkpoint_data = ?")
                values.append(checkpoint_data)

            if not updates:
                return False

            if status == "completed":
                updates.append("completed_at = ?")
                values.append(now)

            updates.append("updated_at = ?")
            values.append(now)
            values.append(task_id)

            await cursor.execute(
                f"UPDATE tasks SET {', '.join(updates)} WHERE task_id = ?",
                values
            )
            await conn.commit()

            if cursor.rowcount > 0:
                logger.info(f"任务更新成功: {task_id}")
                return True
            return False

    async def task_delete(self, task_id: str) -> bool:
        """删除任务"""
        async with self.get_connection() as conn:
            cursor = await conn.cursor()
            await cursor.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
            await conn.commit()

            if cursor.rowcount > 0:
                logger.info(f"任务删除成功: {task_id}")
                return True
            return False

    async def task_list(
        self,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> Tuple[List[Dict[str, Any]], int]:
        """获取任务列表"""
        async with self.get_connection() as conn:
            cursor = await conn.cursor()

            # 获取总数
            if status:
                await cursor.execute("SELECT COUNT(*) FROM tasks WHERE status = ?", (status,))
            else:
                await cursor.execute("SELECT COUNT(*) FROM tasks")
            total = (await cursor.fetchone())[0]

            # 获取分页数据
            if status:
                await cursor.execute(
                    """SELECT * FROM tasks WHERE status = ?
                       ORDER BY created_at DESC LIMIT ? OFFSET ?""",
                    (status, limit, offset)
                )
            else:
                await cursor.execute(
                    """SELECT * FROM tasks
                       ORDER BY created_at DESC LIMIT ? OFFSET ?""",
                    (limit, offset)
                )

            rows = await cursor.fetchall()
            return [dict(row) for row in rows], total

    async def task_get_incomplete(self) -> List[Dict[str, Any]]:
        """获取未完成的任务（用于断点续传）"""
        async with self.get_connection() as conn:
            cursor = await conn.cursor()
            await cursor.execute(
                """SELECT * FROM tasks
                   WHERE status NOT IN ('completed', 'failed', 'cancelled')
                   ORDER BY created_at ASC"""
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def checkpoint_save(self, task_id: str, checkpoint_data: str) -> bool:
        """
        保存任务检查点
        
        Args:
            task_id: 任务ID
            checkpoint_data: 检查点数据（JSON字符串）
            
        Returns:
            是否保存成功
        """
        async with self.get_connection() as conn:
            cursor = await conn.cursor()
            now = datetime.now().isoformat()
            
            await cursor.execute(
                """UPDATE tasks 
                   SET checkpoint_data = ?, updated_at = ? 
                   WHERE task_id = ?""",
                (checkpoint_data, now, task_id)
            )
            await conn.commit()
            
            if cursor.rowcount > 0:
                logger.info(f"检查点保存成功: {task_id}")
                return True
            return False

    async def checkpoint_load(self, task_id: str) -> Optional[str]:
        """
        加载任务检查点
        
        Args:
            task_id: 任务ID
            
        Returns:
            检查点数据（JSON字符串），如果没有则返回 None
        """
        async with self.get_connection() as conn:
            cursor = await conn.cursor()
            await cursor.execute(
                "SELECT checkpoint_data FROM tasks WHERE task_id = ?",
                (task_id,)
            )
            row = await cursor.fetchone()
            
            if row and row['checkpoint_data']:
                logger.info(f"检查点加载成功: {task_id}")
                return row['checkpoint_data']
            return None

    async def checkpoint_clear(self, task_id: str) -> bool:
        """
        清除任务检查点（任务完成后调用）
        
        Args:
            task_id: 任务ID
            
        Returns:
            是否清除成功
        """
        async with self.get_connection() as conn:
            cursor = await conn.cursor()
            
            await cursor.execute(
                "UPDATE tasks SET checkpoint_data = NULL WHERE task_id = ?",
                (task_id,)
            )
            await conn.commit()
            
            if cursor.rowcount > 0:
                logger.info(f"检查点清除成功: {task_id}")
                return True
            return False

    async def task_get_stats(self) -> Dict[str, Any]:
        """获取任务统计信息"""
        async with self.get_connection() as conn:
            cursor = await conn.cursor()

            # 总任务数
            await cursor.execute("SELECT COUNT(*) FROM tasks")
            total = (await cursor.fetchone())[0]

            # 各状态数量
            await cursor.execute(
                """SELECT status, COUNT(*) FROM tasks GROUP BY status"""
            )
            status_counts = {row[0]: row[1] for row in await cursor.fetchall()}

            # 今日任务
            today = datetime.now().strftime("%Y-%m-%d")
            await cursor.execute(
                """SELECT COUNT(*) FROM tasks WHERE date(created_at) = ?""",
                (today,)
            )
            today_count = (await cursor.fetchone())[0]

            return {
                "total": total,
                "pending": status_counts.get("pending", 0),
                "processing": status_counts.get("processing", 0),
                "completed": status_counts.get("completed", 0),
                "failed": status_counts.get("failed", 0),
                "today": today_count
            }

    async def history_add(
        self,
        task_id: str,
        stage: str,
        status: str,
        message: str
    ) -> int:
        """添加任务历史记录"""
        async with self.get_connection() as conn:
            cursor = await conn.cursor()
            now = datetime.now().isoformat()

            await cursor.execute("""
                INSERT INTO task_history (task_id, stage, status, message, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (task_id, stage, status, message, now))

            await conn.commit()
            return cursor.lastrowid

    async def history_get_by_task(self, task_id: str) -> List[Dict[str, Any]]:
        """获取任务的历史记录"""
        async with self.get_connection() as conn:
            cursor = await conn.cursor()
            await cursor.execute(
                """SELECT * FROM task_history WHERE task_id = ?
                   ORDER BY created_at ASC""",
                (task_id,)
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def material_create(
        self,
        material_id: str,
        material_type: str,
        name: str,
        file_path: str = "",
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """创建素材"""
        async with self.get_connection() as conn:
            cursor = await conn.cursor()
            now = datetime.now().isoformat()

            await cursor.execute("""
                INSERT INTO materials (
                    material_id, material_type, name, file_path,
                    description, metadata, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                material_id, material_type, name, file_path,
                description, json.dumps(metadata) if metadata else None, now
            ))

            await conn.commit()
            logger.info(f"素材创建成功: {material_id}")
            return cursor.lastrowid

    async def material_get_by_id(self, material_id: str) -> Optional[Dict[str, Any]]:
        """根据material_id获取素材"""
        async with self.get_connection() as conn:
            cursor = await conn.cursor()
            await cursor.execute(
                "SELECT * FROM materials WHERE material_id = ?",
                (material_id,)
            )
            row = await cursor.fetchone()

            if row:
                return dict(row)
            return None

    async def material_delete(self, material_id: str) -> bool:
        """删除素材"""
        async with self.get_connection() as conn:
            cursor = await conn.cursor()
            await cursor.execute(
                "DELETE FROM materials WHERE material_id = ?",
                (material_id,)
            )
            await conn.commit()

            if cursor.rowcount > 0:
                logger.info(f"素材删除成功: {material_id}")
                return True
            return False

    async def material_list(
        self,
        material_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> Tuple[List[Dict[str, Any]], int]:
        """获取素材列表"""
        async with self.get_connection() as conn:
            cursor = await conn.cursor()

            # 获取总数
            if material_type:
                await cursor.execute(
                    "SELECT COUNT(*) FROM materials WHERE material_type = ?",
                    (material_type,)
                )
            else:
                await cursor.execute("SELECT COUNT(*) FROM materials")
            total = (await cursor.fetchone())[0]

            # 获取分页数据
            if material_type:
                await cursor.execute(
                    """SELECT * FROM materials WHERE material_type = ?
                       ORDER BY created_at DESC LIMIT ? OFFSET ?""",
                    (material_type, limit, offset)
                )
            else:
                await cursor.execute(
                    """SELECT * FROM materials
                       ORDER BY created_at DESC LIMIT ? OFFSET ?""",
                    (limit, offset)
                )

            rows = await cursor.fetchall()
            return [dict(row) for row in rows], total

    # ==================== 智能裁剪任务相关方法 ====================

    async def smart_cut_task_create(
        self,
        task_id: str,
        video_path: str,
        video_name: str = "",
        video_duration: float = 0.0,
        video_fps: float = 0.0,
        video_width: int = 0,
        video_height: int = 0,
        total_frames: int = 0,
        config: Optional[Dict[str, Any]] = None,
        status: str = "pending",
        thumbnail: Optional[str] = None
    ) -> int:
        """创建智能裁剪任务"""
        async with self.get_connection() as conn:
            cursor = await conn.cursor()
            now = datetime.now().isoformat()

            await cursor.execute("""
                INSERT INTO smart_cut_tasks (
                    task_id, video_path, video_name, video_duration, video_fps,
                    video_width, video_height, total_frames, status, progress,
                    current_stage, config, thumbnail, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, '', ?, ?, ?, ?)
            """, (
                task_id, video_path, video_name, video_duration, video_fps,
                video_width, video_height, total_frames, status,
                json.dumps(config) if config else None,
                thumbnail, now, now
            ))

            await conn.commit()
            logger.info(f"智能裁剪任务创建成功: {task_id}, 状态: {status}")
            return cursor.lastrowid

    async def smart_cut_task_get_by_id(self, task_id: str) -> Optional[Dict[str, Any]]:
        """根据task_id获取智能裁剪任务"""
        async with self.get_connection() as conn:
            cursor = await conn.cursor()
            await cursor.execute(
                "SELECT * FROM smart_cut_tasks WHERE task_id = ?",
                (task_id,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def smart_cut_task_update(
        self,
        task_id: str,
        updates: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> bool:
        """更新智能裁剪任务

        Args:
            task_id: 任务ID
            updates: 更新字段字典，支持 status, progress, current_stage, segments_info, error_message
            **kwargs: 也可以直接传递字段名作为关键字参数
        """
        # 合并字典参数和关键字参数
        if updates is None:
            updates = kwargs

        async with self.get_connection() as conn:
            cursor = await conn.cursor()
            now = datetime.now().isoformat()

            update_parts = []
            values = []

            # 支持的字段
            field_mapping = {
                "status": "status",
                "progress": "progress",
                "current_stage": "current_stage",
                "segments_info": "segments_info",
                "error_message": "error_message",
                "config": "config",
                "thumbnail": "thumbnail",
                "video_name": "video_name",
                "video_duration": "video_duration"
            }

            for key, column in field_mapping.items():
                if key in updates and updates[key] is not None:
                    update_parts.append(f"{column} = ?")
                    # segments_info 和 config 需要序列化为 JSON
                    if key in ("segments_info", "config") and not isinstance(updates[key], str):
                        values.append(json.dumps(updates[key], ensure_ascii=False))
                    else:
                        values.append(updates[key])

            if not update_parts:
                return False

            update_parts.append("updated_at = ?")
            values.append(now)
            values.append(task_id)

            await cursor.execute(
                f"UPDATE smart_cut_tasks SET {', '.join(update_parts)} WHERE task_id = ?",
                values
            )
            await conn.commit()

            if cursor.rowcount > 0:
                logger.info(f"智能裁剪任务更新成功: {task_id}")
                return True
            return False

    async def smart_cut_task_delete(self, task_id: str) -> bool:
        """删除智能裁剪任务"""
        async with self.get_connection() as conn:
            cursor = await conn.cursor()
            await cursor.execute(
                "DELETE FROM smart_cut_tasks WHERE task_id = ?",
                (task_id,)
            )
            await conn.commit()

            if cursor.rowcount > 0:
                logger.info(f"智能裁剪任务删除成功: {task_id}")
                return True
            return False

    async def smart_cut_task_list(
        self,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> Tuple[List[Dict[str, Any]], int]:
        """获取智能裁剪任务列表"""
        async with self.get_connection() as conn:
            cursor = await conn.cursor()

            # 获取总数
            if status:
                await cursor.execute(
                    "SELECT COUNT(*) FROM smart_cut_tasks WHERE status = ?",
                    (status,)
                )
            else:
                await cursor.execute("SELECT COUNT(*) FROM smart_cut_tasks")
            total = (await cursor.fetchone())[0]

            # 获取分页数据
            if status:
                await cursor.execute(
                    """SELECT * FROM smart_cut_tasks WHERE status = ?
                       ORDER BY created_at DESC LIMIT ? OFFSET ?""",
                    (status, limit, offset)
                )
            else:
                await cursor.execute(
                    """SELECT * FROM smart_cut_tasks
                       ORDER BY created_at DESC LIMIT ? OFFSET ?""",
                    (limit, offset)
                )

            rows = await cursor.fetchall()
            return [dict(row) for row in rows], total

    async def smart_cut_task_get_processing(self) -> List[Dict[str, Any]]:
        """获取进行中的智能裁剪任务"""
        async with self.get_connection() as conn:
            cursor = await conn.cursor()
            await cursor.execute(
                """SELECT * FROM smart_cut_tasks
                   WHERE status IN ('pending', 'processing')
                   ORDER BY created_at ASC"""
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def smart_cut_task_get_by_video_path(self, video_path: str) -> Optional[Dict[str, Any]]:
        """根据视频路径获取智能裁剪任务（包括uploaded状态）"""
        async with self.get_connection() as conn:
            cursor = await conn.cursor()
            await cursor.execute(
                """SELECT * FROM smart_cut_tasks
                   WHERE video_path = ? AND status IN ('uploaded', 'pending', 'processing')
                   ORDER BY created_at DESC LIMIT 1""",
                (video_path,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    # ==================== 文案生成历史记录相关方法 ====================

    async def script_history_create(
        self,
        user_input: str,
        script_content: str
    ) -> int:
        """��建文案生成历史记录"""
        async with self.get_connection() as conn:
            cursor = await conn.cursor()
            now = datetime.now().isoformat()

            await cursor.execute("""
                INSERT INTO script_history (user_input, script_content, created_at)
                VALUES (?, ?, ?)
            """, (user_input, script_content, now))

            await conn.commit()
            logger.info(f"文案历史记录创建成功: user_input={user_input[:50]}...")
            return cursor.lastrowid

    async def script_history_list(
        self,
        limit: int = 100,
        offset: int = 0
    ) -> Tuple[List[Dict[str, Any]], int]:
        """获取文案生成历史记录列表"""
        async with self.get_connection() as conn:
            cursor = await conn.cursor()

            # 获取总数
            await cursor.execute("SELECT COUNT(*) FROM script_history")
            total = (await cursor.fetchone())[0]

            # 获取分页数据，按时间倒序
            await cursor.execute(
                """SELECT * FROM script_history
                   ORDER BY created_at DESC LIMIT ? OFFSET ?""",
                (limit, offset)
            )

            rows = await cursor.fetchall()
            return [dict(row) for row in rows], total

    async def script_history_delete(self, history_id: int) -> bool:
        """删除单条文案历史记录"""
        async with self.get_connection() as conn:
            cursor = await conn.cursor()
            await cursor.execute(
                "DELETE FROM script_history WHERE id = ?",
                (history_id,)
            )
            await conn.commit()

            if cursor.rowcount > 0:
                logger.info(f"文案历史记录删除成功: id={history_id}")
                return True
            return False

    async def script_history_clear(self) -> int:
        """清空所有文案历史记录"""
        async with self.get_connection() as conn:
            cursor = await conn.cursor()
            await cursor.execute("DELETE FROM script_history")
            await conn.commit()

            deleted_count = cursor.rowcount
            logger.info(f"文案历史记录已清空，共删除 {deleted_count} 条")
            return deleted_count


# 全局数据库服务实例
_database_service: Optional[DatabaseService] = None


async def init_database(db_path: str = DATABASE_PATH) -> DatabaseService:
    """初始化数据库"""
    global _database_service
    _database_service = DatabaseService(db_path)
    await _database_service.initialize()
    return _database_service


async def close_database():
    """关闭数据库"""
    global _database_service
    if _database_service:
        await _database_service.close()
        _database_service = None


def get_database_service() -> DatabaseService:
    """获取数据库服务实例"""
    global _database_service
    if _database_service is None:
        raise RuntimeError("数据库服务未初始化")
    return _database_service


async def get_database_service_async() -> DatabaseService:
    """获取数据库服务实例（异步版本）"""
    return get_database_service()
