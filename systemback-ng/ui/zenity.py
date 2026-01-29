import subprocess


def info(msg: str) -> None:
    subprocess.run(["zenity", "--info", "--text", msg], check=False)


def error(msg: str) -> None:
    subprocess.run(["zenity", "--error", "--text", msg], check=False)


def progress_start(title: str, text: str):
    return subprocess.Popen([
        "zenity",
        "--progress",
        "--title", title,
        "--text", text,
        "--percentage", "0",
        "--auto-close",
    ], stdin=subprocess.PIPE, text=True)


def progress_update(proc, percent: int, text: str | None = None):
    if proc.stdin:
        if text:
            proc.stdin.write(f"#{text}\n")
        proc.stdin.write(f"{percent}\n")
        proc.stdin.flush()


def progress_end(proc):
    if proc.stdin:
        proc.stdin.close()
    proc.wait(timeout=5)
