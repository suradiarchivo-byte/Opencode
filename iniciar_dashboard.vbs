Set sh = CreateObject("WScript.Shell")
sh.Run """C:\Python314\pythonw.exe"" ""C:\bvc-monitor\app.py""", 0, False
WScript.Sleep 2500
sh.Run "http://127.0.0.1:8000", 0, False
