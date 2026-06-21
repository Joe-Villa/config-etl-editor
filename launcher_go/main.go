package main

import (
	"bufio"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
)

func appRoot() string {
	exe, err := os.Executable()
	if err != nil {
		return "."
	}
	return filepath.Dir(exe)
}

func pythonExe(root string) string {
	return filepath.Join(root, "python", "python.exe")
}

func appDir(root string) string {
	return filepath.Join(root, "app")
}

func pauseOnExit() {
	fmt.Print("按 Enter 键退出...")
	_, _ = bufio.NewReader(os.Stdin).ReadBytes('\n')
}

func main() {
	root := appRoot()
	py := pythonExe(root)
	app := appDir(root)
	entry := filepath.Join(app, "view_map.py")

	if _, err := os.Stat(py); err != nil {
		fmt.Printf("错误：找不到内置 Python：%s\n", py)
		fmt.Println("请解压完整的 map_editor 文件夹后再运行。")
		os.Exit(1)
	}
	if _, err := os.Stat(entry); err != nil {
		fmt.Printf("错误：找不到程序文件：%s\n", entry)
		os.Exit(1)
	}

	args := []string{"view_map.py"}
	if len(os.Args) > 1 {
		args = append(args, os.Args[1:]...)
	}

	fmt.Println("地图编辑器")
	if len(os.Args) > 1 {
		fmt.Printf("预加载数据库：%s\n", os.Args[1])
	} else {
		fmt.Println("浏览器将打开启动页，可加载已有数据库或从游戏内容构建新库。")
	}
	fmt.Println("启动中… http://127.0.0.1:8765/viewer/index.html")
	fmt.Println("关闭本窗口即停止服务。")

	cmd := exec.Command(py, args...)
	cmd.Dir = app
	cmd.Env = append(os.Environ(), "PYTHONPATH="+app)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	cmd.Stdin = os.Stdin
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: false}
	err := cmd.Run()
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			fmt.Printf("程序已退出（代码 %d）。\n", exitErr.ExitCode())
		} else {
			fmt.Printf("错误：%v\n", err)
		}
		pauseOnExit()
		os.Exit(1)
	}
}
