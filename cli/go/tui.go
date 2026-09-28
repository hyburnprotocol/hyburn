package main

import (
	"encoding/json"
	"fmt"
	"golang.org/x/term"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"strings"
)

func uiEvent(value map[string]any) {
	if os.Getenv("HYBURN_TUI_CHILD") == "1" {
		data, err := json.Marshal(value)
		if err == nil {
			fmt.Println("@HYBURN_UI@" + string(data))
		}
	}
}

func tuiScript() string {
	exe, _ := os.Executable()
	cwd, _ := os.Getwd()
	for _, start := range []string{filepath.Dir(exe), cwd} {
		for dir := start; ; dir = filepath.Dir(dir) {
			candidate := filepath.Join(dir, "cli", "tui.py")
			if _, err := os.Stat(candidate); err == nil {
				return candidate
			}
			if filepath.Dir(dir) == dir {
				break
			}
		}
	}
	return ""
}

func routeUI(o opts) {
	if o.cmd != "mine" || os.Getenv("HYBURN_TUI_CHILD") == "1" {
		return
	}
	interactive := term.IsTerminal(int(os.Stdin.Fd())) && term.IsTerminal(int(os.Stdout.Fd())) && term.IsTerminal(int(os.Stderr.Fd()))
	if interactive && !o.plain {
		script := tuiScript()
		if script == "" {
			die("Shared TUI files not found; run from the repository or use --plain.")
		}
		exe, _ := os.Executable()
		command, _ := json.Marshal([]string{exe})
		args := append([]string{script, "--engine", "go", "--command", string(command), "--"}, os.Args[1:]...)
		cmd := exec.Command("python3", args...)
		cmd.Stdin = os.Stdin
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr
		signals := make(chan os.Signal, 1)
		signal.Notify(signals, os.Interrupt)
		err := cmd.Run()
		signal.Stop(signals)
		if err != nil {
			if exit, ok := err.(*exec.ExitError); ok {
				os.Exit(exit.ExitCode())
			}
			die("Shared TUI needs Python 3.10+; install it or use --plain. No mining started.")
		}
		os.Exit(0)
	}
	if o.yes {
		return
	}
	if !term.IsTerminal(int(os.Stdin.Fd())) {
		die("Start choice requires a terminal; use --yes for intentional unattended mining.")
	}
	fmt.Print("Start mining? [y/N] ")
	var answer string
	fmt.Fscanln(os.Stdin, &answer)
	if strings.ToLower(strings.TrimSpace(answer)) != "y" && strings.ToLower(strings.TrimSpace(answer)) != "yes" {
		fmt.Println("Mining not started. No new transactions sent.")
		os.Exit(0)
	}
}
