"""本机目录选择。浏览器拿不到真实路径，由宿主弹出系统窗口。"""

import base64
import logging
import os
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# 路径写进 UTF-8 文件。PowerShell 重定向的标准输出是系统 ANSI 代码页，中文路径会被写坏。
_WINDOWS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -ReferencedAssemblies System.Windows.Forms, System.Drawing -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Windows.Forms;

public class VistaFolderPicker {
    public string Title = "";
    public string Initial = "";
    public string SelectedPath = "";

    public bool Show() {
        var owner = new Form();
        owner.TopMost = true;
        owner.ShowInTaskbar = false;
        owner.FormBorderStyle = FormBorderStyle.None;
        owner.StartPosition = FormStartPosition.CenterScreen;
        owner.Size = new System.Drawing.Size(1, 1);
        owner.Opacity = 0.01;
        owner.Show();
        owner.Activate();
        SetForegroundWindow(owner.Handle);
        try {
            var dialog = (IFileOpenDialog)new FileOpenDialogRCW();
            dialog.SetOptions(FOS.FOS_PICKFOLDERS | FOS.FOS_FORCEFILESYSTEM | FOS.FOS_PATHMUSTEXIST | FOS.FOS_NOCHANGEDIR);
            if (!string.IsNullOrEmpty(Title)) dialog.SetTitle(Title);
            SetInitial(dialog);
            int hr = dialog.Show(owner.Handle);
            if (hr == CANCELLED) return false;
            if (hr != 0) Marshal.ThrowExceptionForHR(hr);
            IShellItem item;
            dialog.GetResult(out item);
            IntPtr psz;
            item.GetDisplayName(SIGDN.SIGDN_FILESYSPATH, out psz);
            SelectedPath = Marshal.PtrToStringUni(psz) ?? "";
            Marshal.FreeCoTaskMem(psz);
            return SelectedPath.Length > 0;
        } finally {
            owner.Close();
            owner.Dispose();
        }
    }

    void SetInitial(IFileOpenDialog dialog) {
        if (string.IsNullOrEmpty(Initial)) return;
        Guid iid = typeof(IShellItem).GUID;
        IntPtr ptr;
        if (SHCreateItemFromParsingName(Initial, IntPtr.Zero, ref iid, out ptr) != 0) return;
        try {
            dialog.SetFolder((IShellItem)Marshal.GetObjectForIUnknown(ptr));
        } finally {
            Marshal.Release(ptr);
        }
    }

    const int CANCELLED = unchecked((int)0x800704C7);

    [DllImport("user32.dll")]
    static extern bool SetForegroundWindow(IntPtr hWnd);

    [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = true)]
    static extern int SHCreateItemFromParsingName(string pszPath, IntPtr pbc, ref Guid riid, out IntPtr ppv);

    [ComImport, Guid("DC1C5A9C-E88A-4dde-A5A1-60F82A20AEF7")]
    class FileOpenDialogRCW {}

    [ComImport, Guid("d57c7288-d4ad-4768-be02-9d969532d960"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IFileOpenDialog {
        [PreserveSig] int Show(IntPtr parent);
        void SetFileTypes(uint cFileTypes, IntPtr rgFilterSpec);
        void SetFileTypeIndex(uint iFileType);
        void GetFileTypeIndex(out uint piFileType);
        void Advise(IntPtr pfde, out uint pdwCookie);
        void Unadvise(uint dwCookie);
        void SetOptions(FOS fos);
        void GetOptions(out FOS fos);
        void SetDefaultFolder(IShellItem psi);
        void SetFolder(IShellItem psi);
        void GetFolder(out IShellItem ppsi);
        void GetCurrentSelection(out IShellItem ppsi);
        void SetFileName([MarshalAs(UnmanagedType.LPWStr)] string pszName);
        void GetFileName([MarshalAs(UnmanagedType.LPWStr)] out string pszName);
        void SetTitle([MarshalAs(UnmanagedType.LPWStr)] string pszTitle);
        void SetOkButtonLabel([MarshalAs(UnmanagedType.LPWStr)] string pszText);
        void SetFileNameLabel([MarshalAs(UnmanagedType.LPWStr)] string pszLabel);
        void GetResult(out IShellItem ppsi);
        void AddPlace(IShellItem psi, int fdap);
        void SetDefaultExtension([MarshalAs(UnmanagedType.LPWStr)] string pszDefaultExtension);
        void Close(int hr);
        void SetClientGuid(ref Guid guid);
        void ClearClientData();
        void SetFilter(IntPtr pFilter);
        void GetResults(out IntPtr ppenum);
        void GetSelectedItems(out IntPtr ppsai);
    }

    [ComImport, Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IShellItem {
        void BindToHandler(IntPtr pbc, ref Guid bhid, ref Guid riid, out IntPtr ppv);
        void GetParent(out IShellItem ppsi);
        void GetDisplayName(SIGDN sigdnName, out IntPtr ppszName);
        void GetAttributes(uint sfgaoMask, out uint psfgaoAttribs);
        void Compare(IShellItem psi, uint hint, out int piOrder);
    }

    enum SIGDN : uint {
        SIGDN_FILESYSPATH = 0x80058000,
    }

    [Flags]
    enum FOS : uint {
        FOS_NOCHANGEDIR = 0x8,
        FOS_PICKFOLDERS = 0x20,
        FOS_FORCEFILESYSTEM = 0x40,
        FOS_PATHMUSTEXIST = 0x800,
    }
}
'@
$picker = New-Object VistaFolderPicker
$picker.Title = $env:AINOVEL_PICK_TITLE
$picker.Initial = $env:AINOVEL_PICK_INITIAL
if ($picker.Show()) {
    [System.IO.File]::WriteAllText($env:AINOVEL_PICK_RESULT, $picker.SelectedPath, [System.Text.UTF8Encoding]::new($false))
}
"""


_WINDOWS_SAVE_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class AinovelWindow {
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
}
'@
$owner = New-Object System.Windows.Forms.Form
$owner.TopMost = $true
$owner.ShowInTaskbar = $false
$owner.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::None
$owner.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen
$owner.Size = New-Object System.Drawing.Size(1, 1)
$owner.Opacity = 0.01
$owner.Show()
$owner.Activate()
[void][AinovelWindow]::SetForegroundWindow($owner.Handle)
$dialog = New-Object System.Windows.Forms.SaveFileDialog
$dialog.Title = $env:AINOVEL_PICK_TITLE
$dialog.Filter = '文本文件 (*.txt)|*.txt'
$dialog.DefaultExt = 'txt'
$dialog.AddExtension = $true
$dialog.OverwritePrompt = $true
if ($env:AINOVEL_PICK_INITIAL) { $dialog.InitialDirectory = $env:AINOVEL_PICK_INITIAL }
if ($env:AINOVEL_PICK_NAME) { $dialog.FileName = $env:AINOVEL_PICK_NAME }
try {
    $result = $dialog.ShowDialog($owner)
    if ($result -eq [System.Windows.Forms.DialogResult]::OK -and $dialog.FileName) {
        [System.IO.File]::WriteAllText($env:AINOVEL_PICK_RESULT, $dialog.FileName, [System.Text.UTF8Encoding]::new($false))
    }
} finally {
    $owner.Close()
    $owner.Dispose()
}
"""


def ask_directory(title: str = "选择书目录", initial: Path | None = None) -> str:
    if os.name == "nt":
        return _ask_windows(title, initial)
    return _ask_tk(title, initial)


def _ask_windows(title: str, initial: Path | None) -> str:
    handle, name = tempfile.mkstemp(prefix="ainovel-dir-", suffix=".txt")
    os.close(handle)
    result = Path(name)
    env = os.environ.copy()
    env["AINOVEL_PICK_TITLE"] = title
    env["AINOVEL_PICK_INITIAL"] = str(initial) if initial is not None else ""
    env["AINOVEL_PICK_RESULT"] = str(result)
    try:
        completed = _run_powershell(_WINDOWS_SCRIPT, env)
        if completed.returncode != 0:
            detail = _process_text(completed.stderr) or _process_text(completed.stdout)
            logger.error("目录选择失败: %s", detail or completed.returncode)
            raise RuntimeError("无法打开目录选择")
        return _read_result(result)
    except OSError as exc:
        raise RuntimeError("无法打开目录选择") from exc
    finally:
        result.unlink(missing_ok=True)


def _run_powershell(script: str, env: dict) -> subprocess.CompletedProcess:
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-STA", "-EncodedCommand", encoded],
        capture_output=True,
        env=env,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _read_result(path: Path) -> str:
    if not path.is_file() or path.stat().st_size == 0:
        return ""
    return path.read_text(encoding="utf-8").strip()


def _process_text(raw: bytes) -> str:
    if not raw:
        return ""
    for encoding in ("utf-8", "utf-16", "gbk"):
        try:
            text = raw.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
        if text:
            return text
    return raw.decode("utf-8", "replace").strip()


def ask_save_file(title: str = "导出为文本", initial: Path | None = None, name: str = "") -> str:
    if os.name == "nt":
        return _ask_windows_save(title, initial, name)
    return _ask_tk_save(title, initial, name)


def _ask_windows_save(title: str, initial: Path | None, name: str) -> str:
    handle, result_name = tempfile.mkstemp(prefix="ainovel-save-", suffix=".txt")
    os.close(handle)
    result = Path(result_name)
    env = os.environ.copy()
    env["AINOVEL_PICK_TITLE"] = title
    env["AINOVEL_PICK_INITIAL"] = str(initial) if initial is not None else ""
    env["AINOVEL_PICK_NAME"] = name
    env["AINOVEL_PICK_RESULT"] = str(result)
    try:
        completed = _run_powershell(_WINDOWS_SAVE_SCRIPT, env)
        if completed.returncode != 0:
            detail = _process_text(completed.stderr) or _process_text(completed.stdout)
            logger.error("保存位置选择失败: %s", detail or completed.returncode)
            raise RuntimeError("无法打开保存位置")
        return _read_result(result)
    except OSError as exc:
        raise RuntimeError("无法打开保存位置") from exc
    finally:
        result.unlink(missing_ok=True)


def _ask_tk(title: str, initial: Path | None) -> str:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        chosen = filedialog.askdirectory(parent=root, title=title, initialdir=str(initial) if initial else None)
    finally:
        root.destroy()
    return chosen or ""


def _ask_tk_save(title: str, initial: Path | None, name: str) -> str:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        chosen = filedialog.asksaveasfilename(
            parent=root,
            title=title,
            initialdir=str(initial) if initial else None,
            initialfile=name or None,
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt")],
        )
    finally:
        root.destroy()
    return chosen or ""
