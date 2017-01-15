# coding: utf-8

import os
import re
import sys
import imp
import time
import clg.conf
import threading
import multiprocessing
from addict import Dict

import logging
logger = logging.getLogger('pydownloader')

_SITE_RE = re.compile('^http://(www[.])?([a-zA-Z]*)[.](net|com|org)/.*$')
_FILENAME_RE = re.compile('.*filename="(.*).*"')
SHARED_ATTRS = ['status', 'msg', 'provider', 'pid', 'real_url',
                'filesize', 'filepath', 'downloaded', 'speed']

CHUNK_SIZE = 4096

def trying(max_try=5, wait=1):
    def decorator(func):
        def wrapper(*args, **kwargs):
            nb_try = 1
            error = None
            while True:
                if nb_try > max_try:
                    raise DownloadError(error)

                try:
                    kwargs['cur_try'] = nb_try
                    return func(*args, **kwargs)
                except (IOError, DownloadError) as err:
                    nb_try += 1
                    error = err
                    time.sleep(wait)
        return wrapper
    return decorator


class DownloadError(Exception):
    pass


class SharedLink:
    def __init__(self, link, shared_links):
        for shared_link in shared_links:
            if shared_link.url == link:
                break
        else:
            shared_links.append(Dict(url=link))

        self.url = link
        self.shared_links = shared_links

    def __getattribute__(self, name):
        if name in SHARED_ATTRS:
            for shared_link in self.shared_links:
                if shared_link.url == self.url:
                    return shared_link.get(name, None)
        else:
            return object.__getattribute__(self, name)

    def __setattr__(self, name, value):
        if name in SHARED_ATTRS:
            for idx, shared_link in enumerate(self.shared_links):
                if shared_link.url == self.url:
                    shared_link[name] = value
                    self.shared_links[idx] = shared_link
                    break
        else:
            object.__setattr__(self, name, value)

    def __delattr__(self, name):
        if name in SHARED_ATTRS:
            for idx, shared_link in enumerate(self.shared_links):
                if shared_link.url == self.url:
                    if name in shared_link:
                        del(shared_link[name])
                        self.shared_links[idx] = shared_link
                    break
        else:
            object.__setattr__(self, name, value)

    def __repr__(self):
        return {param: getattr(self, param) for param in SHARED_ATTRS}.__repr__()


class Scheduler(multiprocessing.Process):
    def __init__(self, links, dest, parallel):
        multiprocessing.Process.__init__(self)
        manager = multiprocessing.Manager()

        self.dest = dest
        self.parallel = parallel

        self.providers = {}

        # Initialize sharing of links.
        self.shared_links = manager.list()
        for link in links:
            shared_link = SharedLink(link, self.shared_links)
            # Get provider from link.
            site = _SITE_RE.search(link)
            if site is None:
                shared_link.status = 'failed'
                shared_link.msg = 'invalid URL'
            else:
                site = site.group(2).upper()
                if site not in clg.conf:
                    shared_link.status = 'failed'
                    shared_link.msg = 'invalid site'
                else:
                    shared_link.provider = site
                    shared_link.login = clg.conf[site]['login']
                    shared_link.password = clg.conf[site]['password']
                    shared_link.status = 'starting'

    def get_provider(self, shared_link):
        provider_name = shared_link.provider.lower()
        if provider_name not in self.providers:
            provider = imp.load_module(
                provider_name,
                *imp.find_module(
                    provider_name, [os.path.join(sys.path[0], 'lib', 'sites')]))

            provider.init(shared_link)
            self.providers.setdefault(provider_name, provider)
        else:
            provider = self.providers[provider_name]
        return provider

    def run(self):
        # Initialize links' providers (only once by provider) and start download
        # process. Download process retrieve the real link and wait for the order
        # to start download (ie: wait for the status to 'downloading').
        for link in self.shared_links:
            if link.status == 'failed':
                continue

            shared_link = SharedLink(link.url, self.shared_links)
            shared_link.status = 'connecting'
            time.sleep(0.1)
            try:
                provider = self.get_provider(shared_link)
            except DownloadError as err:
                shared_link.status = 'failed'
                shared_link.msg = str(err)
                continue

            Download(shared_link, self.dest, provider).start()

        # Wait for all links to be initialized (in the 'waiting' or 'failed' state).
        initialized = lambda: all(
            link.status in ('waiting', 'failed') for link in self.shared_links)
        while not initialized():
            time.sleep(1)

        # Schedule the start of downloads.
        while True:
            running, waiting = [], []
            for link in self.shared_links:
                if link.status == 'waiting':
                    waiting.append(SharedLink(link.url, self.shared_links))
                elif link.status == 'downloading':
                    running.append(link)

            nb_lunchable_process = self.parallel - len(running)
            while waiting and nb_lunchable_process > 0:
                for link in waiting:
                    link.status = 'downloading'
                    nb_lunchable_process -= 1
                    break

            time.sleep(1)

    def stop(self):
        # Kill all processes.
        for shared_link in self.shared_links:
            if shared_link.pid:
                try:
                    os.kill(shared_link.pid, 15)
                except OSError:
                    pass

        # Kill the scheduler itself.
        os.kill(self.pid, 15)


class Download(multiprocessing.Process):
    def __init__(self, shared_link, dest, provider, max_try=5, wait=1):
        multiprocessing.Process.__init__(self)
        self.shared_link = shared_link
        self.dest = dest
        self.provider = provider
        self.max_try = max_try
        self.wait = wait

    def run(self):
        self.shared_link.pid = self.pid

        if self.shared_link.status == 'failed':
            return

        try:
            # Get real url and file informations.
            self.shared_link.status = 'initializing'
            self.provider.get_link(self.shared_link)
            self.get_file_info()
            self.shared_link.status = 'waiting'
            del(self.shared_link.msg)

            # Wait for receiving the order to download the link.
            while self.shared_link.status == 'waiting':
                time.sleep(1)
                continue

            # Download link.
            self.download()
            self.shared_link.status = 'finished'
        except DownloadError as err:
            self.shared_link.status = 'failed'
            self.shared_link.msg = str(err)

    @trying(max_try=5, wait=1)
    def get_file_info(self, cur_try):
        # Get filename and filesize.
        self.shared_link.msg = 'retrieving informations (%d)' % cur_try
        response = self.provider.session.get(
            self.shared_link.real_url, stream=True, timeout=5)
        self.shared_link.filesize = int(response.headers['content-length'].strip())
        filename = (
            _FILENAME_RE.search(response.headers['content-disposition'].strip()).group(1))
        self.shared_link.filepath = os.path.join(self.dest, filename)
        response.close()

    @trying(max_try=5, wait=1)
    def download(self, cur_try):
        # Check if file already exists and generate header for resuming download.
        if os.path.exists(self.shared_link.filepath):
            mode = 'ab'
            filesize = os.path.getsize(self.shared_link.filepath)
            headers = {'Range': 'bytes=%d-' % filesize}
            self.shared_link.downloaded = filesize
        else:
            headers = {}
            mode = 'wb'

        # Get file.
        response = self.provider.session.get(
            self.shared_link.real_url, headers=headers, stream=True, timeout=10)
        speed_thread = DownloadSpeed(self.shared_link)
        speed_thread.start()
        del(self.shared_link.msg)
        with open(self.shared_link.filepath, mode) as fhandler:
            for chunk in response.iter_content(CHUNK_SIZE):
                if not chunk:
                    continue
                fhandler.write(chunk)
                downloaded = self.shared_link.downloaded or 0
                downloaded += len(chunk)
                self.shared_link.downloaded = downloaded


class DownloadSpeed(threading.Thread):
    def __init__(self, shared_link):
        threading.Thread.__init__(self)
        self.shared_link = shared_link

    def run(self):
        speeds = []
        last_data = self.shared_link.downloaded or 0
        while not self.shared_link.status in ('finished', 'failed'):
            cur_data = os.path.getsize(self.shared_link.filepath)
            diff = cur_data - last_data
            last_data = cur_data
            if len(speeds) == 10:
                speeds.pop(0)
            speeds.append(diff)
            avg_speeds = speeds.copy()
            if len(avg_speeds) >= 3:
                avg_speeds.remove(min(avg_speeds))
                avg_speeds.remove(max(avg_speeds))
            avg_speed = sum(avg_speeds) / len(avg_speeds)

            self.shared_link.speed = avg_speed
            time.sleep(1)
