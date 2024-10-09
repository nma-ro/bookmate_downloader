#!/usr/bin/env python3
import os
import argparse
import shutil
import json
import array
import base64
import zipfile
import logging
import concurrent.futures
from xml.etree import ElementTree as ET
from html.parser import HTMLParser
import requests
from Crypto.Cipher import AES


def bytess(arr):
    assert type(arr) in [list]
    return array.array('B', arr).tobytes()


def zipdir(path, ziph):
    # ziph is zipfile handle
    top = path
    for root, _, files in os.walk(path):
        for filename in files:
            if filename != "mimetype":
                continue
            src = os.path.join(root, filename)
            ziph.write(filename=src, arcname=os.path.relpath(src, top), compress_type=zipfile.ZIP_STORED)
    for root, _, files in os.walk(path):
        for filename in files:
            if filename == "mimetype":
                continue
            src = os.path.join(root, filename)
            ziph.write(filename=src, arcname=os.path.relpath(src, top))


class ScriptParser(HTMLParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__data = None
        self.client_params = {}

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.__data = ""

    def handle_endtag(self, tag):
        if tag == "script":
            self.handle_script_data(self.__data)
            self.__data = None

    def handle_data(self, data):
        if self.__data is not None:
            self.__data += data

    def handle_script_data(self, script_data):
        logging.debug("script_data:%s ...", script_data[:40])
        S = "initialState"
        if S not in script_data:
            return
        j = json.loads(script_data)
        json_text = j["props"]["pageProps"]["initialState"]
        logging.debug("json_text: %s", json_text)
        self.client_params = json.loads(json_text.strip())
        logging.debug("client_params: %s", self.client_params)


class Downloader:
    def __init__(self, outdir, cookies):
        self.outdir = outdir
        self.cookies = cookies

    def save_bytes(self, bts, name):
        fpath = os.path.join(self.outdir, name)
        dirpath = os.path.dirname(fpath)
        if not os.path.exists(dirpath):
            os.makedirs(dirpath)
        with open(fpath, "wb") as fout:
            fout.write(bts)
            fout.close()

    def request_url(self, url):
        logging.debug("downloading %s ...", url)
        response = requests.get(url, cookies=self.cookies)
        logging.debug("response:%s", response)
        assert response.status_code in [200], response.status_code
        return response

    def path(self, sub):
        return os.path.join(self.outdir, sub)

    def delete_downloaded(self):
        shutil.rmtree(self.outdir)

    def delete_css(self):
        for root, _, files in os.walk(".", topdown=False):
            for name in files:
                if name.lower().endswith(".css"):
                    with open(os.path.join(root, name), "w", encoding="UTF-8") as f:
                        f.write("")
                        f.close()

    def make_epub(self):
        assert os.path.exists(self.outdir), self.outdir
        epubfpath = self.outdir + ".epub"
        with zipfile.ZipFile(epubfpath, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipdir(self.outdir, zipf)
            zipf.close()
        logging.info("ebook saved as %s", epubfpath)
        logging.info("We recommend https://calibre-ebook.com/ for book management and conversion")


class BookDownloader:
    def __init__(self, bookid, downloader, secret=None):
        self.bookid = bookid
        self.downloader = downloader
        self.book_encrypted_metadata = {}
        self.secret = self.download_secret_and_metadata() if secret is None else secret
        assert self.secret is not None

    def download_secret_and_metadata(self):
        url = "https://books.yandex.ru/reader/%s" % self.bookid
        html = self.downloader.request_url(url).text
        logging.debug("html:%s ...", html[:20])
        parser = ScriptParser()
        parser.feed(html)
        secret = parser.client_params["global"]["userMetadata"]["secret"]
        logging.debug("secret: %s", secret)
        self.book_encrypted_metadata = parser.client_params["page"]["bookMetadata"]
        logging.debug("book_metadata: %s", self.book_encrypted_metadata)
        return secret

    def download(self):
        metadata = self.decrypt_metadata(self.book_encrypted_metadata, self.secret)
        self.process_metadata(metadata)

    def decrypt_metadata(self, encrypted_metadata, secret):
        assert type(encrypted_metadata) in [dict]
        metadata = {}
        for (key, val) in encrypted_metadata.items():
            if type(val) in [list]:
                metadata[key] = self.decrypt(secret, bytess(val))
            else:
                metadata[key] = val
        return metadata

    def decrypt(self, secret, data):
        assert type(secret) in [str], type(secret)
        key = base64.b64decode(secret)
        bts = self.rawDecryptBytes(data[16:], key, data[:16])
        logging.debug("len(bts):%s", len(bts))
        logging.debug("lastbyte:%s", bts[-1])
        padsize = -1*bts[-1]
        return bts[:padsize]

    def rawDecryptBytes(self, cryptArr, key, iv):
        assert type(cryptArr) in [bytes]
        assert type(key) in [bytes]
        assert type(iv) in [bytes]
        cipher = AES.new(key, AES.MODE_CBC, iv)
        return cipher.decrypt(cryptArr)

    def process_metadata(self, metadata):
        self.downloader.save_bytes(b"application/epub+zip", "mimetype")
        self.downloader.save_bytes(metadata["container"], "META-INF/container.xml")  # noqa: E501
        self.downloader.save_bytes(metadata["opf"], "OEBPS/content.opf")
        self.process_opf(metadata["document_uuid"])
        self.downloader.save_bytes(metadata["ncx"], "OEBPS/toc.ncx")

    def process_opf(self, uuid):
        content_file = self.downloader.path("OEBPS/content.opf")
        fnames = []
        for event, elem in ET.iterparse(content_file, events=["start"]):
            if event != 'start':
                continue
            if not elem.tag.endswith("}item"):
                continue
            if "href" not in elem.attrib:
                continue
            fname = elem.attrib["href"]
            if fname == "toc.ncx":
                continue
            fnames.append(fname)
        print("Downloading book contents:")
        content_total_parts = len(fnames)

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(self.download_content_part, fname, index + 1, content_total_parts, uuid, self.downloader): index
                for index, fname in enumerate(fnames)
            }

    @staticmethod
    def download_content_part(fname, content_part_number, content_total_parts, uuid, downloader):
        print(f"...{fname} ({content_part_number}/{content_total_parts})")
        logging.debug("fname:%s", fname)
        url = "https://books.yandex.ru/reader/p/a/4/d/{uuid}/contents/OEBPS/{fname}".format(uuid=uuid, fname=fname)
        try:
            response = downloader.request_url(url)
            downloader.save_bytes(response.content, "OEBPS/" + fname)
        except Exception:
            logging.warning("cannot download from '%s'", url)

    def delete_downloaded(self):
        self.downloader.delete_downloaded()

    def make_epub(self):
        self.downloader.make_epub()

    def delete_css(self):
        self.downloader.delete_css()


class Bookmate:
    def __init__(self, outdir, cookies):
        assert os.path.exists(outdir), "path %s does not exist" % outdir
        self.outdir = outdir
        assert cookies
        self.cookies = cookies

    def get_book(self, bookid):
        outdir = os.path.join(self.outdir, bookid)
        downloader = Downloader(outdir=outdir, cookies=self.cookies)
        return BookDownloader(bookid=bookid, downloader=downloader)


def get_cookies():
    if os.path.exists("cookies.json"):
        with open("cookies.json", "r") as cookies_file:
            cc = json.loads(cookies_file.read())
    else:
        try:
            from pycookiecheat import chrome_cookies
            cc = chrome_cookies("https://books.yandex.ru")
            with open("cookies.json", "w") as cookies_file:
                cookies_file.write(json.dumps(cc))
        except Exception:
            print("Log in to books.yandex.ru and get session cookies from Chrome or export them in to a file 'secret.json' in JSON format.")
            exit(0)
    return cc

if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument("--bookid", help="bookid, take from the book url", required=True)
    argparser.add_argument("--outdir", help="Output directory", default="out")
    argparser.add_argument("--log", help="loglevel", type=str, default="INFO", choices=logging._nameToLevel.keys())
    argparser.add_argument("--download", type=bool, default=True)
    argparser.add_argument("--delete_downloaded", type=bool, default=True)
    argparser.add_argument("--make_epub", type=bool, default=True)
    argparser.add_argument("--delete_css", type=bool, default=True)
    arg = argparser.parse_args()
    logformat = '%(asctime)s (%(name)s) %(levelname)s %(module)s.%(funcName)s():%(lineno)d  %(message)s'  # noqa: E501
    logging.basicConfig(level=arg.log, format=logformat)
    if not os.path.exists(arg.outdir):
        logging.info("Creating folder %s ...", arg.outdir)
        os.makedirs(arg.outdir)
    bookmate = Bookmate(outdir=arg.outdir, cookies=get_cookies())
    book = bookmate.get_book(bookid=arg.bookid)
    if arg.download:
        book.download()
    if arg.delete_css:
        book.delete_css()
    if arg.make_epub:
        book.make_epub()
    if arg.delete_downloaded:
        book.delete_downloaded()
    # url = bookid if arg.bookid.startswith("http") else "https://reader.bookmate.com/%s" % arg.bookid  # noqa: E501
    # downloader = BookDownloader(url, "out")
    # downloader.download_book()
    # downloader.make_epub()
    # downloader.delete_downloaded()
