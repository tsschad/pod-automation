; drive_click.ahk
;
; AutoHotkey v2 script that clicks the "Drive" (steering wheel) icon on
; Assetto Corsa's post-launch "Session information" screen, using
; SendMode "Play" instead of the default "Input" mode.
;
; Why this exists: the Python/pyautogui version of this click was
; landing on the right spot -- the icon visibly hovered/highlighted,
; confirming position and window focus were both correct -- but the
; click itself wasn't registering in-game. That's a known symptom for
; fullscreen games that don't respond to OS-level synthetic input
; (SendInput/mouse_event). AutoHotkey's "Play" send mode is built
; specifically for this case: instead of injecting at the OS input
; level, it pushes events directly into the target window's message
; queue. See: https://www.autohotkey.com/board/topic/95412-sendplay/
;
; Usage (called from ahk_click.py, but runnable standalone too):
;   AutoHotkey64.exe drive_click.ahk xy <x> <y> [holdMs] [delayMs] [windowTitle]
;   AutoHotkey64.exe drive_click.ahk image <imagePath> [holdMs] [delayMs] [windowTitle] [timeoutMs]
;
; Exit codes: 0 = clicked, 1 = image not found within timeout, 2 = bad usage.

SendMode "Play"
SetTitleMatchMode 2  ; match anywhere in the window title, not just exact

mode := A_Args.Length >= 1 ? A_Args[1] : ""

if (mode = "xy") {
    x := A_Args[2]
    y := A_Args[3]
    holdMs := A_Args.Length >= 4 ? Integer(A_Args[4]) : 120
    delayMs := A_Args.Length >= 5 ? Integer(A_Args[5]) : 5000
    winTitle := A_Args.Length >= 6 ? A_Args[6] : "Assetto Corsa"

    Sleep delayMs
    if WinExist(winTitle)
        WinActivate
    Sleep 300

    MouseMove x, y, 10
    Sleep 150
    Click x, y, "Down"
    Sleep holdMs
    Click x, y, "Up"

    ExitApp 0
}
else if (mode = "image") {
    imagePath := A_Args[2]
    holdMs := A_Args.Length >= 3 ? Integer(A_Args[3]) : 120
    delayMs := A_Args.Length >= 4 ? Integer(A_Args[4]) : 3000
    winTitle := A_Args.Length >= 5 ? A_Args[5] : "Assetto Corsa"
    timeoutMs := A_Args.Length >= 6 ? Integer(A_Args[6]) : 25000

    Sleep delayMs
    if WinExist(winTitle)
        WinActivate
    Sleep 300

    foundX := 0
    foundY := 0
    elapsed := 0
    pollMs := 500
    found := false

    while (elapsed < timeoutMs) {
        try {
            if ImageSearch(&foundX, &foundY, 0, 0, A_ScreenWidth, A_ScreenHeight, imagePath)
                found := true
        } catch {
            found := false
        }
        if (found)
            break
        Sleep pollMs
        elapsed += pollMs
    }

    if (found) {
        MouseMove foundX, foundY, 10
        Sleep 150
        Click foundX, foundY, "Down"
        Sleep holdMs
        Click foundX, foundY, "Up"
        ExitApp 0
    } else {
        ExitApp 1
    }
}
else {
    ExitApp 2
}
