"""
独立更新脚本
在 AUTOavantar.exe 退出后执行 git pull 并重启应用

使用方法:
    python tools/update_and_restart.py [--auto-start]

参数:
    --auto-start  更新完成后自动启动应用(默认行为)
    不传该参数时，更新完成后等待用户手动启动

该脚本由 desktop_launcher.py 在用户选择更新后启动，
作为独立进程运行，确保主进程可以正常退出。

更新源: Gitee 仓库 (https://gitee.com/astink/autoavantar.git)
"""

import platform
import subprocess
import sys
import os
import time
import json
from pathlib import Path


def get_app_dir() -> Path:
    """获取应用程序目录"""
    script_path = Path(__file__).resolve()
    # tools/update_and_restart.py -> ../../
    return script_path.parent.parent


def find_python() -> str:
    """查找 Python 解释器"""
    app_dir = get_app_dir()
    runtime_path = app_dir / "runtime" / "python.exe"
    if runtime_path.exists():
        return str(runtime_path)
    return "python"


def log(message: str):
    """打印日志并写入日志文件"""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] {message}"
    print(log_line, flush=True)

    # 写入日志文件
    try:
        log_dir = get_app_dir() / "backend" / "data"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "update.log"
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(log_line + '\n')
    except Exception:
        pass


def write_update_status(status: str, message: str = "", progress: int = 0):
    """
    写入更新状态文件，供外部程序或用户查看

    Args:
        status: 状态 - waiting / downloading / installing / success / failed
        message: 状态描述
        progress: 进度百分比 (0-100)
    """
    try:
        app_dir = get_app_dir()
        status_file = app_dir / ".update_status"
        status_data = {
            "status": status,
            "message": message,
            "progress": progress,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        status_file.write_text(json.dumps(status_data, ensure_ascii=False), encoding='utf-8')
    except Exception:
        pass


def clear_update_status():
    """清除更新状态文件"""
    try:
        status_file = get_app_dir() / ".update_status"
        if status_file.exists():
            status_file.unlink()
    except Exception:
        pass


def wait_for_process_exit(process_name: str, timeout: int = 30) -> bool:
    """
    等待进程退出

    Args:
        process_name: 进程名称（不区分大小写）
        timeout: 超时秒数

    Returns:
        True 表示进程已退出，False 表示超时
    """
    try:
        import psutil
        start_time = time.time()
        while time.time() - start_time < timeout:
            # 检查进程是否还在运行
            found = False
            for proc in psutil.process_iter(['name']):
                try:
                    if proc.info['name'] and process_name.lower() in proc.info['name'].lower():
                        found = True
                        break
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            if not found:
                return True
            time.sleep(1)
        return False
    except ImportError:
        # 没有 psutil，直接等待
        time.sleep(5)
        return True


def terminate_process(process_name: str) -> bool:
    """
    尝试终止指定进程

    Returns:
        True 表示成功终止或进程不存在，False 表示终止失败
    """
    try:
        import psutil
        terminated = False
        for proc in psutil.process_iter(['name', 'pid']):
            try:
                if proc.info['name'] and process_name.lower() in proc.info['name'].lower():
                    log(f"终止进程: {proc.info['name']} (PID: {proc.info['pid']})")
                    proc.terminate()
                    terminated = True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if terminated:
            # 等待进程退出
            gone, alive = psutil.wait_procs(
                [p for p in psutil.process_iter(['name']) if p.info.get('name', '').lower() == process_name.lower()],
                timeout=10
            )
            for p in alive:
                try:
                    p.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        return True
    except ImportError:
        # 没有 psutil，使用 taskkill
        if platform.system() == "Windows":
            try:
                subprocess.run(
                    ["taskkill", "/F", "/IM", process_name],
                    capture_output=True,
                    timeout=10,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                return True
            except Exception:
                return False
        return False


def execute_git_pull(app_dir: Path) -> tuple:
    """
    执行 git pull (从 Gitee 仓库更新)

    Returns:
        (success, message)
    """
    # 优先使用 runtime 中的 git，然后尝试系统 git
    git_paths = [
        app_dir / "runtime" / "git" / "bin" / "git.exe",
        app_dir / "runtime" / "git-cmd.exe",
        "git"
    ]

    git_exe = None
    for path in git_paths:
        if isinstance(path, Path):
            if path.exists():
                git_exe = str(path)
                break
        else:
            # 检查系统 git
            try:
                result = subprocess.run(
                    [path, "--version"],
                    capture_output=True,
                    timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
                )
                if result.returncode == 0:
                    git_exe = path
                    break
            except Exception:
                continue

    if not git_exe:
        return False, "未找到 git"

    log(f"使用 git: {git_exe}")
    write_update_status("downloading", "正在配置远程仓库...", 10)

    try:
        # 检查是否已配置 Gitee 远程仓库
        result = subprocess.run(
            [git_exe, "remote", "-v"],
            cwd=str(app_dir),
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
        )

        # 如果没有配置 remote 或 remote 不是 Gitee，则添加
        if "gitee.com/astink/autoavantar" not in result.stdout:
            log("配置 Gitee 远程仓库...")
            write_update_status("downloading", "正在配置远程仓库...", 15)
            # 移除可能存在的 origin
            subprocess.run(
                [git_exe, "remote", "remove", "origin"],
                cwd=str(app_dir),
                capture_output=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
            )
            # 添加 Gitee origin
            subprocess.run(
                [git_exe, "remote", "add", "origin", "https://gitee.com/astink/autoavantar.git"],
                cwd=str(app_dir),
                capture_output=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
            )

        # 执行 git fetch
        log("从 Gitee 获取更新...")
        write_update_status("downloading", "正在从服务器获取更新...", 30)
        result = subprocess.run(
            [git_exe, "fetch", "origin", "master"],
            cwd=str(app_dir),
            capture_output=True,
            text=True,
            timeout=120,
            creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
        )

        if result.returncode != 0:
            return False, f"git fetch 失败: {result.stderr}"

        # 执行 git reset --hard 强制更新到远程版本
        log("应用更新...")
        write_update_status("installing", "正在应用更新...", 70)
        result = subprocess.run(
            [git_exe, "reset", "--hard", "origin/master"],
            cwd=str(app_dir),
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
        )

        if result.returncode != 0:
            return False, f"git reset 失败: {result.stderr}"

        return True, "更新成功"

    except subprocess.TimeoutExpired:
        return False, "git 操作超时"
    except Exception as e:
        return False, f"git 操作异常: {e}"


def restart_application(app_dir: Path) -> bool:
    """
    重启应用

    优先尝试打包的 exe，其次尝试开发模式的 Python 启动

    Returns:
        True 表示成功启动，False 表示启动失败
    """
    # 方式1: 打包的 exe
    exe_path = app_dir / "AUTOavantar.exe"
    if exe_path.exists():
        try:
            subprocess.Popen(
                [str(exe_path)],
                cwd=str(app_dir),
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            )
            log(f"已启动新进程: {exe_path}")
            return True
        except Exception as e:
            log(f"启动 exe 失败: {e}")

    # 方式2: 开发模式 - 使用 Python 启动 desktop_launcher.py
    launcher_script = app_dir / "desktop_launcher.py"
    python_exe = find_python()
    if launcher_script.exists():
        try:
            subprocess.Popen(
                [python_exe, str(launcher_script)],
                cwd=str(app_dir),
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            )
            log(f"已启动新进程: {python_exe} {launcher_script}")
            return True
        except Exception as e:
            log(f"启动 Python 脚本失败: {e}")

    log(f"未找到可启动的应用程序")
    return False


def show_update_notification(title: str, message: str, is_error: bool = False):
    """
    显示 Windows 系统通知

    Args:
        title: 通知标题
        message: 通知内容
        is_error: 是否为错误通知
    """
    if platform.system() != "Windows":
        return

    try:
        from ctypes import windll

        # 使用 Windows Toast 通知
        # 通过 PowerShell 发送通知（更可靠）
        ps_script = f'''
        Add-Type -AssemblyName System.Windows.Forms
        $notify = New-Object System.Windows.Forms.NotifyIcon
        $notify.Icon = [System.Drawing.SystemIcons]::{"Error" if is_error else "Information"}
        $notify.Visible = $true
        $notify.ShowBalloonTip(5000, "{title}", "{message}", {"ToolTipIcon_Error" if is_error else "ToolTipIcon_Info"})
        Start-Sleep -Seconds 6
        $notify.Dispose()
        '''
        subprocess.run(
            ["powershell", "-WindowStyle", "Hidden", "-Command", ps_script],
            capture_output=True,
            timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
    except Exception as e:
        log(f"显示通知失败: {e}")


def main():
    """主函数"""
    # 解析参数
    auto_start = "--auto-start" in sys.argv

    log("=" * 50)
    log("AUTOavantar 更新脚本启动")
    log(f"自动启动: {auto_start}")
    log("=" * 50)

    app_dir = get_app_dir()
    log(f"应用目录: {app_dir}")

    write_update_status("waiting", "等待主程序退出...", 5)

    # 1. 等待主进程退出
    log("等待主进程退出...")
    if not wait_for_process_exit("AUTOavantar", timeout=30):
        log("等待超时，尝试强制终止主进程...")
        terminate_process("AUTOavantar")
        time.sleep(2)

    # 额外等待确保文件释放
    time.sleep(2)

    # 2. 清除更新标记
    update_flag = app_dir / ".update_pending"
    if update_flag.exists():
        update_flag.unlink()
        log("已清除更新标记")

    # 3. 执行 git pull
    log("执行 git pull...")
    write_update_status("downloading", "正在获取更新...", 20)
    success, message = execute_git_pull(app_dir)

    if not success:
        log(f"更新失败: {message}")
        write_update_status("failed", f"更新失败: {message}", 0)
        show_update_notification("AUTOavantar 更新失败", message, is_error=True)

        # 清除状态文件（延迟，给用户时间查看）
        time.sleep(10)
        clear_update_status()
        return

    log(f"更新成功: {message}")
    write_update_status("success", "更新完成", 100)

    # 4. 重启或通知
    if auto_start:
        log("自动启动应用...")
        if restart_application(app_dir):
            log("更新流程完成，应用已启动")
            show_update_notification("AUTOavantar 更新完成", "应用已自动启动")
        else:
            log("自动启动失败，通知用户手动启动")
            show_update_notification("AUTOavantar 更新完成", "请手动启动应用")
    else:
        log("更新完成，等待用户手动启动")
        show_update_notification("AUTOavantar 更新完成", "请手动启动应用")

    # 延迟清除状态文件
    time.sleep(5)
    clear_update_status()

    log("=" * 50)


if __name__ == "__main__":
    main()
