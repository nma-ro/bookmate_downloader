# Bookmate Downloader
Downloads books from https://books.yandex.ru and saves them as epub format files.
Use upstream to download from bookmate.com.

# You need to be subscribed to books.yandex.ru premium OR download books that are available for free !!!
Works on Mac OS X, Linux.
For Windows 10 you'll need to install WSL (Windows subsystem for linux) aka Windows Ubuntu.

Steps:
1. Buy the subscription at books.yandex.ru
2. Authorize at books.yandex.ru with your Chrome browser
3. install python3
4. Copy the bookid (open the book at books.yandex.ru and check the url)
5. `python3 bookmate_downloader.py --bookid BookIdHere`
6. The epub will be downloaded to "out"

## Installation details:
```bash
sudo apt update
sudo apt install -y python3-pip
git clone https://github.com/nma-ro/bookmate_downloader
cd bookmate_downloader
pip3 install -r src/python3/requirements.txt
python3 src/python3/bookmate_downloader.py --bookid KFHDG3bp
```
## Docker Usage (Alternative "installation")
```bash
git clone https://github.com/nma-ro/bookmate_downloader.git .
docker build -t bookmate_dl .
docker run -it --mount type=bind,source=$(pwd),target=/mnt/data bookmate_dl --bookid KFHDG3bp --log DEBUG --outdir /mnt/data
```

## From Windows:
1. Install & Run [WSL](https://docs.microsoft.com/en-us/windows/wsl/install-win10)
2. ```cd /mnt/c/users/myusername```
3. ```git clone https://www.github.com/nma-ro/bookmate_downloader```
4. ```cd bookmate_downloader```
5. ```sudo apt-get update```
6. ```sudo apt install -y python3-pip```
7. ```pip3 install -r src/python3/requirements.txt```
8. ```python3 src/python3/bookmate_downloader.py --bookid KFHDG3bp```
9. After completion, you will find your book at your home folder at bookmate_downloader/out


You will need to be authenticated in books.yandex.ru with your account in Chrome. 
Session cookies will be retrieved either from keychain or from file named `cookies.json`. 
After first successful retrieval, session cookies will be reused.

NOTE: If you experience problems with download, remove `cookies.json` and re-authenticate in books.yandex.ru.

In order to get session cookies manually, use Chrome plugin from https://exportthiscookie.com.
