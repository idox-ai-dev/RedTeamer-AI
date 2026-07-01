如果目標 Windows 機器沒有安裝 Python，請將以下檔案放到這個目錄：

1. Python embeddable package (64-bit)
   下載網址：https://www.python.org/downloads/windows/
   選擇最新的 Python 3.12.x → "Windows embeddable package (64-bit)"
   檔名範例：python-3.12.9-embed-amd64.zip

   注意：
   - 不需要解壓縮，直接放 .zip 即可，install.ps1 會自動解壓縮
   - 只支援 Windows x64（amd64）

2. (選用) get-pip.py
   如果安裝環境無法連網，請預先下載：
   https://bootstrap.pypa.io/get-pip.py
   放到這個目錄，install.ps1 會優先使用本地檔案。

目錄結構（放好後）：
  python-embed/
  ├── README.txt
  ├── python-3.12.x-embed-amd64.zip   ← 必須
  └── get-pip.py                       ← 選用（離線環境用）
