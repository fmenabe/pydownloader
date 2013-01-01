# -*- coding: utf-8 -*-

from pprint import pprint
import os.path as path
import re
import multiprocessing
import time
import sites

FILENAME_REGEX = re.compile('.*filename="(.*).*"')
SITE_REGEXP = re.compile('^http://(www[.])?([a-zA-Z]*)[.](net|com|org)/.*$')
CHUNK_SIZE = 8192


class DownloadError(Exception):
    pass


class DownloadManager(multiprocessing.Process):
    def __init__(self, links, sites, dst, parallel):
        multiprocessing.Process.__init__(self)
        self.manager = multiprocessing.Manager()
#        self.processes = self.manager.list()
        self.processes = self.manager.list()

        # Init links.
        self.links = self.manager.list()
        self.indexed_links = {}
        for index, link in enumerate(links):
            self.indexed_links.setdefault(link, index)
            self.links.append({
                'url': link,
                'status': 'waiting',
                'filename': '',
                'filesize': -1,
                'downloaded': 0,
                'last_downloaded': 0,
            })

        # Init sites.
        self.sites = sites

        # Init destination directory.
        self.dst = dst
        self.parallel = parallel

        self.last_download = 0


    def link(self, link, name, value):
        index = self.indexed_links[link]
        link = self.links[index]
        link[name] = value
        self.links[index] = link


    def downloaded(self, link):
        return self.links[self.indexed_links[link]]['downloaded']


    def download(self):
        link = self.links[self.last_download]['url']

        site = SITE_REGEXP.search(link).group(2).lower()
        if site not in self.sites:
            self.link(link, 'error', "no ids for site '%s'" % site)
            self.link(link, 'status', 'failed')
            return

        self.link(link, 'status', 'connecting')

        if 'obj' in self.sites[site]:
            downloader = self.sites[site]['obj']
        else:
            downloader = getattr(sites, site.capitalize())()

            try:
                downloader.login(
                    self.sites[site]['login'], self.sites[site]['password']
                )
            except DownloadError as err:
                self.link(link, 'status', 'failed')
                self.link(link, 'error', err.__str__())
                return
            self.sites[site].setdefault('obj', downloader)

        try:
            filelink = downloader.get_link(link)
        except DownloadError as err:
            self.link(link, 'status', 'failed')
            self.link(link, 'error', err.__str__())
            return

        process = DownloadProcess(
            filelink, link, self, downloader.opener
        )
        process.start()


    def run(self):
        finished = any([
            True if link['status'] == 'finished' else False for link in self.links
        ])
        while not finished:
            nb_downloads = sum([
                1 if link['status'] in ('connecting', 'downloading') else 0 \
                for link in self.links
            ])

            to_launch = self.parallel - nb_downloads
            if self.last_download < len(self.links):
                for index in xrange(to_launch):
                    self.download()
                    self.last_download += 1
                if self.last_download == len(self.links):
                    break
            time.sleep(1)


class DownloadProcess(multiprocessing.Process):
    def __init__(self, link, original_link, manager, http_handler):
        multiprocessing.Process.__init__(self)
        self.manager = manager
        self.original_link = original_link
        self.link = link
        self.http = http_handler


    def run(self):
        self.manager.processes.append(self.pid)
        response = self.http.open(self.link)
        headers = response.headers

        # Get filesize, filename, filepath.
        filesize = int(headers.getheader('Content-Length').strip())
        filename = FILENAME_REGEX.search(
            headers.getheader('Content-Disposition').strip()
        ).group(1)
        filepath = path.join(self.manager.dst, filename)

        # Update manager for back datas to main function.
        self.manager.link(self.original_link, 'status', 'downloading')
        self.manager.link(self.original_link, 'filesize', filesize)
        self.manager.link(self.original_link, 'filename', filename)

        with open(filepath, 'wb') as fhandler:
            while True:
                chunk = response.read(CHUNK_SIZE)
                if not chunk:
                    self.manager.link(self.original_link, 'status', 'finished')
                    break
                fhandler.write(chunk)
                downloaded = self.manager.downloaded(self.original_link)
                downloaded += len(chunk)
                self.manager.link(self.original_link, 'downloaded', downloaded)
        self.manager.processes.remove(self.pid)
