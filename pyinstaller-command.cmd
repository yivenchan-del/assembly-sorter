
：项目根目录
cd	C:\Users\3F-PT52\Documents\git-bak\myproject\assembly-sorter\assembly_sorter_project
 ：执行py
 python -m assembly-sorter.main
：打包命令
pyinstaller --noconsole --onefile --name="ASC-2.0"  --icon 'Workspaces.ico' --add-data "src\assembly_sorter_project\index.html;." --add-data "static;static" src\assembly_sorter_project/main.py
